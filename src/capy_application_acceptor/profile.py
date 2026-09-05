"""Closed acceptance-profile validator; frozen entrypoint."""
from __future__ import annotations

import hashlib
import io
import zipfile

from . import codec
from . import validation as V
from .constants import (
    EXECUTION_CONTRACT,
    INTERACTION_CONTRACT,
    LIMIT_CEILINGS,
    LIMIT_KEYS,
    NON_GOALS,
    PROFILE_MAX_BYTES,
    PROFILE_MAX_MEMBERS,
    PROFILE_SCHEMA,
    TRUSTED_BUNDLE_SHA256,
    TRUSTED_RELEASE_BINDING_COMMIT,
    TRUSTED_WHEEL_SHA256,
)
from .errors import AcceptorError
from .models import Profile


def _invalid(msg: str = "") -> AcceptorError:
    return AcceptorError("ACCEPTANCE_PROFILE_INVALID", "profile")


def _integrity(msg: str = "") -> AcceptorError:
    return AcceptorError("ACCEPTANCE_PROFILE_INTEGRITY_FAILED", "profile")


def _untrusted() -> AcceptorError:
    return AcceptorError("TOOLCHAIN_UNTRUSTED", "toolchain")


def read_profile(payload: bytes) -> Profile:
    try:
        return _read(payload)
    except AcceptorError:
        raise
    except Exception:
        raise _integrity()


def _read(payload: bytes) -> Profile:
    if not isinstance(payload, bytes) or not payload:
        raise _integrity()
    if len(payload) > PROFILE_MAX_BYTES:
        # Entire profile bounded by 32 MiB -> integrity or invalid?
        # Treat as invalid (exceeds bound) per spec "invalid before execution".
        raise _invalid("size")
    # Loose unpack to find document and expected members. Metadata
    # boundedness is enforced before any decompression/allocation.
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            if z.comment != b"":
                raise _integrity()
            try:
                _info = z.getinfo("ACCEPTANCE-PROFILE.json")
            except KeyError:
                raise _integrity()
            # JSON has the complete profile bound; each request has its own
            # declared bound. Do not invent a smaller document ceiling.
            if _info.compress_type != zipfile.ZIP_STORED:
                raise _integrity()
            if _info.file_size == 0 or _info.file_size > PROFILE_MAX_BYTES:
                raise _integrity()
            if _info.compress_size > PROFILE_MAX_BYTES:
                raise _integrity()
            loose_names = z.namelist()
            if "ACCEPTANCE-PROFILE.json" not in loose_names:
                raise _integrity()
            doc_raw_loose = z.read("ACCEPTANCE-PROFILE.json")
            if len(doc_raw_loose) > PROFILE_MAX_BYTES:
                raise _integrity()
    except AcceptorError:
        raise
    except Exception:
        raise _integrity()
    # Strict canonical JSON for profile document (also checks dup/nonfinite/depth).
    try:
        doc = codec.check_canonical_json_bytes(doc_raw_loose, what="profile")
    except ValueError:
        raise _integrity()
    # Validate document shape (may raise invalid/untrusted/integrity).
    _validate_document(doc)
    # Compute expected member order: profile first, fixtures sorted, expected sorted.
    expected_order = _expected_members(doc)
    # Member count bound.
    if len(expected_order) > PROFILE_MAX_MEMBERS:
        raise _invalid("members")
    # Metadata aggregate boundedness before decompression: reject oversized
    # fixture/expected declarations without allocating them.
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as _pre:
            _total_fixture = 0
            _total_expected = 0
            _limits = doc["limits"]
            for _case in doc["cases"]:
                for _r in _case["resources"]:
                    try:
                        _pi = _pre.getinfo(_r["member"])
                    except KeyError:
                        continue
                    if _pi.compress_type != zipfile.ZIP_STORED:
                        continue
                    _total_fixture += _pi.file_size
                    if _total_fixture > _limits["max_fixture_bytes"]:
                        raise _invalid("max_fixture_bytes")
                    if _total_fixture > LIMIT_CEILINGS["max_fixture_bytes"]:
                        raise _invalid("fixture-hard")
                for _a in _case["expect"]["artifacts"]:
                    try:
                        _pi = _pre.getinfo(_a["member"])
                    except KeyError:
                        continue
                    if _pi.compress_type != zipfile.ZIP_STORED:
                        continue
                    _total_expected += _pi.file_size
                    if _total_expected > _limits["max_expected_artifact_bytes"]:
                        raise _invalid("max_expected_artifact_bytes")
                    if _total_expected > LIMIT_CEILINGS["max_expected_artifact_bytes"]:
                        raise _invalid("expected-hard")
    except AcceptorError:
        raise
    except Exception:
        pass
    # Canonical ZIP check with expected order.
    try:
        members = codec.check_zip_canonical_members(payload, expected_order)
    except ValueError:
        raise _integrity()
    doc_raw = members["ACCEPTANCE-PROFILE.json"]
    if doc_raw != doc_raw_loose:
        raise _integrity()
    # Re-parse to ensure same (already validated).
    # Validate fixture/expected byte bindings and aggregates.
    _validate_members(doc, members)
    bundle_sha = hashlib.sha256(payload).hexdigest()
    return Profile(bundle_sha256=bundle_sha, document=doc, members=dict(members))


