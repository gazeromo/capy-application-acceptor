"""Run-2 regressions for bounded causal repairs (fast, no venv)."""
import io
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path


class ProfileInvalidTests(unittest.TestCase):
    def test_unknown_root_field_is_invalid(self):
        from capy_application_acceptor.errors import AcceptorError
        from capy_application_acceptor.profile import read_profile
        from tests.support import archive, canonical, profile_document

        doc = profile_document()
        doc["unknown_field"] = True
        data = archive({"ACCEPTANCE-PROFILE.json": canonical(doc)})
        with self.assertRaises(AcceptorError) as caught:
            read_profile(data)
        self.assertEqual(caught.exception.code, "ACCEPTANCE_PROFILE_INVALID")

    def test_unknown_case_field_is_invalid(self):
        from capy_application_acceptor.errors import AcceptorError
        from capy_application_acceptor.profile import read_profile
        from tests.support import profile_bytes, profile_document

        doc = profile_document()
        doc["cases"][0]["unknown_field"] = 1
        data = profile_bytes(doc)
        with self.assertRaises(AcceptorError) as caught:
            read_profile(data)
        self.assertEqual(caught.exception.code, "ACCEPTANCE_PROFILE_INVALID")

    def test_bool_limit_is_invalid(self):
        from capy_application_acceptor.errors import AcceptorError
        from capy_application_acceptor.profile import read_profile
        from tests.support import profile_bytes, profile_document

        doc = profile_document()
        doc["limits"]["timeout_seconds"] = True
        data = profile_bytes(doc)
        with self.assertRaises(AcceptorError) as caught:
            read_profile(data)
        self.assertEqual(caught.exception.code, "ACCEPTANCE_PROFILE_INVALID")


@unittest.skipUnless(sys.platform in ('linux','win32'), 'Owner amendment: no native macOS execution backend')
class ProcessTreeTests(unittest.TestCase):
    def test_descendant_tree_bounded_wall_time(self):
        from capy_application_acceptor.process import run_bounded

        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            res = run_bounded(
                [sys.executable, "-c",
                 "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(1.3)']); print('parent done', flush=True)"],
                input_bytes=None,
                timeout_seconds=0.1,
                max_stdout=1024 * 1024,
                max_stderr=1024 * 1024,
                env=dict(os.environ),
                cwd=tmp,
            )
            dur = (time.monotonic() - start) * 1000
            self.assertTrue(res.timed_out)
            self.assertIsNone(res.exit_code)
            self.assertLess(dur, 1000, f"wall time must be bounded, got {dur:.0f}ms")

    def test_overflow_precedes_timeout(self):
        from capy_application_acceptor.process import run_bounded

        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            res = run_bounded(
                [sys.executable, "-c",
                 "import sys,time; sys.stdout.buffer.write(b'X'*20); sys.stdout.buffer.flush(); time.sleep(2)"],
                input_bytes=None,
                timeout_seconds=2,
                max_stdout=8,
                max_stderr=1024 * 1024,
                env=dict(os.environ),
                cwd=tmp,
            )
            dur = (time.monotonic() - start) * 1000
            self.assertTrue(res.stdout_truncated)
            self.assertFalse(res.timed_out)
            self.assertEqual(len(res.stdout), 9)
            self.assertLess(dur, 1000, f"overflow must be prompt, got {dur:.0f}ms")


