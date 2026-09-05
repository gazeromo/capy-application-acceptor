"""SQLite index/journal and independently content-addressed copied bytes."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid
import time
from .locks import IdentityLock

from .codec import canonical_bytes, parse_strict_json
from .errors import AcceptorError

SCHEMA_VERSION = 1
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_AID = re.compile(r"acc_[0-9a-f]{32}\Z")
_WORK = re.compile(r"(acc_[0-9a-f]{32})-([0-9a-f]{32})\Z")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def validate_id(aid):
    if not isinstance(aid, str) or not _AID.fullmatch(aid):
        raise AcceptorError("ACCEPTANCE_ID_INVALID")


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("candidates", "profiles", "documents", "locks", "work"):
            p = self.root / name
            if p.is_symlink():
                raise AcceptorError("STORE_INTEGRITY_FAILED")
            p.mkdir(exist_ok=True)
        self.path = self.root / "acceptor.sqlite3"
        if self.path.is_symlink():
            raise AcceptorError("STORE_INTEGRITY_FAILED")
        with IdentityLock(self.root / "locks/schema.lock") as lock:
            deadline = time.monotonic() + 10
            while not lock.acquire():
                if time.monotonic() >= deadline:
                    raise AcceptorError("STORE_BUSY")
                time.sleep(0.02)
            self._initialize()

    def _initialize(self):
        with self.connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            application = db.execute("PRAGMA application_id").fetchone()[0]
            if version not in (0, SCHEMA_VERSION) or application not in (0, 1128350000):
                raise AcceptorError("STORE_SCHEMA_UNSUPPORTED")
            if version == 0 and db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                raise AcceptorError("STORE_SCHEMA_UNSUPPORTED")
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS candidates (
                  sha256 TEXT PRIMARY KEY, candidate_id TEXT NOT NULL,
                  application_id TEXT NOT NULL, stored_path TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL, first_seen_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles (
                  sha256 TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
                  application_id TEXT NOT NULL, stored_path TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL, first_seen_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (
                  acceptance_id TEXT PRIMARY KEY,
                  candidate_sha256 TEXT NOT NULL REFERENCES candidates(sha256),
                  profile_sha256 TEXT NOT NULL REFERENCES profiles(sha256),
                  identity_json TEXT NOT NULL, generation INTEGER NOT NULL,
                  status TEXT NOT NULL, classification TEXT,
                  started_at TEXT NOT NULL, terminal_at TEXT,
                  document_sha256 TEXT, document_path TEXT,
                  error_code TEXT, error_detail TEXT, work_name TEXT);
                CREATE TABLE IF NOT EXISTS case_results (
                  acceptance_id TEXT NOT NULL REFERENCES attempts(acceptance_id),
                  generation INTEGER NOT NULL, case_order INTEGER NOT NULL,
                  case_id TEXT NOT NULL, status TEXT NOT NULL,
                  projection_json TEXT NOT NULL, diagnostics_json TEXT NOT NULL,
                  PRIMARY KEY(acceptance_id,generation,case_order));
                CREATE TABLE IF NOT EXISTS events (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  acceptance_id TEXT NOT NULL REFERENCES attempts(acceptance_id),
                  generation INTEGER NOT NULL, at TEXT NOT NULL,
                  kind TEXT NOT NULL, facts_json TEXT NOT NULL);
                PRAGMA application_id=1128350000;
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=10)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        except sqlite3.Error as exc:
            raise AcceptorError("STORE_INTEGRITY_FAILED") from exc
        finally:
            if db is not None:
                db.close()

    def blob_path(self, kind, digest):
        if kind not in {"candidates", "profiles", "documents"} or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise AcceptorError("STORE_INTEGRITY_FAILED")
        return self.root / kind / digest

    def read_blob(self, kind, digest, size=None):
        p = self.blob_path(kind, digest)
        ceiling = 64 * 1024 * 1024 if kind == "candidates" else 32 * 1024 * 1024
        try:
            if p.is_symlink() or not p.is_file() or p.stat().st_size > ceiling:
                raise AcceptorError("STORE_INTEGRITY_FAILED")
            with p.open("rb") as stream:
                data = stream.read(ceiling + 1)
            if len(data) > ceiling or sha(data) != digest or (size is not None and len(data) != size):
                raise AcceptorError("STORE_INTEGRITY_FAILED")
            return data
        except OSError as exc:
            raise AcceptorError("STORE_INTEGRITY_FAILED") from exc

    def put_blob(self, kind, payload):
        digest = sha(payload)
        target = self.blob_path(kind, digest)
        if target.exists() or target.is_symlink():
            self.read_blob(kind, digest, len(payload))
            return digest
        temp = target.parent / ("tmp-" + uuid.uuid4().hex)
        try:
            with temp.open("xb") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(temp, target)
            except FileExistsError:
                self.read_blob(kind, digest, len(payload))
            self._sync_directory(target.parent)
        except OSError as exc:
            raise AcceptorError("STORE_WRITE_FAILED") from exc
        finally:
            temp.unlink(missing_ok=True)
        return digest

    @staticmethod
    def _sync_directory(path):
        if os.name != "nt":
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    def ingest(self, candidate, profile, candidate_bytes, profile_bytes):
        cd = self.put_blob("candidates", candidate_bytes)
        pd = self.put_blob("profiles", profile_bytes)
        with self.connect() as db:
            for table, digest, identity, app, data in (
                ("candidates", cd, candidate.manifest["release_candidate_id"], candidate.manifest["application"]["id"], candidate_bytes),
                ("profiles", pd, profile.document["profile_id"], profile.document["application_id"], profile_bytes),
            ):
                row = db.execute(f"SELECT * FROM {table} WHERE sha256=?", (digest,)).fetchone()
                identity_column = "candidate_id" if table == "candidates" else "profile_id"
                expected = (identity, app, table + "/" + digest, len(data))
                if row and tuple(row[k] for k in (identity_column, "application_id", "stored_path", "size_bytes")) != expected:
                    raise AcceptorError("STORE_INTEGRITY_FAILED")
                db.execute(f"INSERT OR IGNORE INTO {table} VALUES (?,?,?,?,?,?)", (digest, *expected, now()))

    def row(self, aid):
        validate_id(aid)
        with self.connect() as db:
            row = db.execute("SELECT * FROM attempts WHERE acceptance_id=?", (aid,)).fetchone()
            return dict(row) if row else None

    def event(self, db, aid, generation, kind, facts):
        db.execute("INSERT INTO events(acceptance_id,generation,at,kind,facts_json) VALUES(?,?,?,?,?)",
                   (aid, generation, now(), kind, canonical_bytes(facts).decode()))

    def allocate(self, aid, identity):
        validate_id(aid)
        old = self.row(aid)
        generation = old["generation"] + 1 if old else 1
        with self.connect() as db:
            if old:
                db.execute("UPDATE attempts SET generation=?,status='PREPARING',classification=NULL,started_at=?,terminal_at=NULL,document_sha256=NULL,document_path=NULL,error_code=NULL,error_detail=NULL,work_name=NULL WHERE acceptance_id=?", (generation, now(), aid))
            else:
                db.execute("INSERT INTO attempts(acceptance_id,candidate_sha256,profile_sha256,identity_json,generation,status,started_at) VALUES(?,?,?,?,?,'PREPARING',?)",
                           (aid, identity["candidate_bundle_sha256"], identity["profile_bundle_sha256"], canonical_bytes(identity).decode(), generation, now()))
                self.event(db, aid, generation, "candidate_ingested", {"sha256": identity["candidate_bundle_sha256"]})
                self.event(db, aid, generation, "profile_ingested", {"sha256": identity["profile_bundle_sha256"]})
                self.event(db, aid, generation, "identity_allocated", {"acceptance_id": aid})
            self.event(db, aid, generation, "attempt_preparing", {})
        return generation

    def create_work(self, aid, generation):
        nonce = uuid.uuid4().hex
        name = aid + "-" + nonce
        path = self.root / "work" / name
        # Record before creating anything so interrupted preparation is recoverable.
        with self.connect() as db:
            db.execute("UPDATE attempts SET work_name=? WHERE acceptance_id=? AND generation=?", (name, aid, generation))
        path.mkdir()
        marker = {"schema": "capy.acceptor-work/v0", "acceptance_id": aid, "nonce": nonce, "directory": name}
        with (path / "owner.json").open("xb") as f:
            f.write(canonical_bytes(marker)); f.flush(); os.fsync(f.fileno())
        (path / "run").mkdir()
        with self.connect() as db:
            db.execute("UPDATE attempts SET status='RUNNING' WHERE acceptance_id=? AND generation=?", (aid, generation))
            self.event(db, aid, generation, "toolchain_validated", {})
        return path / "run"

    def cleanup(self, row):
        name = row["work_name"]
        if name is None:
            return
        match = _WORK.fullmatch(name)
        if not match or match[1] != row["acceptance_id"]:
            raise AcceptorError("CLEANUP_FAILED")
        root = self.root / "work"
        path = root / name
        if not path.exists() and not path.is_symlink():
            return
        try:
            if root.is_symlink() or path.is_symlink() or path.parent.resolve() != root.resolve():
                raise AcceptorError("CLEANUP_FAILED")
            marker_path = path / "owner.json"
            if marker_path.is_symlink() or marker_path.stat().st_size > 1024:
                raise AcceptorError("CLEANUP_FAILED")
            marker = parse_strict_json(marker_path.read_bytes())
            if marker != {"schema": "capy.acceptor-work/v0", "acceptance_id": row["acceptance_id"], "nonce": match[2], "directory": name}:
                raise AcceptorError("CLEANUP_FAILED")
            shutil.rmtree(path)
            if path.exists():
                raise AcceptorError("CLEANUP_FAILED")
        except (OSError, ValueError) as exc:
            raise AcceptorError("CLEANUP_FAILED") from exc

    def fail(self, aid, generation, code, status="FAILED"):
        with self.connect() as db:
            db.execute("UPDATE attempts SET status=?,classification=?,error_code=?,error_detail='',terminal_at=?,document_sha256=NULL,document_path=NULL WHERE acceptance_id=? AND generation=?", (status, code, code, now(), aid, generation))
            self.event(db, aid, generation, "attempt_terminal", {"status": status, "code": code})

    def record_case(self, aid, generation, kind, facts):
        with self.connect() as db:
            if kind == "case_terminal":
                projection, diagnostics = facts["projection"], facts["diagnostics"]
                db.execute("INSERT INTO case_results VALUES (?,?,?,?,?,?,?)", (aid, generation, diagnostics["order"], projection["case_id"], "MATCHED" if projection["matched"] else "REJECTED", canonical_bytes(projection).decode(), canonical_bytes(diagnostics).decode()))
            self.event(db, aid, generation, kind, facts)

    def finish(self, aid, generation, evaluation):
        payload = canonical_bytes(evaluation.document)
        digest = self.put_blob("documents", payload)
        with self.connect() as db:
            self.event(db, aid, generation, "cleanup_terminal", {"status": "CONFIRMED"})
            db.execute("UPDATE attempts SET status=?,classification=?,terminal_at=?,document_sha256=?,document_path=? WHERE acceptance_id=? AND generation=?", (evaluation.status, evaluation.classification, now(), digest, "documents/" + digest, aid, generation))
            self.event(db, aid, generation, "receipt_committed" if evaluation.status == "ACCEPTED" else "rejection_report_committed", {"sha256": digest})
        return payload

    def terminal_bytes(self, row, identity):
        if row["identity_json"].encode() != canonical_bytes(identity):
            raise AcceptorError("STORE_INTEGRITY_FAILED")
        if row["document_path"] != "documents/" + str(row["document_sha256"]):
            raise AcceptorError("STORE_INTEGRITY_FAILED")
        payload = self.read_blob("documents", row["document_sha256"])
        try:
            doc = parse_strict_json(payload)
            if canonical_bytes(doc) != payload or canonical_bytes(doc["identity"]) != canonical_bytes(identity) or doc["acceptance_id"] != row["acceptance_id"] or doc["status"] != row["status"] or doc["classification"] != row["classification"] or doc["cleanup"] != {"status": "CONFIRMED"}:
                raise AcceptorError("STORE_INTEGRITY_FAILED")
        except (ValueError, KeyError, TypeError) as exc:
            raise AcceptorError("STORE_INTEGRITY_FAILED") from exc
        return payload

    def journal(self, aid):
        with self.connect() as db:
            events = [dict(r) for r in db.execute("SELECT generation,at,kind,facts_json FROM events WHERE acceptance_id=? ORDER BY sequence", (aid,))]
            cases = [dict(r) for r in db.execute("SELECT generation,case_order,case_id,status,projection_json,diagnostics_json FROM case_results WHERE acceptance_id=? ORDER BY generation,case_order", (aid,))]
        for r in events:
            r["facts"] = json.loads(r.pop("facts_json"))
        for r in cases:
            r["projection"] = json.loads(r.pop("projection_json"))
            r["diagnostics"] = json.loads(r.pop("diagnostics_json"))
        return events, cases
