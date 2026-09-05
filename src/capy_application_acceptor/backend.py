"""Execution is a qualified host capability, independent of portable identity."""
import sys
from .errors import AcceptorError


def capability():
    name = 'linux-subreaper/v0' if sys.platform == 'linux' else 'windows-job/v0' if sys.platform == 'win32' else None
    return {'available':name is not None,'backend':name,
            'unavailable_code':None if name else 'EXECUTION_CONTAINMENT_UNAVAILABLE',
            'native_unprivileged_macos_execution_supported':False}


def require_backend():
    if not capability()['available']:
        raise AcceptorError('EXECUTION_CONTAINMENT_UNAVAILABLE')
