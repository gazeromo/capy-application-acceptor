"""Synthetic tests only; never print canary or environment values."""
import json
import os
from pathlib import Path
import socket
import subprocess
checks = {}
def attempt(label, fn):
    try:
        fn(); checks[label] = {"allowed": True}
    except OSError as ex:
        checks[label] = {"allowed": False, "errno": ex.errno, "error": type(ex).__name__}
def write(path):
    with path.open("x") as stream: stream.write("public synthetic canary\n")
    path.unlink()
root = Path.cwd()
attempt("workspace_read", lambda: (root / "README.md").read_bytes())
attempt("workspace_write", lambda: write(root / "capy-containment-write.txt"))
attempt("git_write", lambda: write(root / ".git" / "capy-containment-write"))
attempt("host_private_read", lambda: Path("/Users/gazeromo/.capy-private-containment-canary").read_bytes())
attempt("host_private_write", lambda: write(Path("/Users/gazeromo/.capy-private-containment-write")))
attempt("host_sibling_read", lambda: Path("/Users/gazeromo/dev/.capy-acceptor-preflight-01a07095/read-canary.txt").read_bytes())
def connect(host, port):
    with socket.create_connection((host, port), timeout=3): pass
attempt("arbitrary_network", lambda: connect("1.1.1.1", 443))
attempt("credential_proxy_network", lambda: connect("gateway", 8765))
proxy_ip = (root / "tools/muse_containment/gateway-ip.txt").read_text().strip()
checks["credential_proxy_ip"] = proxy_ip
attempt("credential_proxy_numeric_network", lambda: connect(proxy_ip, 8765))
checks["credential_environment_names_present"] = [k for k in ("MUSE_SECRET_CANARY", "META_API_KEY", "MODEL_API_KEY", "OPENAI_API_KEY", "GITHUB_TOKEN", "SSH_AUTH_SOCK") if k in os.environ]
attempt("provider_auth_file_read", lambda: Path("/home/capy/.config/muse/auth.json").read_bytes())
checks["host_mounts_present"] = any(v in Path("/proc/self/mountinfo").read_text() for v in ("/Users/gazeromo", "docker.sock"))
# Examine process environments without printing contents; only the named synthetic canary.
visible = []
for path in Path("/proc").glob("[0-9]*/environ"):
    try:
        if b"MUSE_SECRET_CANARY=" in path.read_bytes(): visible.append(path.parent.name)
    except OSError: pass
checks["credential_canary_processes_visible"] = visible
checks["python_subprocess_canary_visible"] = subprocess.check_output(["python3", "-c", "import os; print('MUSE_SECRET_CANARY' in os.environ)"], text=True).strip() == "True"
print(json.dumps(checks, sort_keys=True))
