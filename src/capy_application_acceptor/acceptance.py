"""Independent execution and portable evidence; frozen entrypoint."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from . import codec
from .comparison import canonical_result_sha, classify_case
from .constants import EXECUTION_CONTRACT, INTERACTION_CONTRACT
from .errors import AcceptorError
from .execution import run_one_case
from .models import Candidate, Evaluation, Profile
from .projection import (
    acceptance_id_for,
    build_case_projection,
    build_document,
    build_expected_entry,
    build_identity,
    build_observed_entry,
    identity_sha,
)
from .scan import scan_many
from .backend import require_backend


def _release_invalid() -> AcceptorError:
    return AcceptorError("RELEASE_INVALID", "release")


def evaluate(candidate: Candidate, profile: Profile, release: dict, work_root: Path, *, on_event=None) -> Evaluation:
    # Validate work_root is an existing empty directory.
    try:
        if not isinstance(work_root, Path):
            work_root = Path(work_root)
        if not work_root.is_dir():
            raise AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment")
        # Caller owns work_root itself; we may create only children.
        if any(work_root.iterdir()):
            raise AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment")
    except AcceptorError:
        raise
    except Exception:
        raise AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment")

    # All execution must leave root empty on every return; cleanup failure
    # raises CLEANUP_FAILED and never returns ACCEPTED.
    try:
        return _evaluate_inner(candidate, profile, release, work_root, on_event=on_event)
    finally:
        # Ensure cleanup on every return path (including raises? Spec says on
        # every return; we also clean on raises to avoid leaking, but preserve
        # original error unless cleanup itself fails).
        _cleanup_children(work_root)


def _evaluate_inner(candidate: Candidate, profile: Profile, release: dict, work_root: Path, *, on_event=None) -> Evaluation:
    # Wrap entire trial to guarantee cleanup.
    created: list[Path] = []
    try:
        result = _trial(candidate, profile, release, work_root, created, on_event=on_event)
        _cleanup_children(work_root)
        return result
    except AcceptorError as e:
        # Attempt cleanup; if cleanup fails, mask with CLEANUP_FAILED?
        # Spec: cleanup failure raises CLEANUP_FAILED and must never return ACCEPTED.
        # For raises, we still must leave root empty; if we cannot, raise CLEANUP_FAILED.
        try:
            _cleanup_children(work_root)
        except AcceptorError as ce:
            raise ce
        raise
    except Exception as e:
        try:
            _cleanup_children(work_root)
        except AcceptorError as ce:
            raise ce
        # Unexpected internal error -> environment unavailable (no raw data).
        raise AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment") from e


def _cleanup_children(work_root: Path):
    try:
        for child in list(work_root.iterdir()):
            try:
                if child.is_symlink() or child.is_file():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child, ignore_errors=False)
                else:
                    # Unknown type: try unlink.
                    try:
                        child.unlink()
                    except OSError:
                        shutil.rmtree(child, ignore_errors=False)
            except OSError as e:
                raise AcceptorError("CLEANUP_FAILED", "cleanup") from e
        # Verify empty.
        try:
            remaining = list(work_root.iterdir())
        except OSError as e:
            raise AcceptorError("CLEANUP_FAILED", "cleanup") from e
        if remaining:
            raise AcceptorError("CLEANUP_FAILED", "cleanup")
    except AcceptorError:
        raise
    except Exception as e:
        raise AcceptorError("CLEANUP_FAILED", "cleanup") from e


def _validate_release(release) -> dict:
    if not isinstance(release, dict):
        raise _release_invalid()
    if set(release) != {"contract", "version", "implementation_commit", "implementation_tree"}:
        raise _release_invalid()
    if release.get("contract") != "capy.independent-application-acceptance/v0":
        raise _release_invalid()
    if release.get("version") != "0.1.0":
        raise _release_invalid()
    for key in ("implementation_commit", "implementation_tree"):
        v = release.get(key)
        if not isinstance(v, str) or len(v) != 40 or any(c not in "0123456789abcdef" for c in v):
            raise _release_invalid()
    return dict(release)


def _trial(candidate, profile, release, work_root: Path, created: list, *, on_event=None) -> Evaluation:
    release_clean = _validate_release(release)
    # Basic type checks for candidate/profile (must be validated models).
    if not isinstance(candidate, Candidate) or not isinstance(profile, Profile):
        raise AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment")
    # Application mismatch.
    try:
        cand_app = candidate.manifest["application"]["id"]
        prof_app = profile.document["application_id"]
    except (KeyError, TypeError):
        raise AcceptorError("APPLICATION_PROFILE_MISMATCH", "application")
    if cand_app != prof_app:
        raise AcceptorError("APPLICATION_PROFILE_MISMATCH", "application")
    # Also check descriptor/interaction app ids consistent (integrity).
    try:
        if candidate.descriptor.get("id") != cand_app:
            raise AcceptorError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate")
        if candidate.interaction.get("application_id") != cand_app:
            raise AcceptorError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate")
    except AttributeError:
        raise AcceptorError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate")
    # Unsupported descriptor state/connections/side-effect/contracts.
    desc = candidate.descriptor
    try:
        if desc.get("state_required") is True:
            raise AcceptorError("APPLICATION_UNSUPPORTED", "application")
        if desc.get("connections"):
            raise AcceptorError("APPLICATION_UNSUPPORTED", "application")
        if desc.get("side_effect") not in ("read_only", "artifact_generation"):
            raise AcceptorError("APPLICATION_UNSUPPORTED", "application")
        if candidate.manifest["application"]["contract"] != EXECUTION_CONTRACT:
            raise AcceptorError("APPLICATION_UNSUPPORTED", "application")
        if candidate.manifest["application"]["interaction"]["schema"] != INTERACTION_CONTRACT:
            raise AcceptorError("APPLICATION_UNSUPPORTED", "application")
    except KeyError:
        raise AcceptorError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate")
    # Toolchain trust cross-check.
    try:
        req = profile.document["candidate_requirements"]
        tc = candidate.manifest["toolchain"]
        if (req["toolchain_release_binding_commit"] != tc["release_binding_commit"]
                or req["toolchain_wheel_sha256"] != tc["wheel_sha256"]
                or req["toolchain_authoring_bundle_sha256"] != tc["authoring_bundle"]["sha256"]):
            raise AcceptorError("TOOLCHAIN_UNTRUSTED", "toolchain")
        # Also ensure candidate toolchain is still trusted (defense).
        from .constants import (
            TRUSTED_BUNDLE_SHA256,
            TRUSTED_RELEASE_BINDING_COMMIT,
            TRUSTED_WHEEL_SHA256,
        )

        if (tc["release_binding_commit"] != TRUSTED_RELEASE_BINDING_COMMIT
                or tc["wheel_sha256"] != TRUSTED_WHEEL_SHA256
                or tc["authoring_bundle"]["sha256"] != TRUSTED_BUNDLE_SHA256):
            raise AcceptorError("TOOLCHAIN_UNTRUSTED", "toolchain")
    except KeyError:
        raise AcceptorError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate")
    # Identity for portable docs.
    identity = build_identity(candidate, profile, release_clean)
    isha = identity_sha(identity)
    aid = acceptance_id_for(isha)

    # Pre-execution secret scan of all candidate application members.
    try:
        blobs = list(candidate.application_members.values())
    except Exception:
        raise AcceptorError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate")
    if scan_many(blobs):
        return _early_rejection(candidate, profile, release_clean, "REJECTED_SECRET_BOUNDARY", secret_hit=True)

    # Source scanning precedes every semantic rejection and any PASSED scan fact.
    if req.get("side_effect") != desc.get("side_effect"):
        return _early_rejection(candidate, profile, release_clean, "REJECTED_INTERACTION_MISMATCH", secret_hit=False)

    # Interaction expectations cross-check (semantic, no LM judgment).
    if not _interaction_matches(profile.document["interaction_expectations"], candidate.interaction, desc):
        return _early_rejection(candidate, profile, release_clean, "REJECTED_INTERACTION_MISMATCH", secret_hit=False)

    # No wheel setup or candidate process on a host without qualified teardown.
    require_backend()

    # Do not run candidate code before input/toolchain/secret checks pass:
    # validate request sizes and resource bindings fit limits (already validated
    # in profile, but re-check against limits defensively).
    limits = profile.document["limits"]
    for case in profile.document["cases"]:
        try:
            rb = codec.canonical_bytes(case["request"])
        except (TypeError, ValueError):
            raise AcceptorError("ACCEPTANCE_PROFILE_INTEGRITY_FAILED", "profile")
        if len(rb) > limits["max_request_bytes"]:
            raise AcceptorError("ACCEPTANCE_PROFILE_INVALID", "profile")

    # Per-case timeout/limits.
    desc_timeout = desc.get("timeout_seconds", limits["timeout_seconds"])
    try:
        per_case_timeout = float(min(int(limits["timeout_seconds"]), int(desc_timeout)))
    except (TypeError, ValueError):
        raise AcceptorError("ACCEPTANCE_PROFILE_INVALID", "profile")
    if per_case_timeout <= 0:
        raise AcceptorError("ACCEPTANCE_PROFILE_INVALID", "profile")
    max_stdout = int(limits["max_stdout_bytes"])
    max_stderr = int(limits["max_stderr_bytes"])
    max_total = int(limits["max_total_artifact_bytes"])

    # Write wheel once under work_root for pip installs (exact filename required).
    try:
        _wheel_name = candidate.manifest["toolchain"]["wheel_filename"]
    except (KeyError, TypeError):
        raise AcceptorError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate")
    wheel_path = work_root / _wheel_name
    try:
        wheel_path.write_bytes(candidate.wheel_bytes)
        created.append(wheel_path)
    except OSError as e:
        raise AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment") from e

    # Run all bounded cases in profile order.
    case_projections: list[dict] = []
    case_records: list[dict] = []
    overall_secret_rejected = False
    for order, case in enumerate(profile.document["cases"]):
        work_case = work_root / f"case-{order:02d}-{case['case_id']}"
        try:
            work_case.mkdir(parents=False, exist_ok=False)
            created.append(work_case)
        except OSError as e:
            raise AcceptorError("EXECUTION_ENVIRONMENT_UNAVAILABLE", "environment") from e
        if on_event is not None:
            on_event("case_started", {"case_id": case["case_id"], "order": order})
        raw = run_one_case(
            candidate=candidate,
            profile=profile,
            case=case,
            case_order=order,
            work_case=work_case,
            wheel_path=wheel_path,
            per_case_timeout=per_case_timeout,
            max_stdout=max_stdout,
            max_stderr=max_stderr,
            max_total_artifacts=max_total,
        )
        # Secret hit in this case takes precedence.
        if raw.get("secret_hit"):
            overall_secret_rejected = True
        # Build expected/observed entries.
        expected_entry = build_expected_entry(case["expect"], profile.members)
        # Observed artifacts projection (sorted, safe names only already).
        obs_arts = []
        for filename, data in raw.get("artifacts", []):
            # Invalid/unsafe names not projected (already filtered in collect).
            # Still guard.
            if not codec.is_safe_basename(filename):
                continue
            obs_arts.append(
                {"filename": filename, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}
            )
        obs_arts.sort(key=lambda x: x["filename"])
        observed_entry = build_observed_entry(
            status=raw.get("observed_status", "error"),
            result=raw.get("observed_result"),
            artifacts=obs_arts,
            failure_code=raw.get("observed_failure_code"),
        )
        # For error observations, ensure null result/failure per spec.
        if observed_entry["status"] == "error":
            observed_entry["result_sha256"] = None
            observed_entry["failure_code"] = None
        # Classify with precedence. Filesystem anomalies (extra/dotfile/
        # unsafe/dir/symlink) reject for successful and failed cases.
        classification = classify_case(
            expect=case["expect"],
            timed_out=bool(raw.get("timed_out")),
            output_limited=bool(raw.get("output_limited")),
            secret_hit=bool(raw.get("secret_hit")),
            exit_code=raw.get("exit_code"),
            stdout=raw.get("stdout", b""),
            stderr=raw.get("stderr", b""),
            actual_artifacts=raw.get("artifacts", []),
            envelope_error=raw.get("envelope_error"),
            observed_result=raw.get("observed_result"),
            observed_failure_code=raw.get("observed_failure_code"),
            observed_status=raw.get("observed_status", "error"),
            artifact_anomaly=raw.get("artifact_anomaly"),
        )
        matched = classification == "CASE_MATCHED"
        proj = build_case_projection(
            case_id=case["case_id"],
            matched=matched,
            classification=classification,
            expected=expected_entry,
            observed=observed_entry,
        )
        case_projections.append(proj)
        # Case records: local-only diagnostics (no native paths in portable doc).
        # Include bounded digests/counts, duration, tool-free facts.
        stdout_data = raw.get("stdout", b"")
        stderr_data = raw.get("stderr", b"")
        rec = {
            "case_id": case["case_id"],
            "order": order,
            "classification": classification,
            "exit_code": raw.get("exit_code"),
            "timed_out": bool(raw.get("timed_out")),
            "output_limited": bool(raw.get("output_limited")),
            "stdout_sha256": hashlib.sha256(stdout_data).hexdigest(),
            "stdout_bytes": len(stdout_data),
            "stdout_truncated": bool(raw.get("stdout_truncated")),
            "stderr_sha256": hashlib.sha256(stderr_data).hexdigest(),
            "stderr_bytes": len(stderr_data),
            "stderr_truncated": bool(raw.get("stderr_truncated")),
            "duration_ms": int(raw.get("duration_ms", 0)),
            "envelope_error": raw.get("envelope_error"),
            "artifact_anomaly": raw.get("artifact_anomaly"),
            "artifact_count": len(raw.get("artifacts", [])),
        }
        case_records.append(rec)
        if on_event is not None:
            on_event("case_terminal", {"projection": proj, "diagnostics": rec})

    # Overall classification: first rejection in case order, else ACCEPTED.
    first_reject = None
    for proj in case_projections:
        if not proj["matched"]:
            first_reject = proj["classification"]
            break
    if first_reject is not None:
        status = "REJECTED"
        classification = first_reject
    else:
        # Every accepted projection must have all matched, secret PASSED, cleanup CONFIRMED.
        if overall_secret_rejected:
            # Should not happen when all matched (secret would be mismatch),
            # but guard.
            status = "REJECTED"
            classification = "REJECTED_SECRET_BOUNDARY"
        else:
            status = "ACCEPTED"
            classification = "ACCEPTED"
    secret_status = "REJECTED" if overall_secret_rejected else "PASSED"
    # If early secret was per-case, findings is ["SECRET_PATTERN"], else [].
    findings: list[str] = ["SECRET_PATTERN"] if overall_secret_rejected else []
    document = build_document(
        status=status,
        classification=classification,
        identity=identity,
        isha=isha,
        aid=aid,
        candidate=candidate,
        cases=case_projections,
        secret_status=secret_status,
        secret_findings=findings,
    )
    return Evaluation(status=status, classification=classification, document=document, case_records=case_records)


def _early_rejection(candidate, profile, release_clean, classification: str, *, secret_hit: bool) -> Evaluation:
    identity = build_identity(candidate, profile, release_clean)
    isha = identity_sha(identity)
    aid = acceptance_id_for(isha)
    if classification == "REJECTED_SECRET_BOUNDARY":
        secret_status = "REJECTED"
        findings = ["SECRET_PATTERN"]
    else:
        secret_status = "PASSED" if not secret_hit else "REJECTED"
        findings = ["SECRET_PATTERN"] if secret_hit else []
        # For interaction mismatch, secret PASSED.
        if classification == "REJECTED_INTERACTION_MISMATCH":
            secret_status = "PASSED"
            findings = []
    document = build_document(
        status="REJECTED",
        classification=classification,
        identity=identity,
        isha=isha,
        aid=aid,
        candidate=candidate,
        cases=[],
        secret_status=secret_status,
        secret_findings=findings,
    )
    return Evaluation(status="REJECTED", classification=classification, document=document, case_records=[])


def _interaction_matches(expect: dict, interaction_doc: dict, descriptor: dict) -> bool:
    try:
        # operation_id exact.
        if expect.get("operation_id") != interaction_doc["operation"]["operation_id"]:
            return False
        # purpose null (unspecified) or exact.
        if expect.get("purpose") is not None and expect.get("purpose") != interaction_doc.get("purpose"):
            return False
        # not_for subset.
        cand_not_for = interaction_doc.get("not_for", [])
        for item in expect.get("not_for", []):
            if item not in cand_not_for:
                return False
        # request_fields ordered exact (field_id, required).
        cand_req = [(f["field_id"], f["required"]) for f in interaction_doc["operation"].get("request_fields", [])]
        exp_req = [(f["field_id"], f["required"]) for f in expect.get("request_fields", [])]
        if cand_req != exp_req:
            return False
        # resource_fields ordered exact (slot, required, min, max).
        cand_res = [
            (f["slot"], f["required"], f["minimum_count"], f["maximum_count"])
            for f in interaction_doc["operation"].get("resource_fields", [])
        ]
        exp_res = [
            (f["slot"], f["required"], f["min_items"], f["max_items"])
            for f in expect.get("resource_fields", [])
        ]
        if cand_res != exp_res:
            return False
        # result_fact_paths ordered exact.
        cand_facts = [f["path"] for f in interaction_doc["operation"]["result"].get("facts", [])]
        if cand_facts != list(expect.get("result_fact_paths", [])):
            return False
        # artifact_filenames ordered exact.
        cand_arts = [a["filename"] for a in interaction_doc["operation"]["result"].get("artifacts", [])]
        if cand_arts != list(expect.get("artifact_filenames", [])):
            return False
        # boundaries subset with exact nearest lists.
        cand_map = {b["boundary_id"]: list(b["nearest_operation_ids"]) for b in interaction_doc.get("boundaries", [])}
        for b in expect.get("boundaries", []):
            bid = b["boundary_id"]
            if bid not in cand_map:
                return False
            if cand_map[bid] != list(b["nearest_operation_ids"]):
                return False
        return True
    except (KeyError, TypeError, AttributeError):
        return False
