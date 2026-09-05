"""Deterministic, dependency-free PEP 517 wheel builder for exact clean Git source."""
import base64
import csv
import hashlib
import io
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
DIST = "capy_application_acceptor-0.1.0.dist-info"
NAME = "capy_application_acceptor-0.1.0-py3-none-any.whl"


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from capy_application_acceptor.release_identity import get
        from capy_application_acceptor.codec import canonical_bytes
        identity = get()
    finally:
        sys.path.pop(0)
    files = {}
    for path in sorted((ROOT / "src/capy_application_acceptor").rglob("*.py")):
        if path.is_symlink():
            raise ValueError("source symlink")
        files[path.relative_to(ROOT / "src").as_posix()] = path.read_bytes()
    files["capy_application_acceptor/_release.json"] = canonical_bytes(identity)
    files[DIST + "/METADATA"] = ("Metadata-Version: 2.4\nName: capy-application-acceptor\nVersion: 0.1.0\n"
        "Summary: Independent deterministic acceptance of synthetic Capy applications\n"
        "Requires-Python: >=3.11\nLicense-Expression: LicenseRef-Proprietary\nLicense-File: LICENSE\n\n").encode()
    files[DIST + "/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: capy-application-acceptor-stdlib\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    files[DIST + "/entry_points.txt"] = b"[console_scripts]\ncapy-acceptor = capy_application_acceptor.cli:main\n"
    files[DIST + "/licenses/LICENSE"] = (ROOT / "LICENSE").read_bytes()
    rows = []
    for name, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append([name, "sha256=" + digest, str(len(data))])
    rows.append([DIST + "/RECORD", "", ""])
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\n").writerows(rows)
    files[DIST + "/RECORD"] = output.getvalue().encode()
    target = Path(wheel_directory); target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target / NAME, "w", compression=zipfile.ZIP_STORED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3; info.external_attr = 0o100644 << 16
            z.writestr(info, data)
    return NAME


def get_requires_for_build_wheel(config_settings=None):
    return []


if __name__ == "__main__":
    print(build_wheel(sys.argv[1] if len(sys.argv) > 1 else "dist"))
