import json
import unittest
from datetime import datetime, timezone

from webhookkit.processor import MAX_ATTEMPTS, Processor
from webhookkit.signature import sign
from webhookkit.store import SqliteStore

SECRET = "whsec_test"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def body(event_id="evt_1", sequence=1, type_="order.created"):
    return json.dumps({"id": event_id, "type": type_, "sequence": sequence}).encode()


def make_processor(handlers=None, failures=0):
    store = SqliteStore(":memory:")
    applied = []

    def handler(event):
        if len(applied) < failures:
            raise RuntimeError("provider is down")
        applied.append(event.event_id)

    processor = Processor(store, SECRET, handlers or {"order.created": handler},
                          clock=lambda: NOW)
    return processor, store, applied


class IngestTests(unittest.TestCase):
    def test_valid_event_is_accepted(self):
        processor, store, _ = make_processor()
        result = processor.receive(body(), sign(body(), SECRET, timestamp=int(NOW.timestamp())))
        self.assertEqual(result.status, "accepted")
        self.assertEqual(store.count("pending"), 1)

    def test_bad_signature_rejected_and_not_stored(self):
        processor, store, _ = make_processor()
        result = processor.receive(body(), "t=1,v1=deadbeef")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(store.count(), 0)

    def test_replay_is_duplicate(self):
        processor, store, _ = make_processor()
        header = sign(body(), SECRET, timestamp=int(NOW.timestamp()))
        self.assertEqual(processor.receive(body(), header).status, "accepted")
        self.assertEqual(processor.receive(body(), header).status, "duplicate")
        self.assertEqual(store.count(), 1)

    def test_malformed_payload_rejected(self):
        processor, _, _ = make_processor()
        bad = b'{"id": "x"}'
        result = processor.receive(bad, sign(bad, SECRET, timestamp=int(NOW.timestamp())))
        self.assertEqual(result.status, "rejected")
        self.assertIn("bad payload", result.reason)


class ProcessingTests(unittest.TestCase):
    def send(self, processor, event_id, sequence):
        payload = body(event_id, sequence)
        header = sign(payload, SECRET, timestamp=int(NOW.timestamp()))
        return processor.receive(payload, header)

    def test_handler_runs_once(self):
        processor, store, applied = make_processor()
        self.send(processor, "evt_1", 1)
        results = processor.drain()
        self.assertEqual([r.status for r in results], ["processed"])
        self.assertEqual(applied, ["evt_1"])
        self.assertEqual(store.count("processed"), 1)

    def test_out_of_order_is_parked(self):
        processor, store, applied = make_processor()
        self.send(processor, "evt_2", 2)
        first = processor.drain()
        self.assertEqual(first[0].status, "out_of_order")
        self.assertEqual(applied, [])
        # the missing earlier event arrives -> both apply, in sequence
        self.send(processor, "evt_1", 1)
        statuses = [r.status for r in processor.drain()]
        self.assertEqual(statuses, ["processed", "processed"])
        self.assertEqual(applied, ["evt_1", "evt_2"])

    def test_failure_is_retried_then_dead_lettered(self):
        processor, store, _ = make_processor(failures=99)
        self.send(processor, "evt_1", 1)
        results = processor.drain()
        self.assertEqual(results[0].status, "failed")
        event = store.get("evt_1")
        self.assertEqual(event.status, "dead")
        self.assertEqual(event.attempts, MAX_ATTEMPTS)
        self.assertIn("provider is down", event.last_error)

    def test_transient_failure_then_success(self):
        store = SqliteStore(":memory:")
        applied = []
        attempts = {"n": 0}

        def flaky(event):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("temporary")
            applied.append(event.event_id)

        processor = Processor(store, SECRET, {"order.created": flaky}, clock=lambda: NOW)
        self.send(processor, "evt_1", 1)
        results = processor.drain()
        self.assertEqual(results[0].status, "processed")
        self.assertEqual(applied, ["evt_1"])

    def test_unknown_type_goes_to_dead_letter(self):
        processor, store, _ = make_processor()
        self.send(processor, "evt_9", 1)
        processor.handlers = {}
        results = processor.drain()
        self.assertEqual(results[0].status, "failed")
        self.assertEqual(store.get("evt_9").status, "dead")

    def test_http_status_mapping(self):
        processor, _, _ = make_processor()
        self.assertEqual(processor.receive(b"{}", "nope").http_status, 401)
