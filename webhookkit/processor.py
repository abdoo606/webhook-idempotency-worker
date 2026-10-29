"""Receive → verify → dedupe → apply in order → retry → dead-letter."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .signature import verify
from .store import Event, SqliteStore

Handler = Callable[[Event], None]
MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class Result:
    status: str           # accepted | duplicate | rejected | processed | failed | out_of_order
    event_id: str = ""
    reason: str = ""

    @property
    def http_status(self) -> int:
        return {"accepted": 202, "duplicate": 200, "processed": 200,
                "failed": 500, "rejected": 401, "out_of_order": 202}.get(self.status, 200)


class Processor:
    """Ordering is enforced per ``type`` using the provider's ``sequence``.

    A gap means an earlier event was lost: the later one is parked instead of
    applied out of order, because "order shipped" before "order created" is
    worse than a delayed webhook.
    """

    def __init__(self, store: SqliteStore, secret: str, handlers: dict[str, Handler],
                 clock: Callable[[], datetime] | None = None):
        self.store = store
        self.secret = secret
        self.handlers = handlers
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # -- ingest ------------------------------------------------------------
    def receive(self, body: bytes, signature_header: str) -> Result:
        if not verify(body, signature_header, self.secret, now=int(self._clock().timestamp())):
            return Result("rejected", reason="bad signature")
        try:
            payload = json.loads(body)
            event = Event(event_id=str(payload["id"]), type=str(payload["type"]),
                          sequence=int(payload.get("sequence", 0)),
                          payload=json.dumps(payload, sort_keys=True))
        except (ValueError, KeyError, TypeError) as exc:
            return Result("rejected", reason=f"bad payload: {exc}")

        if not self.store.insert_event(event, self._clock().isoformat()):
            return Result("duplicate", event_id=event.event_id,
                          reason="already received")
        return Result("accepted", event_id=event.event_id)

    # -- processing --------------------------------------------------------
    def drain(self, max_events: int = 100) -> list[Result]:
        results: list[Result] = []
        for event in self.store.pending()[:max_events]:
            results.append(self._apply(event))
            if results[-1].status in {"failed", "out_of_order"} and \
                    self.store.get(event.event_id).status == "pending":
                break  # preserve ordering: stop at the first event we cannot apply
        return results

    def _apply(self, event: Event) -> Result:
        last_applied = self.store.last_processed_sequence(event.type)
        if event.sequence > last_applied + 1:
            return Result("out_of_order", event.event_id,
                          f"expected sequence {last_applied + 1}, got {event.sequence}")

        handler = self.handlers.get(event.type)
        if handler is None:
            self.store.mark(event.event_id, "dead", f"no handler for {event.type!r}")
            return Result("failed", event.event_id, "unhandled type")

        attempts = self.store.get(event.event_id).attempts
        while attempts < MAX_ATTEMPTS:
            try:
                handler(event)
            except Exception as exc:  # noqa: BLE001 - the whole point is to survive it
                attempts += 1
                self.store.mark(event.event_id,
                                "dead" if attempts >= MAX_ATTEMPTS else "pending",
                                f"{type(exc).__name__}: {exc}")
                if attempts >= MAX_ATTEMPTS:
                    return Result("failed", event.event_id, "moved to dead-letter")
            else:
                self.store.mark(event.event_id, "processed")
                return Result("processed", event.event_id)
        return Result("failed", event.event_id, "attempts exhausted")
