import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from capy_application_acceptor.acceptance import evaluate
from capy_application_acceptor.candidate import read_candidate
from capy_application_acceptor.errors import AcceptorError
from capy_application_acceptor.locks import IdentityLock
from capy_application_acceptor.profile import read_profile
from capy_application_acceptor.process import run_bounded, scrubbed_env
from capy_application_acceptor.service import Service
from tests.support import FIXTURES, RELEASE, ROOT, profile_bytes, profile_document


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("bounded test condition did not arrive")
        time.sleep(.02)


def alive(pid):
    if os.name == "nt":
        import ctypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k.OpenProcess.restype = ctypes.c_void_p
        k.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k.OpenProcess(0x100000, False, pid)
        if not handle:
            return False
        try:
            return k.WaitForSingleObject(handle, 0) == 258
        finally:
            k.CloseHandle(handle)
    result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


class DurabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cb = (FIXTURES / "fixed-v1.capyrc").read_bytes()
        cls.pb = (FIXTURES / "greeting.capya").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            cls.result = evaluate(read_candidate(cls.cb), read_profile(cls.pb), RELEASE, Path(td))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = Service(Path(self.temp.name), RELEASE)

    def accept(self):
        with patch("capy_application_acceptor.service.evaluate", return_value=self.result) as execute:
            data = self.service.accept(self.cb, self.pb)
            execute.assert_called_once()
        return data, json.loads(data)["acceptance_id"]

    def test_restart_replay_without_execution_and_journal(self):
        data, aid = self.accept()
        restarted = Service(Path(self.temp.name), RELEASE)
        with patch("capy_application_acceptor.service.evaluate", side_effect=AssertionError("replayed execution")):
            self.assertEqual(restarted.accept(self.cb, self.pb), data)
        inspection = restarted.inspect(aid)
        self.assertEqual(inspection["document"], json.loads(data))
        self.assertEqual(inspection["generation"], 1)
        self.assertEqual([e["kind"] for e in inspection["events"]], ["candidate_ingested", "profile_ingested", "identity_allocated", "attempt_preparing", "toolchain_validated", "cleanup_terminal", "receipt_committed"])
        self.assertFalse(list((Path(self.temp.name) / "work").iterdir()))

    def test_same_identity_locked_other_identity_independent(self):
        _, aid = self.accept()
        with IdentityLock(self.service.store.root / "locks" / (aid + ".lock")) as lock:
            self.assertTrue(lock.acquire())
            with self.assertRaisesRegex(AcceptorError, "ACCEPTANCE_IN_PROGRESS"):
                self.service.accept(self.cb, self.pb)
            self.assertTrue(self.service.inspect(aid)["live"])
            doc = profile_document(); doc["interaction_expectations"]["purpose"] = "Different purpose."
            other = json.loads(self.service.accept(self.cb, profile_bytes(doc)))
            self.assertNotEqual(other["acceptance_id"], aid)

    def stale(self):
        _, aid = self.accept()
        row = self.service.store.row(aid)
        generation = self.service.store.allocate(aid, json.loads(row["identity_json"]))
        run = self.service.store.create_work(aid, generation)
        (run / "test-owned").write_bytes(b"unfinished")
        return aid, run

    def test_stale_inspection_then_retry(self):
        aid, run = self.stale()
        inspected = self.service.inspect(aid)
        self.assertEqual(inspected["status"], "INTERRUPTED")
        self.assertIsNone(inspected["document"])
        self.assertFalse(run.parent.exists())
        data, retried = self.accept()
        self.assertEqual(aid, retried)
        self.assertEqual(self.service.inspect(aid)["generation"], 3)

    def test_uncertain_marker_never_deleted(self):
        aid, run = self.stale()
        (run.parent / "owner.json").write_text("{}")
        with self.assertRaisesRegex(AcceptorError, "CLEANUP_FAILED"):
            self.service.inspect(aid)
        self.assertTrue((run / "test-owned").exists())
        row = self.service.store.row(aid)
        self.assertEqual(row["status"], "FAILED")
        self.assertIsNone(row["document_sha256"])

    def test_cleanup_failure_withholds_document(self):
        with patch("capy_application_acceptor.service.evaluate", return_value=self.result), patch.object(self.service.store, "cleanup", side_effect=AcceptorError("CLEANUP_FAILED")):
            with self.assertRaisesRegex(AcceptorError, "CLEANUP_FAILED"):
                self.service.accept(self.cb, self.pb)
        with self.service.store.connect() as db:
            row = db.execute("SELECT * FROM attempts").fetchone()
        self.assertEqual(row["status"], "FAILED")
        self.assertIsNone(row["document_sha256"])
        self.assertFalse(list((self.service.store.root / "documents").iterdir()))

    def test_corrupted_input_copy_rejected_on_replay(self):
        _, aid = self.accept()
        row = self.service.store.row(aid)
        self.service.store.blob_path("candidates", row["candidate_sha256"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(AcceptorError, "STORE_INTEGRITY_FAILED"):
            self.service.accept(self.cb, self.pb)
        with self.assertRaisesRegex(AcceptorError, "STORE_INTEGRITY_FAILED"):
            self.service.inspect(aid)

    def test_corrupted_document_and_index_rejected(self):
        _, aid = self.accept()
        row = self.service.store.row(aid)
        self.service.store.blob_path("documents", row["document_sha256"]).write_bytes(b"{}")
        with self.assertRaisesRegex(AcceptorError, "STORE_INTEGRITY_FAILED"):
            self.service.inspect(aid)


class ProcessOwnershipTests(unittest.TestCase):
    def test_normal_parent_exit_kills_redirected_descendant(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            result = run_bounded([sys.executable, str(ROOT / "tests/process_fixture.py"), "app", td, "normal"], input_bytes=None,
                timeout_seconds=10, max_stdout=1024, max_stderr=1024, env=scrubbed_env({}), cwd=root)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.stdout, b"complete\n")
            self.assertFalse(alive(int((root / "child.pid").read_text())))

    def interrupt(self, method):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT))
            owner = subprocess.Popen([sys.executable, str(ROOT / "tests/process_fixture.py"), "owner", td, "service"], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                wait_for(lambda: (root / "child.pid").exists())
                service = Service(root / "store", RELEASE)
                with service.store.connect() as db:
                    aid = db.execute("SELECT acceptance_id FROM attempts").fetchone()[0]
                self.assertTrue(service.inspect(aid)["live"])
                getattr(owner, method)(); owner.wait(timeout=10)
                pids = [int((root / name).read_text()) for name in ("parent.pid", "child.pid")]
                wait_for(lambda: not any(alive(pid) for pid in pids))
                # Guardian may retain ownership briefly while confirming cleanup.
                wait_for(lambda: not service.inspect(aid)["live"])
                inspection = service.inspect(aid)
                self.assertEqual(inspection["status"], "INTERRUPTED")
                self.assertIsNone(inspection["document"])
                self.assertFalse(list((root / "store/work").iterdir()))
                retry = json.loads(service.accept((FIXTURES / "fixed-v1.capyrc").read_bytes(), (FIXTURES / "greeting.capya").read_bytes()))
                self.assertEqual(retry["status"], "ACCEPTED")
                self.assertEqual(retry["acceptance_id"], aid)
            finally:
                if owner.poll() is None:
                    owner.kill(); owner.wait(timeout=10)

    def test_killed_owner_cleans_tree_reconciles_and_retries(self):
        self.interrupt("kill")

    def test_terminated_owner_cleans_tree_reconciles_and_retries(self):
        self.interrupt("terminate")