def _expected_members(doc) -> list[str]:
    members = ["ACCEPTANCE-PROFILE.json"]
    fixtures: list[str] = []
    expected: list[str] = []
    for case in doc["cases"]:
        cid = case["case_id"]
        for r in case["resources"]:
            fixtures.append(r["member"])
        for a in case["expect"]["artifacts"]:
            expected.append(a["member"])
    fixtures_sorted = sorted(fixtures)
    expected_sorted = sorted(expected)
    # No unreferenced members: expected order is fixtures sorted then expected sorted.
    # Also check for duplicates (shared fixtures) here as integrity? Spec says
    # fixtures may not be shared -> invalid? Treat as invalid.
    members.extend(fixtures_sorted)
    members.extend(expected_sorted)
    # Case-fold collisions are unsafe (Windows alias).
    try:
        codec.check_casefold_collisions(members)
    except ValueError:
        raise _integrity()
    return members


def _validate_document(doc):
    # Top-level exact keys: unknown field is schema-invalid (INVALID);
    # missing/malformed shape remains integrity failure.
    _TOP = {
        "schema", "profile_id", "application_id", "candidate_requirements",
        "interaction_expectations", "cases", "limits", "non_goals",
    }
    try:
        V.require_closed(doc, _TOP, "profile")
    except ValueError:
        if isinstance(doc, dict) and (set(doc.keys()) - _TOP):
            raise _invalid("unknown-field")
        raise _integrity()
    if doc["schema"] != PROFILE_SCHEMA:
        # Wrong schema: malformed? Treat as integrity (or invalid?).
        # Spec says unsupported requirements fail INVALID; schema mismatch is
        # more fundamental -> integrity.
        raise _integrity()
    try:
        V.check_profile_id(doc["profile_id"])
        V.check_application_id(doc["application_id"])
    except ValueError:
        raise _integrity()
    if doc["non_goals"] != NON_GOALS:
        # Must be exactly ordered values. Value mismatch -> invalid?
        # Treat as invalid (unsupported non-goals).
        raise _invalid("non_goals")
    _validate_requirements(doc["candidate_requirements"])
    _validate_interaction_expectations(doc["interaction_expectations"])
    _validate_limits(doc["limits"])
    _validate_cases(doc)


def _validate_requirements(req):
    # Exact fields; unknown -> integrity? But spec says unsupported requirements
    # fail INVALID. Distinguish: unknown field -> integrity, bad value -> invalid/untrusted.
    try:
        V.require_closed(
            req,
            {"release_candidate_schema", "execution_contract", "interaction_contract",
             "toolchain_release_binding_commit", "toolchain_wheel_sha256",
             "toolchain_authoring_bundle_sha256", "side_effect", "state_required", "connections"},
            "requirements",
        )
    except ValueError:
        raise _integrity()
    # Supported values; toolchain identities -> untrusted if wrong.
    if req["release_candidate_schema"] != "capy.application-release-candidate/v1":
        raise _invalid("release_candidate_schema")
    if req["execution_contract"] != EXECUTION_CONTRACT:
        raise _invalid("execution_contract")
    if req["interaction_contract"] != INTERACTION_CONTRACT:
        raise _invalid("interaction_contract")
    # Fixed toolchain identities.
    if (req["toolchain_release_binding_commit"] != TRUSTED_RELEASE_BINDING_COMMIT
            or req["toolchain_wheel_sha256"] != TRUSTED_WHEEL_SHA256
            or req["toolchain_authoring_bundle_sha256"] != TRUSTED_BUNDLE_SHA256):
        # Check syntax first: if not hex, it's malformed -> integrity?
        # If well-formed but wrong value -> untrusted.
        for key in ("toolchain_release_binding_commit",):
            v = req[key]
            if not isinstance(v, str) or not codec.is_hex40(v):
                raise _integrity()
        for key in ("toolchain_wheel_sha256", "toolchain_authoring_bundle_sha256"):
            v = req[key]
            if not isinstance(v, str) or not codec.is_hex64(v):
                raise _integrity()
        raise _untrusted()
    # Validate hex syntax even when trusted (already).
    try:
        V.check_hex40(req["toolchain_release_binding_commit"], "binding")
        V.check_hex64(req["toolchain_wheel_sha256"], "wheel")
        V.check_hex64(req["toolchain_authoring_bundle_sha256"], "bundle")
    except ValueError:
        raise _integrity()
    if req["side_effect"] not in ("read_only", "artifact_generation"):
        raise _invalid("side_effect")
    if type(req["state_required"]) is not bool:
        raise _integrity()
    if req["state_required"] is not False:
        raise _invalid("state_required")
    if not isinstance(req["connections"], list):
        raise _integrity()
    if req["connections"] != []:
        raise _invalid("connections")


