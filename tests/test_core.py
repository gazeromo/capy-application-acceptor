"""Frozen visible core qualification. Contributor may not alter this file."""
import copy
import tempfile
from pathlib import Path
import unittest
import sys
from capy_application_acceptor.candidate import read_candidate
from capy_application_acceptor.profile import read_profile
from capy_application_acceptor.acceptance import evaluate
from capy_application_acceptor.errors import AcceptorError
from tests.support import FIXTURES, RELEASE, archive, canonical, digest, profile_bytes, profile_document, unpack

class CandidateTests(unittest.TestCase):
    def test_accepted_public_v1(self):
        payload=(FIXTURES/'fixed-v1.capyrc').read_bytes();v=read_candidate(payload)
        self.assertEqual(v.bundle_sha256,digest(payload))
        self.assertEqual(v.manifest['application']['id'],'demo.interaction_fixture')
        self.assertEqual(digest(v.wheel_bytes),'56c9f6c930b21d600a2e8f10da7a3e92f5cfbf1c6d91490d170d1790e5555603')
    def test_v0_has_causal_version_error(self):
        with self.assertRaises(AcceptorError) as caught:read_candidate((FIXTURES/'accepted-v0.capyrc').read_bytes())
        self.assertEqual(caught.exception.code,'RELEASE_CANDIDATE_VERSION_UNSUPPORTED')
    def test_outer_tamper(self):
        data=(FIXTURES/'fixed-v1.capyrc').read_bytes();members=unpack(data)
        variants=[data+b'trailing',archive(members,comment=b'comment'),archive(dict(reversed(list(members.items()))))]
        changed=dict(members);changed['application/interaction.json']+=b' ';variants.append(archive(changed))
        for payload in variants:
            with self.subTest(digest=digest(payload)),self.assertRaises(AcceptorError):read_candidate(payload)

class ProfileTests(unittest.TestCase):
    def test_valid_profile_and_digest(self):
        data=profile_bytes();v=read_profile(data)
        self.assertEqual(v.bundle_sha256,digest(data));self.assertEqual(len(v.document['cases']),2)
    def test_closed_and_bounded_profile(self):
        base=profile_document();variants=[]
        for mutate in [lambda d:d.update(unknown=True),lambda d:d['limits'].update(timeout_seconds=31),
                       lambda d:d['candidate_requirements'].update(state_required=True),
                       lambda d:d['candidate_requirements'].update(connections=[{}]),
                       lambda d:d['cases'].pop(),lambda d:d['cases'][1].update(case_id='normal')]:
            doc=copy.deepcopy(base);mutate(doc);variants.append(profile_bytes(doc))
        for data in variants:
            with self.subTest(digest=digest(data)),self.assertRaises(AcceptorError):read_profile(data)
    def test_expected_artifact_integrity(self):
        data=profile_bytes(artifact=True);members=unpack(data);members['expected/normal/text-report.txt']=b'wrong'
        with self.assertRaises(AcceptorError):read_profile(archive(members))

@unittest.skipUnless(sys.platform in ('linux','win32'), 'Owner amendment: no native macOS execution backend')
class ExecutionTests(unittest.TestCase):
    def run_case(self,profile=None,artifact=False):
        candidate=read_candidate((FIXTURES/('artifact-v1.capyrc' if artifact else 'fixed-v1.capyrc')).read_bytes())
        p=read_profile(profile_bytes(profile,artifact=artifact))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);evaluation=evaluate(candidate,p,RELEASE,root)
            self.assertEqual(list(root.iterdir()),[], 'case cleanup must complete before return')
        return evaluation
    def test_independent_positive_and_negative(self):
        result=self.run_case();self.assertEqual(result.status,'ACCEPTED')
        self.assertTrue(all(c['matched'] for c in result.document['cases']))
        self.assertEqual(result.document['cleanup'],{'status':'CONFIRMED'})
    def test_wrong_result_rejected(self):
        p=profile_document();p['cases'][0]['expect']['result']={'message':'goodbye'}
        result=self.run_case(p);self.assertEqual(result.classification,'REJECTED_RESULT_MISMATCH')
        self.assertEqual(result.status,'REJECTED')
    def test_wrong_failure_code_rejected(self):
        p=profile_document();p['cases'][1]['expect']['failure_code']='WRONG_FAILURE'
        self.assertEqual(self.run_case(p).classification,'REJECTED_FAILURE_CODE_MISMATCH')
    def test_interaction_expectation_rejected(self):
        p=profile_document();p['interaction_expectations']['purpose']='A different exact purpose.'
        result=self.run_case(p);self.assertEqual(result.classification,'REJECTED_INTERACTION_MISMATCH')
        self.assertEqual(result.document['cases'],[])
    def test_artifact_bytes_collected_and_bound(self):
        result=self.run_case(artifact=True);self.assertEqual(result.status,'ACCEPTED')
        artifact=result.document['cases'][0]['observed']['artifacts'][0]
        self.assertEqual(artifact,{'filename':'text-report.txt','sha256':digest(b'Brief\n=====\n\nHello\n'),'size_bytes':19})
    def test_portable_bytes_deterministic(self):
        first=canonical(self.run_case().document);second=canonical(self.run_case().document)
        self.assertEqual(first,second);self.assertNotIn(b'/Users/',first);self.assertNotIn(b'/tmp/',first)

if __name__=='__main__':unittest.main()
