"""Muse-owned closed acceptance-profile validator; frozen entrypoint."""
from .models import Profile


def read_profile(payload: bytes) -> Profile:
    """Validate copied complete .capya bytes, or raise AcceptorError."""
    raise NotImplementedError("Contributor implementation pending")
