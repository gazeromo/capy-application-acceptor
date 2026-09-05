"""Test-owned external owner/child processes for actual interruption tests."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def app(root, mode):
    (root / "parent.pid").write_text(str(os.getpid()))
    code = "import os,time;from pathlib import Path;p=Path(" + repr(str(root)) + ");(p/'child.pid').write_text(str(os.getpid()));time.sleep(30);(p/'escaped').write_text('bad')"
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 10
    while not (root / "child.pid").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("child did not start")
        time.sleep(.01)
    if mode == "hold":
        time.sleep(30)
    print("complete", flush=True)


def owner(root, mode):
    from capy_application_acceptor.process import run_bounded, scrubbed_env
    def execute(*args, **kwargs):
        run_bounded([sys.executable, str(Path(__file__).resolve()), "app", str(root), mode],
                    input_bytes=None, timeout_seconds=60, max_stdout=1024, max_stderr=1024,
                    cwd=root, env=scrubbed_env({"HOME":str(root),"TMPDIR":str(root),"TEMP":str(root),"TMP":str(root)}))
        raise RuntimeError("test owner should have been interrupted")
    if mode == "service":
        from capy_application_acceptor import service
        from tests.support import FIXTURES, RELEASE
        service.evaluate = execute
        mode = "hold"
        signal.signal(signal.SIGTERM, lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
        service.Service(root / "store", RELEASE).accept((FIXTURES / "fixed-v1.capyrc").read_bytes(), (FIXTURES / "greeting.capya").read_bytes())
    else:
        execute()


if __name__ == "__main__":
    action, path, mode = sys.argv[1:]
    (app if action == "app" else owner)(Path(path), mode)
