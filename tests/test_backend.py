"""No candidate process or receipt on hosts lacking qualified containment."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from capy_application_acceptor.backend import capability
from capy_application_acceptor.errors import AcceptorError
from capy_application_acceptor.process import run_bounded
from capy_application_acceptor.service import Service
from tests.support import FIXTURES, RELEASE


class BackendTests(unittest.TestCase):
    def test_macos_refuses_fresh_execution_without_any_subprocess(self):
        with tempfile.TemporaryDirectory() as td, patch('sys.platform','darwin'), patch('subprocess.Popen',side_effect=AssertionError('candidate process started')):
            self.assertFalse(capability()['available'])
            service=Service(Path(td),RELEASE)
            with self.assertRaisesRegex(AcceptorError,'EXECUTION_CONTAINMENT_UNAVAILABLE'):
                service.accept((FIXTURES/'fixed-v1.capyrc').read_bytes(),(FIXTURES/'greeting.capya').read_bytes())
            self.assertEqual(list((Path(td)/'documents').iterdir()),[])
            self.assertEqual(list((Path(td)/'work').iterdir()),[])
            with service.store.connect() as db:
                row=db.execute('SELECT * FROM attempts').fetchone()
            self.assertEqual(row['status'],'FAILED')
            self.assertEqual(row['error_code'],'EXECUTION_CONTAINMENT_UNAVAILABLE')
            with self.assertRaisesRegex(AcceptorError,'EXECUTION_CONTAINMENT_UNAVAILABLE'):
                run_bounded(['unused'],input_bytes=None,timeout_seconds=1,max_stdout=1,max_stderr=1,env={},cwd=td)
