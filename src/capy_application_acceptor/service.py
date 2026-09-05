"""Durable local acceptance, exact replay and abandoned-attempt recovery."""
import json
from pathlib import Path

from .acceptance import evaluate
from .candidate import read_candidate
from .codec import canonical_bytes
from .errors import AcceptorError
from .locks import IdentityLock
from .profile import read_profile
from .process import IDENTITY_LEASE
from .projection import acceptance_id_for, build_identity, identity_sha
from .release_identity import validate as validate_release
from .store import Store, validate_id


class Service:
    def __init__(self, root: Path, release: dict):
        self.release = validate_release(release)
        self.store = Store(root)

    def _recover(self, row):
        if row and row["status"] in {"PREPARING", "RUNNING"}:
            try:
                self.store.cleanup(row)
            except AcceptorError:
                self.store.fail(row["acceptance_id"], row["generation"], "CLEANUP_FAILED")
                raise
            with self.store.connect() as db:
                self.store.event(db, row["acceptance_id"], row["generation"], "cleanup_terminal", {"status": "CONFIRMED"})
            self.store.fail(row["acceptance_id"], row["generation"], "INTERRUPTED", "INTERRUPTED")

    def accept(self, candidate_bytes: bytes, profile_bytes: bytes):
        candidate = read_candidate(candidate_bytes)
        profile = read_profile(profile_bytes)
        if candidate.manifest["application"]["id"] != profile.document["application_id"]:
            raise AcceptorError("APPLICATION_PROFILE_MISMATCH")
        identity = build_identity(candidate, profile, self.release)
        aid = acceptance_id_for(identity_sha(identity))
        with IdentityLock(self.store.root / "locks" / (aid + ".lock")) as lock:
            if not lock.acquire():
                raise AcceptorError("ACCEPTANCE_IN_PROGRESS")
            self.store.ingest(candidate, profile, candidate_bytes, profile_bytes)
            row = self.store.row(aid)
            if row and row["identity_json"].encode() != canonical_bytes(identity):
                raise AcceptorError("STORE_INTEGRITY_FAILED")
            if row and row["status"] in {"ACCEPTED", "REJECTED"}:
                return self.store.terminal_bytes(row, identity)
            self._recover(row)
            # Failed cleanup remains a repairable tool error; never forget its root.
            row = self.store.row(aid)
            if row and row["work_name"]:
                self.store.cleanup(row)
            generation = self.store.allocate(aid, identity)
            try:
                root = self.store.create_work(aid, generation)
                def event(kind, facts):
                    self.store.record_case(aid, generation, kind, facts)
                lease = IDENTITY_LEASE.set(lock.file.fileno())
                try:
                    result = evaluate(candidate, profile, self.release, root, on_event=event)
                finally:
                    IDENTITY_LEASE.reset(lease)
                if any(root.iterdir()):
                    raise AcceptorError("CLEANUP_FAILED")
                self.store.cleanup(self.store.row(aid))
                return self.store.finish(aid, generation, result)
            except BaseException as exc:
                interrupted = isinstance(exc, (KeyboardInterrupt, SystemExit))
                code = "INTERRUPTED" if interrupted else exc.code if isinstance(exc, AcceptorError) else "INTERNAL_ERROR"
                try:
                    self.store.cleanup(self.store.row(aid))
                except AcceptorError:
                    code = "CLEANUP_FAILED"
                    interrupted = False
                self.store.fail(aid, generation, code, "INTERRUPTED" if interrupted else "FAILED")
                raise AcceptorError(code) from exc

    def inspect(self, aid):
        validate_id(aid)
        with IdentityLock(self.store.root / "locks" / (aid + ".lock")) as lock:
            owned = lock.acquire()
            row = self.store.row(aid)
            if row is None:
                raise AcceptorError("ACCEPTANCE_NOT_FOUND")
            if owned:
                self._recover(row)
                row = self.store.row(aid)
            try:
                identity = json.loads(row["identity_json"])
                if acceptance_id_for(identity_sha(identity)) != aid:
                    raise AcceptorError("STORE_INTEGRITY_FAILED")
                candidate = read_candidate(self.store.read_blob("candidates", row["candidate_sha256"]))
                profile = read_profile(self.store.read_blob("profiles", row["profile_sha256"]))
                expected = build_identity(candidate, profile, validate_release(identity["acceptor"]))
                if canonical_bytes(expected) != canonical_bytes(identity):
                    raise AcceptorError("STORE_INTEGRITY_FAILED")
                document = json.loads(self.store.terminal_bytes(row, identity)) if row["status"] in {"ACCEPTED", "REJECTED"} else None
            except (ValueError, KeyError, TypeError) as exc:
                raise AcceptorError("STORE_INTEGRITY_FAILED") from exc
            events, cases = self.store.journal(aid)
            return {"schema": "capy.acceptance-inspection/v0", "acceptance_id": aid, "status": row["status"],
                    "live": not owned, "classification": row["classification"], "generation": row["generation"],
                    "started_at": row["started_at"], "terminal_at": row["terminal_at"],
                    "error_code": row["error_code"], "document_sha256": row["document_sha256"],
                    "document": document, "events": events, "cases": cases}
