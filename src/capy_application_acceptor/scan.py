"""Defense-in-depth secret boundary scan.

Scans bytes for provider/API keys, GitHub tokens, PEM/OpenSSH private keys,
bearer tokens, obvious credential assignments, and the public canary.
Returns True when a secret pattern is present. Never includes matched values.
"""
from __future__ import annotations

import re

from .constants import SECRET_CANARY

_PROVIDER_KEY = re.compile(
    rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})"
)
_PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
_CREDENTIAL_ASSIGN = re.compile(
    rb"(?i)(?:api_key|apikey|access_token|client_secret|password|secret_key)"
    rb"[\"' ]*[:=][ \t]*[\"'][A-Za-z0-9_+/=\-]{20,}[\"']"
)
_BEARER = re.compile(rb"(?i)bearer[ \t]+[A-Za-z0-9_~+/=-]{20,}")
_AWS_KEY = re.compile(rb"AKIA[0-9A-Z]{16}")
_XOX = re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}")


def contains_secret(data: bytes) -> bool:
    if not isinstance(data, bytes):
        return False
    if SECRET_CANARY.encode() in data:
        return True
    if _PROVIDER_KEY.search(data):
        return True
    if _PRIVATE_KEY.search(data):
        return True
    if _CREDENTIAL_ASSIGN.search(data):
        return True
    if _BEARER.search(data):
        return True
    if _AWS_KEY.search(data):
        return True
    if _XOX.search(data):
        return True
    return False


def scan_many(blobs: list[bytes]) -> bool:
    for b in blobs:
        if contains_secret(b):
            return True
    return False