class ArtifactAnomalyTests(unittest.TestCase):
    def test_dotfile_and_unsafe_reject_empty(self):
        from capy_application_acceptor.comparison import classify_case
        from capy_application_acceptor.execution import collect_artifacts

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".undeclared").write_bytes(b"hi")
            (root / "bad name.txt").write_bytes(b"hi")
            arts, anomaly = collect_artifacts(root)
            self.assertEqual(arts, [])
            self.assertIsNotNone(anomaly)
            # Successful empty expectation must not match.
            cls_ok = classify_case(
                expect={"status": "ok", "result": {}, "artifacts": [], "failure_code": None},
                timed_out=False, output_limited=False, secret_hit=False,
                exit_code=0, stdout=b'{"artifacts":[]}\n', stderr=b"",
                actual_artifacts=arts, envelope_error=None,
                observed_result={}, observed_failure_code=None,
                observed_status="ok", artifact_anomaly=anomaly,
            )
            self.assertEqual(cls_ok, "REJECTED_ARTIFACT_SET_MISMATCH")
            # Failed empty expectation must not match either.
            cls_failed = classify_case(
                expect={"status": "failed", "result": None, "artifacts": [], "failure_code": "E"},
                timed_out=False, output_limited=False, secret_hit=False,
                exit_code=2, stdout=b"", stderr=b"E\n",
                actual_artifacts=arts, envelope_error=None,
                observed_result=None, observed_failure_code="E",
                observed_status="failed", artifact_anomaly=anomaly,
            )
            self.assertEqual(cls_failed, "REJECTED_ARTIFACT_SET_MISMATCH")

    def test_symlink_and_dir_reject(self):
        from capy_application_acceptor.execution import collect_artifacts

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ok.txt").write_bytes(b"data")
            try:
                os.symlink("ok.txt", root / "link.txt")
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            (root / "subdir").mkdir()
            arts, anomaly = collect_artifacts(root)
            self.assertIsNotNone(anomaly)
            # Unsafe names never projected; safe file retained.
            self.assertEqual([n for n, _ in arts], ["ok.txt"])

    def test_unsafe_not_projected(self):
        from capy_application_acceptor import codec
        from capy_application_acceptor.execution import collect_artifacts

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "bad name.txt").write_bytes(b"x")
            arts, anomaly = collect_artifacts(root)
            self.assertEqual(arts, [])
            self.assertEqual(anomaly, "unsafe-name")
            self.assertFalse(codec.is_safe_basename("bad name.txt"))


class BoundedCollectionTests(unittest.TestCase):
    def test_huge_file_bounded_to_limit_plus_one(self):
        from capy_application_acceptor.execution import collect_artifacts

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "big.bin").write_bytes(b"A" * (3 * 1024 * 1024))
            arts, _ = collect_artifacts(root, 1024 * 1024)
            total = sum(len(b) for _, b in arts)
            self.assertEqual(total, 1024 * 1024 + 1)
            self.assertGreater(total, 1024 * 1024)

    def test_canary_beyond_1mib_scanned(self):
        from capy_application_acceptor.execution import collect_artifacts
        from capy_application_acceptor.scan import scan_many

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            canary = b"CAPY_ACCEPTOR_SECRET_CANARY_V0"
            data = b"A" * (2 * 1024 * 1024) + canary + b"B" * 100
            (root / "a.bin").write_bytes(data)
            arts, _ = collect_artifacts(root, 8 * 1024 * 1024)
            self.assertTrue(arts)
            self.assertTrue(scan_many([arts[0][1]]))
            # Old 1MiB prefix would miss it.
            self.assertFalse(scan_many([data[: 1024 * 1024 + 1]]))


