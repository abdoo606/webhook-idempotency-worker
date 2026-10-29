import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from webhookkit.cli import main

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_replay_sample(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(["replay", "--file", str(ROOT / "samples" / "order_created.json")])
        self.assertEqual(code, 0)
        self.assertIn('"ingest": "accepted"', out.getvalue())
        self.assertIn('"applied": [\n    "evt_1001"', out.getvalue())

    def test_missing_file_crashes_cleanly(self):
        with self.assertRaises(FileNotFoundError):
            main(["replay", "--file", "/nope.json"])
