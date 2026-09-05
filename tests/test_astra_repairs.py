"""Regressions for independently observed defects after untouched Muse Run 2."""
import copy
import unittest
from unittest.mock import patch
import zipfile

from capy_application_acceptor.candidate import read_candidate
from capy_application_acceptor.codec import parse_strict_json
from capy_application_acceptor.comparison import classify_case, parse_success_envelope
from capy_application_acceptor.constants import MANIFEST_MAX_BYTES, INTERACTION_MAX_BYTES
from capy_application_acceptor.errors import AcceptorError
from capy_application_acceptor.profile import read_profile
from tests.support import FIXTURES, archive, canonical, profile_bytes, profile_document, unpack


class AstraRepairTests(unittest.TestCase):
    def test_actual_developer_source_dotfiles_supported(self):
        for name in ("total.capyrc", "mean.capyrc", "artifact.capyrc"):
            with self.subTest(name=name):
                candidate = read_candidate((FIXTURES / "product" / name).read_bytes())
                self.assertIn(".gitignore", candidate.application_members)

    def test_metadata_bounds_before_member_read(self):
        original = zipfile.ZipFile.read
        for name, maximum in (("RELEASE-CANDIDATE.json", MANIFEST_MAX_BYTES), ("application/interaction.json", INTERACTION_MAX_BYTES)):
            members = unpack((FIXTURES / "fixed-v1.capyrc").read_bytes())
            members[name] = b" " * (maximum + 1)
            calls = []
            def observed(z, member, *args, **kwargs):
                calls.append(member if isinstance(member, str) else member.filename)
                return original(z, member, *args, **kwargs)
            with self.subTest(name=name), patch.object(zipfile.ZipFile, "read", observed):
                with self.assertRaises(AcceptorError):
                    read_candidate(archive(members))
                self.assertNotIn(name, calls)

    def test_valid_profile_larger_than_one_mib(self):
        document = profile_document()
        # Exact expected result JSON has no invented 1 MiB document restriction.
        document["cases"][0]["expect"]["result"] = {"large": "x" * (1024 * 1024)}
        payload = profile_bytes(document)
        self.assertGreater(len(payload), 1024 * 1024)
        self.assertEqual(read_profile(payload).document, document)

    def test_json_overflow_and_lone_surrogate_are_malformed_output(self):
        for raw in (b'{"artifacts":[],"value":1e309}', b'{"artifacts":[],"value":"\\ud800"}'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_strict_json(raw)
                self.assertEqual(parse_success_envelope(raw + b"\n"), (None, "json"))

    def test_result_and_failure_codes_precede_artifact_anomaly(self):
        facts = dict(timed_out=False, output_limited=False, secret_hit=False, exit_code=0, stdout=b"", stderr=b"",
                     actual_artifacts=[], envelope_error=None, observed_result={"wrong":1}, observed_failure_code=None,
                     observed_status="ok", artifact_anomaly="unsafe-name")
        self.assertEqual(classify_case(expect={"status":"ok", "result":{"right":1}}, **facts), "REJECTED_RESULT_MISMATCH")
        facts.update(observed_status="failed", observed_failure_code="WRONG", observed_result=None, exit_code=2)
        self.assertEqual(classify_case(expect={"status":"failed", "failure_code":"EXPECTED"}, **facts), "REJECTED_FAILURE_CODE_MISMATCH")