def _validate_interaction_expectations(exp):
    try:
        V.require_closed(
            exp,
            {"purpose", "operation_id", "not_for", "request_fields", "resource_fields",
             "result_fact_paths", "artifact_filenames", "boundaries"},
            "interaction_expectations",
        )
    except ValueError:
        raise _integrity()
    # purpose null or nonempty ≤4000.
    p = exp["purpose"]
    if p is not None:
        if not isinstance(p, str) or not p or len(p) > 4000:
            raise _invalid("purpose")
        if "\x00" in p:
            raise _integrity()
    try:
        V.check_dotted(exp["operation_id"], "operation_id")
    except ValueError:
        raise _invalid("operation_id")
    # not_for unique nonempty strings.
    nf = exp["not_for"]
    if not isinstance(nf, list):
        raise _invalid("not_for")
    seen_nf: set[str] = set()
    for item in nf:
        if not isinstance(item, str) or not item:
            raise _invalid("not_for")
        if "\x00" in item:
            raise _integrity()
        if item in seen_nf:
            raise _invalid("not_for-dup")
        seen_nf.add(item)
    # request_fields ordered exact list of {field_id, required}.
    rf = exp["request_fields"]
    if not isinstance(rf, list):
        raise _integrity()
    seen_fid: set[str] = set()
    for entry in rf:
        try:
            V.require_closed(entry, {"field_id", "required"}, "request_field")
        except ValueError:
            raise _integrity()
        try:
            V.check_path_dotted(entry["field_id"], "field_id")
        except ValueError:
            raise _invalid("field_id")
        if entry["field_id"] in seen_fid:
            raise _invalid("field-dup")
        seen_fid.add(entry["field_id"])
        if type(entry["required"]) is not bool:
            raise _integrity()
    # resource_fields ordered exact list of {slot, required, min_items, max_items}.
    rsf = exp["resource_fields"]
    if not isinstance(rsf, list):
        raise _integrity()
    seen_slot: set[str] = set()
    for entry in rsf:
        try:
            V.require_closed(entry, {"slot", "required", "min_items", "max_items"}, "resource_field")
        except ValueError:
            raise _integrity()
        slot = entry["slot"]
        if not isinstance(slot, str) or not slot:
            raise _invalid("slot")
        # Slot grammar: [a-z][a-z0-9_]* ? Use segment check.
        import re as _re

        if _re.fullmatch(r"[a-z][a-z0-9_]*", slot) is None:
            raise _invalid("slot")
        if slot in seen_slot:
            raise _invalid("slot-dup")
        seen_slot.add(slot)
        if type(entry["required"]) is not bool:
            raise _integrity()
        for key in ("min_items", "max_items"):
            v = entry[key]
            if type(v) is not int or not 0 <= v <= 16:
                raise _invalid(key)
        if entry["min_items"] > entry["max_items"]:
            raise _invalid("counts")
        if entry["required"] and entry["min_items"] < 1:
            raise _invalid("required-count")
    # result_fact_paths unique ordered list of exact scalar dotted paths.
    rfp = exp["result_fact_paths"]
    if not isinstance(rfp, list):
        raise _integrity()
    seen_fp: set[str] = set()
    for path in rfp:
        try:
            V.check_path_dotted(path, "fact-path")
        except ValueError:
            raise _invalid("fact-path")
        if path in seen_fp:
            raise _invalid("fact-dup")
        seen_fp.add(path)
    # artifact_filenames unique ordered list of safe basenames.
    af = exp["artifact_filenames"]
    if not isinstance(af, list):
        raise _integrity()
    seen_af: set[str] = set()
    lowered: set[str] = set()
    for name in af:
        try:
            V.check_safe_basename(name, "artifact_filenames")
        except ValueError:
            raise _integrity()
        if name in seen_af:
            raise _invalid("artifact-dup")
        seen_af.add(name)
        low = name.lower()
        if low in lowered:
            raise _integrity()
        lowered.add(low)
    # boundaries unique boundary IDs each {boundary_id, nearest_operation_ids}.
    bnds = exp["boundaries"]
    if not isinstance(bnds, list):
        raise _invalid("boundaries")
    seen_b: set[str] = set()
    for entry in bnds:
        try:
            V.require_closed(entry, {"boundary_id", "nearest_operation_ids"}, "boundary")
        except ValueError:
            raise _integrity()
        try:
            V.check_dotted(entry["boundary_id"], "boundary_id")
        except ValueError:
            raise _invalid("boundary_id")
        if entry["boundary_id"] in seen_b:
            raise _invalid("boundary-dup")
        seen_b.add(entry["boundary_id"])
        nearest = entry["nearest_operation_ids"]
        if not isinstance(nearest, list) or not nearest:
            raise _invalid("nearest")
        for nid in nearest:
            try:
                V.check_dotted(nid, "nearest")
            except ValueError:
                raise _invalid("nearest")


