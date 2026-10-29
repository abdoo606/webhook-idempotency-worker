import unittest

from webhookkit.signature import sign, verify

SECRET = "whsec_test"
BODY = b'{"id":"evt_1","type":"order.created","sequence":1}'


class SignatureTests(unittest.TestCase):
    def test_roundtrip(self):
        header = sign(BODY, SECRET, timestamp=1_700_000_000)
        self.assertTrue(verify(BODY, header, SECRET, now=1_700_000_000))

    def test_tampered_body_fails(self):
        header = sign(BODY, SECRET, timestamp=1_700_000_000)
        self.assertFalse(verify(BODY + b" ", header, SECRET, now=1_700_000_000))

    def test_wrong_secret_fails(self):
        header = sign(BODY, SECRET, timestamp=1_700_000_000)
        self.assertFalse(verify(BODY, header, "other", now=1_700_000_000))

    def test_stale_timestamp_rejected(self):
        header = sign(BODY, SECRET, timestamp=1_700_000_000)
        self.assertFalse(verify(BODY, header, SECRET, now=1_700_000_000 + 301))

    def test_malformed_header_is_false_not_exception(self):
        for header in ("", "garbage", "t=abc,v1=def", "v1=abc"):
            with self.subTest(header=header):
                self.assertFalse(verify(BODY, header, SECRET, now=1_700_000_000))

    def test_empty_secret_rejected(self):
        with self.assertRaises(ValueError):
            sign(BODY, "")
