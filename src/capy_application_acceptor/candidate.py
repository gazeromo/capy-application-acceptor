"""Muse-owned independent V1 candidate validator; frozen entrypoint."""
from .models import Candidate


def read_candidate(payload: bytes) -> Candidate:
    """Validate copied complete .capyrc bytes, or raise AcceptorError."""
    raise NotImplementedError("Contributor implementation pending")
