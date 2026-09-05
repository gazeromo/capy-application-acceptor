"""Installed-package non-execution qualification for the macOS amendment.

The persistence document is an explicitly synthetic pre-existing store fixture;
it is never presented as a new acceptance or actual candidate execution.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from capy_application_acceptor import service
from capy_application_acceptor.candidate import read_candidate
from capy_application_acceptor.profile import read_profile
from capy_application_acceptor.codec import canonical_bytes
from capy_application_acceptor.errors import AcceptorError
from capy_application_acceptor.models import Evaluation
from capy_application_acceptor.release_identity import get

root=Path(sys.argv[1]);state=Path(sys.argv[2]);fixtures=root/'tests/fixtures'
original=root/'campaigns/independent_application_acceptance_v0/oracle-original'
sys.path.insert(0,str(original))
spec=importlib.util.spec_from_file_location('original_vectors',original/'qualify.py')
vectors=importlib.util.module_from_spec(spec);spec.loader.exec_module(vectors)
count=0
with patch.object(subprocess,'Popen',side_effect=AssertionError('candidate process started')) as spawn:
    s=service.Service(state/'inputs',get())
    for name,candidate,profile,code,classification in vectors.vectors():
        if code!=2:continue
        try:s.accept(candidate,profile)
        except AcceptorError as ex:assert ex.code==classification,(name,ex.code,classification)
        else:raise AssertionError(name)
        count+=1
    for name in ('mean','total','artifact'):read_candidate((fixtures/'product'/(name+'.capyrc')).read_bytes())
    for name in ('csv-mean','csv-summary-artifact'):read_profile((fixtures/'product'/(name+'.capya')).read_bytes())
    try:s.accept((fixtures/'product/mean.capyrc').read_bytes(),(fixtures/'product/csv-mean.capya').read_bytes())
    except AcceptorError as ex:assert ex.code=='EXECUTION_CONTAINMENT_UNAVAILABLE'
    else:raise AssertionError('unsupported execution accepted')
    assert not list((state/'inputs/documents').iterdir())
    # Pre-existing synthetic store fixture; verifies replay without execution.
    document=json.loads((fixtures/'persistence-only.json').read_bytes())
    release=document['identity']['acceptor'];c=(fixtures/'fixed-v1.capyrc').read_bytes();p=(fixtures/'greeting.capya').read_bytes()
    persisted=service.Service(state/'fixture-replay',release)
    identity=document['identity'];aid=document['acceptance_id']
    persisted.store.ingest(read_candidate(c),read_profile(p),c,p)
    generation=persisted.store.allocate(aid,identity)
    persisted.store.finish(aid,generation,Evaluation('ACCEPTED','ACCEPTED',document,[]))
    with patch.object(service,'evaluate',side_effect=AssertionError('replayed execution')):
        actual=service.Service(state/'fixture-replay',release).accept(c,p)
        assert actual==canonical_bytes(document)
        assert service.Service(state/'fixture-replay',release).inspect(aid)['document']==document
    assert spawn.call_count==0
print(json.dumps({'passed':True,'input_tamper_vectors':count,'validated_real_developer_candidates':3,'candidate_processes_started':0,'fresh_acceptance_receipts':0,'synthetic_existing_store_replay':True},sort_keys=True))
