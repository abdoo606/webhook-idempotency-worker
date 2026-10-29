# webhook-idempotency-worker

Receive provider webhooks safely: verify the signature, deduplicate retries,
apply in sequence order, retry transient failures, dead-letter the rest.

Zero dependencies (stdlib only), Python 3.9+.

## Why

Webhook endpoints fail in four specific ways, and each one is worse than the last:

| Failure | Symptom | Handled by |
|---|---|---|
| Forged request | anyone can create orders | HMAC-SHA256 over `timestamp.payload`, constant-time compare, 5-minute window |
| Provider retry | the same event applied twice | unique `event_id`, replay returns `duplicate` |
| Out-of-order delivery | "shipped" lands before "created" | per-type sequence gate; later events are parked |
| Handler outage | event lost forever | bounded retries, then `dead` with `last_error` preserved |

## Usage

```bash
python -m webhookkit replay --file samples/order_created.json
pip install -r requirements.txt   # not needed: stdlib only
python -m unittest discover -s tests -v
```

## Design notes

- **Verify before parse.** The signature check happens on raw bytes; parsing
  untrusted JSON first is how you end up with a poisoned store.
- **A gap stops the queue.** `drain()` stops at the first event it cannot
  apply rather than skipping ahead — a delayed webhook is better than an
  inconsistent one.
- **Attempts live in the store**, not in memory, so a restart does not reset
  the retry budget and turn an outage into an infinite loop.
- **Unhandled event types are dead-lettered, not dropped**, so a new provider
  event type shows up as work instead of disappearing.

## Tests

18 tests covering signature tampering, stale timestamps, duplicate delivery,
ordering, transient failure, permanent failure and the CLI.
