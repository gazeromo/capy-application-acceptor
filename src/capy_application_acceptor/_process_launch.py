"""POSIX launch gate: no application code runs before its guardian is ready."""
import json
import os
import sys

fd = int(sys.argv[1])
ready = os.read(fd, 1)
os.close(fd)
if ready != b"1":
    raise SystemExit(125)
argv = json.loads(sys.argv[2])
os.execvpe(argv[0], argv, os.environ)
