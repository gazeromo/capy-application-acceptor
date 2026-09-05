"""Bounded worktree and full Git-history scan; print paths and rule names only."""
import json
import hashlib
import re
import subprocess
import sys
from pathlib import Path
RULES = {
    "provider_key": rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})",
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    "credential_assignment": rb"(?i)(?:api_key|access_token|client_secret|password)[\"\' ]*[:=][ \t]*[\"\'][A-Za-z0-9_+/=-]{20,}[\"\']",
}
def scan(root):
    findings = []
    reviewed = []
    exception_path = Path(__file__).with_name('secret_scan_exceptions.json')
    exceptions = json.loads(exception_path.read_bytes())['entries'] if exception_path.exists() else []
    count = 0
    def check(label, data):
        nonlocal count
        count += 1
        for rule, pattern in RULES.items():
            matches = list(re.finditer(pattern, data))
            if matches:
                digest = hashlib.sha256(data).hexdigest()
                item = {"object": label, "rule": rule}
                if any(e['sha256']==digest and e['rule']==rule and e['occurrences']==len(matches) for e in exceptions):
                    reviewed.append({**item, 'sha256':digest, 'occurrences':len(matches)})
                else:
                    findings.append(item)
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(root).parts:
            check(str(path.relative_to(root)), path.read_bytes())
    proc = subprocess.run(["git", "rev-list", "--objects", "--all"], cwd=root, capture_output=True, check=True)
    for line in proc.stdout.decode().splitlines():
        oid = line.split(" ", 1)[0]
        kind = subprocess.check_output(["git", "cat-file", "-t", oid], cwd=root).strip()
        if kind == b"blob":
            check("git:" + oid, subprocess.check_output(["git", "cat-file", "blob", oid], cwd=root))
    print(json.dumps({"scanned_objects": count, "findings": findings, "reviewed_synthetic": reviewed}, sort_keys=True))
    return bool(findings)
if __name__ == "__main__":
    sys.exit(scan(Path(sys.argv[1] if len(sys.argv)>1 else ".").resolve()))