class StrictEnvelopeTests(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        from capy_application_acceptor.comparison import classify_case, parse_success_envelope

        dup = b'{"message":"wrong","message":"hello","artifacts":[]}\n'
        result, err = parse_success_envelope(dup)
        self.assertIsNone(result)
        self.assertIsNotNone(err)
        # Must not match expected hello via last-wins.
        cls = classify_case(
            expect={"status": "ok", "result": {"message": "hello"}, "artifacts": [], "failure_code": None},
            timed_out=False, output_limited=False, secret_hit=False,
            exit_code=0, stdout=dup, stderr=b"",
            actual_artifacts=[], envelope_error=err,
            observed_result=None, observed_failure_code=None,
            observed_status="error",
        )
        self.assertEqual(cls, "REJECTED_APPLICATION_EXIT")

    def test_nonfinite_rejected(self):
        from capy_application_acceptor.comparison import parse_success_envelope

        result, err = parse_success_envelope(b'{"x":NaN,"artifacts":[]}\n')
        self.assertIsNone(result)
        self.assertIsNotNone(err)


class StrictReceiptIntTests(unittest.TestCase):
    def _stage_base(self, name, facts):
        return {
            "exit_code": 0 if name not in ("source_mutation_check", "package_compare", "archive_preserve") else None,
            "facts": facts,
            "name": name,
            "status": "PASSED",
            "stderr_truncated_bytes": 0,
            "stdout_truncated_bytes": 0,
            "stored_stderr_bytes": 0,
            "stored_stderr_sha256": "0" * 64,
            "stored_stdout_bytes": 0,
            "stored_stdout_sha256": "0" * 64,
        }

    def test_float_sizes_rejected(self):
        from capy_application_acceptor.candidate import _validate_stage
        from capy_application_acceptor.errors import AcceptorError

        app = b"hello"
        outer = b'{"a":1}'
        inner = b'{"a":1}'
        # package_compare with float sizes numerically equal must fail.
        import hashlib

        app_sha = hashlib.sha256(app).hexdigest()
        stage = self._stage_base("package_compare", {
            "sha256_a": app_sha, "sha256_b": app_sha,
            "size_a": float(len(app)), "size_b": len(app),
        })
        with self.assertRaises(AcceptorError):
            _validate_stage(stage, app, outer, inner)
        # archive_preserve float.
        stage2 = self._stage_base("archive_preserve", {
            "sha256": app_sha, "size_bytes": float(len(app)),
        })
        stage2["exit_code"] = None
        with self.assertRaises(AcceptorError):
            _validate_stage(stage2, app, outer, inner)
        # interaction_preserve float.
        outer_sha = hashlib.sha256(outer).hexdigest()
        inner_sha = hashlib.sha256(inner).hexdigest()
        stage3 = self._stage_base("interaction_preserve", {
            "candidate_unchanged": True, "canonical_sha256": outer_sha,
            "canonical_size_bytes": float(len(outer)),
            "source_sha256": inner_sha, "timed_out": False,
        })
        stage3["exit_code"] = 0
        with self.assertRaises(AcceptorError):
            _validate_stage(stage3, app, outer, inner)

    def test_bool_sizes_rejected(self):
        from capy_application_acceptor.candidate import _validate_stage
        from capy_application_acceptor.errors import AcceptorError

        app = b"x" * 1
        outer = b'{"a":1}'
        inner = b'{"a":1}'
        import hashlib

        app_sha = hashlib.sha256(app).hexdigest()
        stage = self._stage_base("archive_preserve", {"sha256": app_sha, "size_bytes": True})
        stage["exit_code"] = None
        with self.assertRaises(AcceptorError):
            _validate_stage(stage, app, outer, inner)


class BoundedZipTests(unittest.TestCase):
    def test_deflated_outer_rejected_without_expansion(self):
        from capy_application_acceptor.candidate import read_candidate
        from capy_application_acceptor.errors import AcceptorError
        from tests.support import unpack
        from tests.support import FIXTURES

        valid = unpack((FIXTURES / "fixed-v1.capyrc").read_bytes())
        huge = b"A" * (2 * 1024 * 1024)
        members = dict(valid)
        members["RELEASE-CANDIDATE.json"] = huge
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, data in members.items():
                item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                item.create_system = 3
                item.external_attr = 0o100644 << 16
                item.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(item, data)
        bomb = out.getvalue()
        # Compressed is small, expanded is huge; must reject as integrity quickly.
        self.assertLess(len(bomb), 1024 * 1024)
        with self.assertRaises(AcceptorError) as caught:
            read_candidate(bomb)
        self.assertEqual(caught.exception.code, "RELEASE_CANDIDATE_INTEGRITY_FAILED")


if __name__ == "__main__":
    unittest.main()
