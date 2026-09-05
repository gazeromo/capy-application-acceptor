"""Campaign-only synthetic containment probe, not product implementation."""
import errno
import json
import socket
from pathlib import Path
ROOT = Path.cwd()
OUTSIDE = ROOT.parent / ".capy-acceptor-preflight-01a07095"
results = {}
def attempt(name, action):
    try:
        action()
        results[name] = {"allowed": True}
    except OSError as exc:
        results[name] = {"allowed": False, "errno": exc.errno, "exception": type(exc).__name__}
def write_remove(path):
    with path.open("x") as f:
        f.write("PUBLIC_SYNTHETIC_WRITE_CANARY\n")
    path.unlink()
attempt("workspace_write", lambda: write_remove(ROOT / "probe-workspace-write.txt"))
attempt("outside_write", lambda: write_remove(OUTSIDE / "write-canary.txt"))
attempt("git_write", lambda: write_remove(ROOT / ".git" / "capy-probe-write"))
attempt("outside_read", lambda: (OUTSIDE / "read-canary.txt").read_bytes())
def network():
    with socket.create_connection(("1.1.1.1", 443), timeout=3):
        pass
attempt("shell_network", network)
print(json.dumps(results, sort_keys=True))
