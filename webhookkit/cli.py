"""CLI: replay a sample webhook file through the processor."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .processor import Processor
from .signature import sign
from .store import SqliteStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="webhookkit", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("replay", help="sign and process a webhook JSON file")
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--secret", default="whsec_demo")
    args = parser.parse_args(argv)

    body = args.file.read_bytes()
    header = sign(body, args.secret)
    store = SqliteStore(":memory:")
    applied: list[str] = []

    def handler(event):
        applied.append(event.event_id)

    processor = Processor(store, args.secret, {"order.created": handler}, )
    first = processor.receive(body, header)
    print(json.dumps({"ingest": first.status, "id": first.event_id}, indent=2))
    for result in processor.drain():
        print(json.dumps({"apply": result.status, "reason": result.reason}, indent=2))
    print(json.dumps({"applied": applied, "dead": store.count("dead")}, indent=2))
    return 0 if first.status == "accepted" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
