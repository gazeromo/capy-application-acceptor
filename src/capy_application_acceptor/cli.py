"""Local model-free JSON CLI; portable output is byte-identical on replay."""
import argparse
import json
import signal
import sys
from pathlib import Path

from .codec import canonical_bytes
from .config import data_root
from .errors import AcceptorError
from .profile import read_profile
from .release_identity import get
from .service import Service
from .store import SCHEMA_VERSION
from .backend import capability


def read_input(path, maximum, code):
    try:
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise AcceptorError(code)
        return data
    except OSError as exc:
        raise AcceptorError("INPUT_UNAVAILABLE") from exc


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="capy-acceptor")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor"); doctor.add_argument("--json", action="store_true")
    profile = sub.add_parser("profile").add_subparsers(dest="action", required=True).add_parser("inspect")
    profile.add_argument("--profile", type=Path, required=True); profile.add_argument("--json", action="store_true")
    accept = sub.add_parser("accept")
    accept.add_argument("--candidate", type=Path, required=True); accept.add_argument("--profile", type=Path, required=True); accept.add_argument("--json", action="store_true")
    inspect = sub.add_parser("acceptance").add_subparsers(dest="action", required=True).add_parser("inspect")
    inspect.add_argument("--acceptance-id", required=True); inspect.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.command == "profile":
            profile = read_profile(read_input(args.profile, 32 * 1024 * 1024, "ACCEPTANCE_PROFILE_INVALID"))
            payload = canonical_bytes({"schema": "capy.acceptance-profile-inspection/v0", "bundle_sha256": profile.bundle_sha256, "profile": profile.document})
        else:
            service = Service(data_root(), get())
            if args.command == "doctor":
                payload = canonical_bytes({"schema": "capy.acceptor-doctor/v0", "ok": True, "version": "0.1.0", "database_schema": SCHEMA_VERSION,
                    "release": service.release, "data_root": str(service.store.root), "model_calls": 0, "execution": capability(),
                    "supported_side_effects": ["read_only", "artifact_generation"], "state_required": False, "connections": []})
            elif args.command == "acceptance":
                payload = canonical_bytes(service.inspect(args.acceptance_id))
            else:
                payload = service.accept(read_input(args.candidate, 64 * 1024 * 1024, "RELEASE_CANDIDATE_INTEGRITY_FAILED"), read_input(args.profile, 32 * 1024 * 1024, "ACCEPTANCE_PROFILE_INVALID"))
        sys.stdout.buffer.write(payload + b"\n")
        return 1 if args.command == "accept" and json.loads(payload).get("status") == "REJECTED" else 0
    except AcceptorError as exc:
        sys.stdout.buffer.write(canonical_bytes({"schema": "capy.acceptor-error/v0", "status": "ERROR", "code": exc.code}) + b"\n")
        return 2
    except (OSError, ValueError, KeyboardInterrupt):
        sys.stdout.buffer.write(canonical_bytes({"schema": "capy.acceptor-error/v0", "status": "ERROR", "code": "INTERNAL_ERROR"}) + b"\n")
        return 2
    finally:
        signal.signal(signal.SIGTERM, previous)
