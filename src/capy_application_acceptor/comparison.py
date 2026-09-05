"""Exact semantic and artifact comparison with causal precedence."""
from __future__ import annotations

import hashlib
import json
import re

from . import codec

_FAILURE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
_DETAIL_MAX = 512


def canonical_result_sha(result) -> str | None:
    if result is None:
        return None
    try:
        return hashlib.sha256(codec.canonical_bytes(result)).hexdigest()
    except (TypeError, ValueError):
        return None


def project_artifacts(artifact_files: list[tuple[str, bytes]]) -> list[dict]:
    out = []
    for filename, data in sorted(artifact_files, key=lambda x: x[0]):
        out.append({"filename": filename, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
    return out


def expected_projection(expect: dict) -> dict:
    arts = []
    for a in expect.get("artifacts", []):
        # Expected artifacts in profile have member+sha; projection uses filename/sha/size.
        # Size comes from actual expected bytes; caller must supply size. Here we
        # only have sha; size filled by projection layer. This helper builds the
        # shape without size; projection.py fills sizes from profile members.
        arts.append({"filename": a["filename"], "sha256": a["sha256"], "size_bytes": a.get("size_bytes", 0)})
    arts.sort(key=lambda x: x["filename"])
    return {
        "status": expect["status"],
        "result_sha256": canonical_result_sha(expect.get("result")),
        "artifacts": arts,
        "failure_code": expect.get("failure_code"),
    }


def parse_success_envelope(stdout: bytes) -> tuple[dict | None, str | None]:
    """Parse DevKit success envelope. Returns (result_without_artifacts, error)."""
    if not stdout:
        return None, "empty"
    if not stdout.endswith(b"\n"):
        return None, "no-newline"
    # Exactly one JSON result envelope: single line.
    lines = stdout.split(b"\n")
    # stdout ends with \n -> last element b"".
    if len(lines) != 2 or lines[1] != b"":
        return None, "multiple"
    line = lines[0]
    if not line:
        return None, "empty-line"
    try:
        line.decode("utf-8")
    except UnicodeDecodeError:
        return None, "unicode"
    # Strict JSON: reject duplicate keys, nonfinite values, bad Unicode,
    # excessive depth and other malformed JSON before semantic comparison.
    try:
        envelope = codec.parse_strict_json(line)
    except ValueError:
        return None, "json"
    if not isinstance(envelope, dict) or "artifacts" not in envelope:
        return None, "envelope"
    artifacts = envelope.get("artifacts")
    if not isinstance(artifacts, list) or any(not isinstance(x, str) for x in artifacts):
        return None, "artifacts-type"
    if len(set(artifacts)) != len(artifacts):
        return None, "artifacts-dup"
    result = dict(envelope)
    result.pop("artifacts")
    return (result, None)


def parse_failure_stderr(stderr: bytes) -> tuple[str | None, str | None]:
    """Parse stable failure stderr. Returns (code, error)."""
    if not stderr:
        return None, "empty"
    # Exactly one stderr line.
    if not stderr.endswith(b"\n"):
        return None, "no-newline"
    lines = stderr.split(b"\n")
    if len(lines) != 2 or lines[1] != b"":
        return None, "multiple"
    try:
        text = lines[0].decode("utf-8")
    except UnicodeDecodeError:
        return None, "unicode"
    if not text.strip():
        return None, "empty-line"
    # Code optionally followed by colon-space and bounded safe detail.
    if ": " in text:
        code, detail = text.split(": ", 1)
        if not detail.strip() or len(detail) > _DETAIL_MAX or "\x00" in detail or "\n" in detail:
            return None, "detail"
    else:
        # Also allow bare code with no detail, but reject trailing colon variants.
        code = text
        if code.endswith(":") or code.endswith(" "):
            return None, "format"
    if _FAILURE_RE.fullmatch(code) is None or len(code) > 96:
        return None, "code"
    return code, None


def classify_case(
    *,
    expect: dict,
    timed_out: bool,
    output_limited: bool,
    secret_hit: bool,
    exit_code: int | None,
    stdout: bytes,
    stderr: bytes,
    actual_artifacts: list[tuple[str, bytes]],
    envelope_error: str | None,
    observed_result,
    observed_failure_code: str | None,
    observed_status: str,
    artifact_anomaly: str | None = None,
) -> str:
    """Return classification in causal precedence."""
    if secret_hit:
        return "REJECTED_SECRET_BOUNDARY"
    if timed_out:
        return "REJECTED_CASE_TIMEOUT"
    if output_limited:
        return "REJECTED_OUTPUT_LIMIT"
    # Application exit errors: unhandled exceptions, non-JSON/multiple outputs,
    # inconsistent status/exit, other exit codes.
    if envelope_error is not None:
        return "REJECTED_APPLICATION_EXIT"
    if observed_status == "error":
        return "REJECTED_APPLICATION_EXIT"
    # Every extra/undeclared output, dotfile, unsafe name, directory, or
    # symlink must be rejected for successful and failed cases, without
    # exposing unsafe names in portable evidence (already filtered).
    if artifact_anomaly is not None:
        return "REJECTED_ARTIFACT_SET_MISMATCH"
    # Now observed is ok or failed with valid envelope.
    if expect["status"] == "ok" and observed_status == "failed":
        return "REJECTED_RESULT_MISMATCH"
    if expect["status"] == "failed" and observed_status == "ok":
        return "REJECTED_RESULT_MISMATCH"
    if expect["status"] == "failed" and observed_status == "failed":
        if expect.get("failure_code") != observed_failure_code:
            return "REJECTED_FAILURE_CODE_MISMATCH"
        # Failed cases expect no artifacts; any produced file is an extra.
        if actual_artifacts:
            return "REJECTED_ARTIFACT_SET_MISMATCH"
        return "CASE_MATCHED"
    # Both ok: compare result exact JSON values/types.
    if not _json_equal(expect.get("result"), observed_result):
        return "REJECTED_RESULT_MISMATCH"
    # Compare artifact sets then bytes.
    exp_names = sorted(a["filename"] for a in expect.get("artifacts", []))
    obs_names = sorted(n for n, _ in actual_artifacts)
    if exp_names != obs_names:
        return "REJECTED_ARTIFACT_SET_MISMATCH"
    # Bytes: compare each file's sha against expected sha.
    exp_map = {a["filename"]: a["sha256"] for a in expect.get("artifacts", [])}
    for filename, data in actual_artifacts:
        if hashlib.sha256(data).hexdigest() != exp_map.get(filename):
            return "REJECTED_ARTIFACT_BYTES_MISMATCH"
    return "CASE_MATCHED"


def _json_equal(a, b) -> bool:
    # Exact JSON values/types: true vs 1 vs 1.0 distinct. Python json loads
    # true->True, 1->int, 1.0->float, but our observed/expected are already
    # parsed Python values from canonical JSON. Need to distinguish bool/int/float.
    # Use canonical bytes comparison: canonical(a) == canonical(b).
    try:
        return codec.canonical_bytes(a) == codec.canonical_bytes(b)
    except (TypeError, ValueError):
        return False
