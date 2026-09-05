"""Contributor-owned meaningful checks (fast, no hidden fixtures)."""
import copy
import tempfile
import unittest
from pathlib import Path

from capy_application_acceptor import codec, scan
from capy_application_acceptor.acceptance import evaluate
from capy_application_acceptor.candidate import read_candidate
from capy_application_acceptor.comparison import classify_case
from capy_application_acceptor.errors import AcceptorError
from capy_application_acceptor.profile import read_profile
from tests.support import FIXTURES, RELEASE, profile_bytes, profile_document


class CodecTests(unittest.TestCase):
    def test_canonical_rejects_trailing_and_order(self):
        with self.assertRaises(ValueError):
            codec.check_canonical_json_bytes(b'{"a":1}\n')
        with self.assertRaises(ValueError):
            codec.check_canonical_json_bytes(b'{"b":1,"a":2}')
        self.assertEqual(codec.check_canonical_json_bytes(b'{"a":1,"b":2}'), {"a": 1, "b": 2})

    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ValueError):
            codec.parse_strict_json(b'{"a":1,"a":2}')

    def test_safe_basename(self):
        self.assertTrue(codec.is_safe_basename("text-report.txt"))
        self.assertFalse(codec.is_safe_basename("CON"))
        self.assertFalse(codec.is_safe_basename("a."))
        self.assertFalse(codec.is_safe_basename("../x"))


class ScanTests(unittest.TestCase):
    def test_canary_and_keys(self):
        self.assertFalse(scan.contains_secret(b"hello world"))
        self.assertTrue(scan.contains_secret(b"prefix CAPY_ACCEPTOR_SECRET_CANARY_V0 suffix"))
        self.assertTrue(scan.contains_secret(b"ghp_" + b"a" * 36))
        self.assertTrue(scan.contains_secret(b"-----BEGIN PRIVATE KEY-----"))

    def test_no_raw_leak_in_findings(self):
        # Findings must never contain raw values; projection uses constant.
        candidate = read_candidate((FIXTURES / "fixed-v1.capyrc").read_bytes())
        profile = read_profile(profile_bytes())
        doc = copy.deepcopy(profile_document())
        doc["interaction_expectations"]["purpose"] = "different purpose"
        from tests.support import profile_bytes as pb

        other = read_profile(pb(doc))
        with tempfile.TemporaryDirectory() as temp:
            ev = evaluate(candidate, other, RELEASE, Path(temp))
            self.assertEqual(ev.classification, "REJECTED_INTERACTION_MISMATCH")
            self.assertEqual(ev.document["secret_scan"], {"status": "PASSED", "findings": []})


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.candidate = read_candidate((FIXTURES / "fixed-v1.capyrc").read_bytes())
        self.profile = read_profile(profile_bytes())

    def test_bad_release_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AcceptorError):
                evaluate(self.candidate, self.profile, {"bad": 1}, Path(temp))
            with self.assertRaises(AcceptorError):
                bad = dict(RELEASE)
                bad["implementation_commit"] = "ZZZ"
                evaluate(self.candidate, self.profile, bad, Path(temp))

    def test_application_mismatch(self):
        artifact_profile = read_profile(profile_bytes(artifact=True))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AcceptorError) as caught:
                evaluate(self.candidate, artifact_profile, RELEASE, Path(temp))
            self.assertEqual(caught.exception.code, "APPLICATION_PROFILE_MISMATCH")

    def test_toolchain_untrusted_profile(self):
        doc = profile_document()
        doc["candidate_requirements"]["toolchain_wheel_sha256"] = "0" * 64
        from tests.support import archive, canonical

        data = archive({"ACCEPTANCE-PROFILE.json": canonical(doc)})
        with self.assertRaises(AcceptorError) as caught:
            read_profile(data)
        self.assertEqual(caught.exception.code, "TOOLCHAIN_UNTRUSTED")

    def test_interaction_mismatch_early_and_cleanup(self):
        doc = profile_document()
        doc["interaction_expectations"]["purpose"] = "A different exact purpose."
        from tests.support import profile_bytes as pb

        other = read_profile(pb(doc))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ev = evaluate(self.candidate, other, RELEASE, root)
            self.assertEqual(ev.classification, "REJECTED_INTERACTION_MISMATCH")
            self.assertEqual(ev.document["cases"], [])
            self.assertEqual(list(root.iterdir()), [])


class ComparisonTests(unittest.TestCase):
    def test_numeric_representations_distinct(self):
        # true vs 1 vs 1.0 must be distinct via canonical bytes.
        self.assertNotEqual(codec.canonical_bytes(True), codec.canonical_bytes(1))
        self.assertNotEqual(codec.canonical_bytes(1), codec.canonical_bytes(1.0))

    def test_precedence_secret_first(self):
        expect = {"status": "ok", "result": {"a": 1}, "artifacts": [], "failure_code": None}
        cls = classify_case(
            expect=expect,
            timed_out=True,
            output_limited=True,
            secret_hit=True,
            exit_code=0,
            stdout=b"{}",
            stderr=b"",
            actual_artifacts=[],
            envelope_error=None,
            observed_result={"a": 1},
            observed_failure_code=None,
            observed_status="ok",
        )
        self.assertEqual(cls, "REJECTED_SECRET_BOUNDARY")

    def test_failed_with_artifacts_is_set_mismatch(self):
        expect = {"status": "failed", "result": None, "artifacts": [], "failure_code": "E"}
        cls = classify_case(
            expect=expect,
            timed_out=False,
            output_limited=False,
            secret_hit=False,
            exit_code=2,
            stdout=b"",
            stderr=b"E\n",
            actual_artifacts=[("x.txt", b"data")],
            envelope_error=None,
            observed_result=None,
            observed_failure_code="E",
            observed_status="failed",
        )
        self.assertEqual(cls, "REJECTED_ARTIFACT_SET_MISMATCH")


class ImportHygieneTests(unittest.TestCase):
    def test_no_devkit_or_model_imports(self):
        import capy_application_acceptor.candidate as c
        import capy_application_acceptor.profile as p
        import capy_application_acceptor.acceptance as a

        for mod in (c, p, a):
            with open(mod.__file__, encoding="utf-8") as f:
                src = f.read()
            self.assertNotIn("capy_script", src)
            self.assertNotIn("capy_developer", src)
            self.assertNotIn("import requests", src)


if __name__ == "__main__":
    unittest.main()