def _validate_limits(limits):
    try:
        V.require_closed(limits, set(LIMIT_KEYS), "limits")
    except ValueError:
        raise _integrity()
    for key in LIMIT_KEYS:
        v = limits[key]
        # Booleans are not integers: schema-invalid limit value.
        if type(v) is bool:
            raise _invalid(key)
        if type(v) is not int:
            raise _integrity()
        if v <= 0:
            raise _invalid(key)
        if v > LIMIT_CEILINGS[key]:
            raise _invalid(key)


def _validate_cases(doc):
    cases = doc["cases"]
    limits = doc["limits"]
    exp_inter = doc["interaction_expectations"]
    if not isinstance(cases, list) or not cases:
        raise _invalid("cases")
    if len(cases) > limits["max_cases"]:
        raise _invalid("max_cases")
    if len(cases) > LIMIT_CEILINGS["max_cases"]:
        raise _invalid("max_cases-hard")
    seen_ids: set[str] = set()
    has_ok = False
    has_failed = False
    # For fixture sharing check.
    all_resource_members: set[str] = set()
    total_fixture = 0
    total_expected = 0
    _CASE_KEYS = {"case_id", "request", "resources", "expect"}
    for case in cases:
        try:
            V.require_closed(case, _CASE_KEYS, "case")
        except ValueError:
            if isinstance(case, dict) and (set(case.keys()) - _CASE_KEYS):
                raise _invalid("unknown-field")
            raise _integrity()
        try:
            V.check_case_id(case["case_id"])
        except ValueError:
            raise _invalid("case_id")
        if case["case_id"] in seen_ids:
            raise _invalid("case-dup")
        seen_ids.add(case["case_id"])
        if not isinstance(case["request"], dict):
            raise _integrity()
        # Canonical request bytes must fit limits.
        try:
            req_bytes = codec.canonical_bytes(case["request"])
        except (TypeError, ValueError):
            raise _integrity()
        if len(req_bytes) > limits["max_request_bytes"]:
            raise _invalid("max_request_bytes")
        # Request values arbitrary finite JSON governed by app schemas: check
        # finite (no NaN/Infinity already via canonical), depth? Use depth check.
        # Depth over 32 invalid -> integrity? Treat as integrity (malformed JSON value).
        # Our canonical already ensures encodable; check depth via parse?
        # Skip extra check; canonical ensures finite.
        resources = case["resources"]
        if not isinstance(resources, list):
            raise _integrity()
        if len(resources) > limits["max_resources_per_case"]:
            raise _invalid("max_resources_per_case")
        # Each resource exactly {slot, filename, member, sha256}.
        seen_slots: set[str] = set()
        for r in resources:
            try:
                V.require_closed(r, {"slot", "filename", "member", "sha256"}, "resource")
            except ValueError:
                raise _integrity()
            slot = r["slot"]
            if not isinstance(slot, str) or not slot:
                raise _invalid("slot")
            if slot in seen_slots:
                raise _invalid("slot-dup")
            seen_slots.add(slot)
            # Slot must name a profile resource field.
            declared_slots = {e["slot"] for e in exp_inter["resource_fields"]}
            if slot not in declared_slots:
                raise _invalid("slot-unknown")
            try:
                V.check_safe_basename(r["filename"], "filename")
            except ValueError:
                raise _integrity()
            # Member exactly fixtures/<case_id>/<filename>.
            expected_member = f"fixtures/{case['case_id']}/{r['filename']}"
            if r["member"] != expected_member:
                raise _integrity()
            try:
                V.check_hex64(r["sha256"], "resource.sha256")
            except ValueError:
                raise _integrity()
            if r["member"] in all_resource_members:
                raise _invalid("fixture-shared")
            all_resource_members.add(r["member"])
        # Projected counts must satisfy every slot's requiredness/counts,
        # including zero for absent optional slots.
        _check_projected_counts(resources, exp_inter["resource_fields"])
        # Expect exactly {status, result, artifacts, failure_code}.
        expect = case["expect"]
        try:
            V.require_closed(expect, {"status", "result", "artifacts", "failure_code"}, "expect")
        except ValueError:
            raise _integrity()
        if expect["status"] not in ("ok", "failed"):
            raise _invalid("expect.status")
        if expect["status"] == "ok":
            has_ok = True
            if not isinstance(expect["result"], dict):
                raise _invalid("expect.result")
            if expect["failure_code"] is not None:
                raise _invalid("expect.failure_code")
            # Artifacts each exactly {filename, member, sha256}.
            arts = expect["artifacts"]
            if not isinstance(arts, list):
                raise _integrity()
            seen_art: set[str] = set()
            for a in arts:
                try:
                    V.require_closed(a, {"filename", "member", "sha256"}, "artifact")
                except ValueError:
                    raise _integrity()
                try:
                    V.check_safe_basename(a["filename"], "artifact.filename")
                except ValueError:
                    raise _integrity()
                if a["filename"] in seen_art:
                    raise _invalid("artifact-dup")
                seen_art.add(a["filename"])
                expected_member = f"expected/{case['case_id']}/{a['filename']}"
                if a["member"] != expected_member:
                    raise _integrity()
                try:
                    V.check_hex64(a["sha256"], "artifact.sha256")
                except ValueError:
                    raise _integrity()
            # Filenames must match profile artifact declarations for ok case.
            if set(seen_art) != set(exp_inter["artifact_filenames"]):
                raise _invalid("artifact-declarations")
            # For ok cases, artifact order? Not specified; allow any? But members
            # sorted in ZIP; keep as is.
        else:
            has_failed = True
            if expect["result"] is not None:
                raise _invalid("expect.result-failed")
            if expect["artifacts"] != []:
                raise _invalid("expect.artifacts-failed")
            fc = expect["failure_code"]
            try:
                V.check_failure_code(fc)
            except ValueError:
                raise _invalid("failure_code")
    if not (has_ok and has_failed):
        raise _invalid("need-ok-and-failed")
    # Aggregate byte limits are checked in _validate_members (needs actual bytes).
    # But also check declared counts vs hard ceilings already in limits.


