"""Local-only storage roots; no runtime or Developer discovery."""
import os
import sys
from pathlib import Path


def data_root():
    explicit = os.environ.get("CAPY_ACCEPTOR_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Capy/ApplicationAcceptor"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Capy/ApplicationAcceptor"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "capy/application-acceptor"
