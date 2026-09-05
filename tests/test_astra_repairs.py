"""Regressions for independently observed defects after untouched Muse Run 2."""
import copy
import unittest
from unittest.mock import patch
import zipfile
import tempfile
from pathlib import Path

from capy_application_acceptor.candidate import read_candidate
from capy_application_acceptor.codec import parse_strict_json
from capy_application_acceptor.comparison import classify_case, parse_success_envelope, parse_failure_stderr
from capy_application_acceptor.constants import MANIFEST_MAX_BYTES, INTERACTION_MAX_BYTES
from capy_application_acceptor.errors import AcceptorError
from capy_application_acceptor.profile import read_profile
from tests.support import FIXTURES, archive, canonical, profile_bytes, profile_document, unpack
from tests.support import RELEASE
from tools.control_fixtures import reseal
from capy_application_acceptor.acceptance import evaluate


class AstraRepairTests(unittest.TestCase):
    def test_native_line_endings_preserve_failure_code(self):
        for ending in (b"\n", b"\r\n"):
            for body in (b"INPUT_INVALID", b"INPUT_INVALID: bounded detail"):
                self.assertEqual(parse_failure_stderr(body + ending), ("INPUT_INVALID", None))
        for raw in (b"INPUT_INVALID\r\r\n", b"INPUT_INVALID: bad\rline\n", b"INPUT_INVALID\nextra\n"):
            self.assertIsNotNone(parse_failure_stderr(raw)[1])

    def test_empty_subset_lists_and_safe_entrypoint(self):
        document=profile_document()
        document['interaction_expectations'].update(not_for=[],boundaries=[])
        self.assertEqual(read_profile(profile_bytes(document)).document,document)
        def rename(app):
            app['_main.py']=app.pop('main.py')
            app['capability.toml']=app['capability.toml'].replace(b'main.py',b'_main.py')
        self.assertIn('_main.py',read_candidate(reseal((FIXTURES/'fixed-v1.capyrc').read_bytes(),app_change=rename)).application_members)

    def test_source_scan_precedes_side_effect_mismatch(self):
        candidate=read_candidate(reseal((FIXTURES/'fixed-v1.capyrc').read_bytes(),app_change=lambda app:app.update({'canary.txt':b'CAPY_ACCEPTOR_SECRET_CANARY_V0'})))
        doc=profile_document();doc['candidate_requirements']['side_effect']='artifact_generation'
        with tempfile.TemporaryDirectory() as td:
            result=evaluate(candidate,read_profile(profile_bytes(doc)),RELEASE,Path(td))
        self.assertEqual(result.classification,'REJECTED_SECRET_BOUNDARY')
        self.assertEqual(result.document['secret_scan']['status'],'REJECTED')

    def test_nonregular_application_member_rejected(self):
        from capy_application_acceptor.candidate import _validate_application_zip
        import io
        app=unpack(unpack((FIXTURES/'fixed-v1.capyrc').read_bytes())['application/application.zip'])
        self.assertEqual(_validate_application_zip(archive(app),{}),app)
        for mode in (0o010644,0o020644,0o040644,0o060644,0o120644,0o140644):
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w') as z:
                for name,data in app.items():
                    item=zipfile.ZipInfo(name);item.create_system=3;item.external_attr=(mode if name=='main.py' else 0o100644)<<16;z.writestr(item,data)
            with self.subTest(mode=mode),self.assertRaises(AcceptorError):
                _validate_application_zip(output.getvalue(),{})

    def test_remote_identity_rejects_query_fragment_or_missing_repository(self):
        from capy_application_acceptor.candidate import _validate_manifest_shape
        import hashlib,json
        manifest=json.loads(unpack((FIXTURES/'fixed-v1.capyrc').read_bytes())['RELEASE-CANDIDATE.json'])
        for value in ('git://','git://example.invalid/repo?token=synthetic','git://example.invalid/repo#secret','git://user@example.invalid/repo','git://example.invalid/../repo','git://example.invalid/repo\n'):
            doc=copy.deepcopy(manifest);doc['source']['repository']={'kind':'remote','public_identity':value,'identity_sha256':hashlib.sha256(value.encode()).hexdigest()}
            with self.subTest(value=value),self.assertRaises(AcceptorError):
                _validate_manifest_shape(doc,{},b'')
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