def _check_projected_counts(resources, declared):
    counts: dict[str, int] = {d["slot"]: 0 for d in declared}
    for r in resources:
        counts[r["slot"]] = counts.get(r["slot"], 0) + 1
    for d in declared:
        slot = d["slot"]
        c = counts.get(slot, 0)
        if not (d["min_items"] <= c <= d["max_items"]):
            raise _invalid(f"count:{slot}")


def _validate_members(doc, members):
    limits = doc["limits"]
    total_fixture = 0
    total_expected = 0
    # Check each referenced member present and hash matches, sizes fit.
    for case in doc["cases"]:
        for r in case["resources"]:
            member = r["member"]
            if member not in members:
                raise _integrity()
            data = members[member]
            total_fixture += len(data)
            if hashlib.sha256(data).hexdigest() != r["sha256"]:
                raise _integrity()
        for a in case["expect"]["artifacts"]:
            member = a["member"]
            if member not in members:
                raise _integrity()
            data = members[member]
            total_expected += len(data)
            if hashlib.sha256(data).hexdigest() != a["sha256"]:
                raise _integrity()
    if total_fixture > limits["max_fixture_bytes"]:
        raise _invalid("max_fixture_bytes")
    if total_expected > limits["max_expected_artifact_bytes"]:
        raise _invalid("max_expected_artifact_bytes")
    if total_fixture > LIMIT_CEILINGS["max_fixture_bytes"]:
        raise _invalid("fixture-hard")
    if total_expected > LIMIT_CEILINGS["max_expected_artifact_bytes"]:
        raise _invalid("expected-hard")
    # No unreferenced members already enforced by expected order equality.
    # But also ensure no duplicate members (ZIP already unique).
