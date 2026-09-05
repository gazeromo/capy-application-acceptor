"""Immutable installed release identity; source checkouts use their Git identity."""
import json
from pathlib import Path
import re
import subprocess

from .errors import AcceptorError


def validate(value):
    if not isinstance(value, dict) or set(value) != {"contract", "version", "implementation_commit", "implementation_tree"}:
        raise AcceptorError("RELEASE_INVALID")
    if value["contract"] != "capy.independent-application-acceptance/v0" or value["version"] != "0.1.0":
        raise AcceptorError("RELEASE_INVALID")
    if any(not isinstance(value[k], str) or not re.fullmatch(r"[0-9a-f]{40}", value[k]) for k in ("implementation_commit", "implementation_tree")):
        raise AcceptorError("RELEASE_INVALID")
    return dict(value)


def get():
    packaged = Path(__file__).with_name("_release.json")
    try:
        if packaged.is_file():
            return validate(json.loads(packaged.read_bytes()))
        root = Path(__file__).resolve().parents[2]
        recorded = root / "release/IMPLEMENTATION.json"
        if recorded.is_file():
            identity = validate(json.loads(recorded.read_bytes()))
            reference = identity["implementation_commit"]
        else:
            reference = "HEAD"
            identity = None
        paths = ["src", "pyproject.toml", "build_backend.py", "LICENSE"]
        if subprocess.run(["git", "diff", "--quiet", reference, "--", *paths], cwd=root, timeout=5).returncode:
            raise AcceptorError("RELEASE_INVALID")
        if subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "--", *paths], cwd=root, timeout=5).strip():
            raise AcceptorError("RELEASE_INVALID")
        if identity is not None:
            observed = subprocess.check_output(["git", "rev-parse", reference, reference + "^{tree}"], cwd=root, timeout=5).decode().splitlines()
            if observed != [identity["implementation_commit"], identity["implementation_tree"]]:
                raise AcceptorError("RELEASE_INVALID")
            return identity
        values = subprocess.check_output(["git", "rev-parse", "HEAD", "HEAD^{tree}"], cwd=root, stderr=subprocess.DEVNULL, timeout=5).decode().splitlines()
        return validate({"contract": "capy.independent-application-acceptance/v0", "version": "0.1.0", "implementation_commit": values[0], "implementation_tree": values[1]})
    except (OSError, ValueError, subprocess.SubprocessError, IndexError) as exc:
        raise AcceptorError("RELEASE_INVALID") from exc
