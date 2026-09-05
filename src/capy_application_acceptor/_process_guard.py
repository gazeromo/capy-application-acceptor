"""POSIX guardian for bounded, test-owned child trees.

Only PID/parent/group/birth/status metadata is read. Never process arguments,
environment or credentials. EOF from the owner triggers tree cleanup even
when the owner was killed. An inherited identity-lock descriptor, when supplied
by the service, keeps ownership live until cleanup ends.
"""
import os
import selectors
import signal
import subprocess
import sys
import time


def snapshot():
    result = subprocess.run(["/bin/ps", "-A", "-o", "pid=,ppid=,pgid=,stat=,lstart="],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=1, check=True, text=True)
    rows = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 9:
            rows[int(fields[0])] = (int(fields[1]), int(fields[2]), fields[3], " ".join(fields[4:]))
    return rows


def collect(root, birth, known, rows):
    # A reused root PID cannot grant authority over a new process group.
    if root in rows and rows[root][3] != birth:
        return
    for pid, row in rows.items():
        if row[1] == root:
            known[pid] = row[3]
    changed = True
    while changed:
        changed = False
        for pid, row in rows.items():
            parent = row[0]
            if pid not in known and parent in known and parent in rows and rows[parent][3] == known[parent]:
                known[pid] = row[3]
                changed = True


def kill_owned(root, birth, known):
    deadline = time.monotonic() + 2
    while True:
        rows = snapshot()
        collect(root, birth, known, rows)
        live = {pid for pid, stamp in known.items() if pid in rows and rows[pid][3] == stamp and not rows[pid][2].startswith("Z")}
        if not live:
            return True
        groups = {root} if root not in rows or rows[root][3] == birth else set()
        for pid in live:
            group = rows[pid][1]
            if group in known and group in rows and rows[group][3] == known[group]:
                groups.add(group)
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        for pid in live:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def main():
    root = int(sys.argv[1])
    rows = snapshot()
    if root not in rows or rows[root][0] != os.getppid():
        return 2
    birth = rows[root][3]
    known = {root: birth}
    print("READY", flush=True)
    selector = selectors.DefaultSelector()
    selector.register(sys.stdin, selectors.EVENT_READ)
    try:
        while True:
            if selector.select(0.03):
                # No messages are required. Owner closes this pipe on every exit.
                if not os.read(sys.stdin.fileno(), 4096):
                    break
            collect(root, birth, known, snapshot())
    finally:
        selector.close()
        cleaned = kill_owned(root, birth, known)
    return 0 if cleaned else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError, ValueError):
        # Fail closed for the root group if supervision itself fails.
        try:
            os.killpg(int(sys.argv[1]), signal.SIGKILL)
        except (OSError, ValueError):
            pass
        raise SystemExit(4)
