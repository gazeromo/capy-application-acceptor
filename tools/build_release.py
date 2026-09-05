"""Build two clean detached snapshots; preserve one exact reproducible wheel."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, cwd):
    return subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT, timeout=120)


def build(destination):
    destination = Path(destination).resolve(); destination.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "src"))
    from capy_application_acceptor.release_identity import get
    identity = get()
    wheels = []
    for index in range(2):
        with tempfile.TemporaryDirectory(prefix="capy-build-") as td:
            clone = Path(td) / "source"
            run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout", str(ROOT), str(clone)], ROOT)
            run(["git", "checkout", "--quiet", "--detach", identity["implementation_commit"]], clone)
            if run(["git", "status", "--porcelain"], clone).strip():
                raise ValueError("snapshot not clean")
            run([sys.executable, "-B", "build_backend.py", "dist"], clone)
            wheel = next((clone / "dist").glob("*.whl"))
            wheels.append(wheel.read_bytes())
            filename = wheel.name
    if wheels[0] != wheels[1]:
        raise ValueError("non-reproducible wheel")
    (destination / filename).write_bytes(wheels[0])
    receipt = {"schema": "capy.acceptor-build/v0", "release": identity, "clean_builds": 2,
               "byte_identical": True, "filename": filename, "sha256": hashlib.sha256(wheels[0]).hexdigest(), "size_bytes": len(wheels[0])}
    (destination / "build.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return destination / filename, receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path, default=ROOT / "dist")
    print(json.dumps(build(parser.parse_args().output)[1], sort_keys=True))
