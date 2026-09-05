"""Fresh offline installed-wheel journeys, copied oracle and original vectors."""
import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

from build_release import build
from control_fixtures import artifact_controls, canon, profile_change, reseal, sha

ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'tests/fixtures/product'


def check(condition, message):
    if not condition:raise AssertionError(message)


def qualify(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    wheel, build_receipt=build(output/'package')
    release=build_receipt['release']
    rows=[];portable={}
    with tempfile.TemporaryDirectory(prefix='caa-') as td:
        work=Path(td);venv=work/'venv'
        env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','PYTHONHOME','CAPY_ACCEPTOR_DATA_ROOT'}}
        env.update(PYTHONDONTWRITEBYTECODE='1',PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1',CAPY_ACCEPTOR_DATA_ROOT=str(work/'data'))
        subprocess.run([sys.executable,'-m','venv',str(venv)],check=True,env=env,timeout=120,capture_output=True)
        py=venv/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        cli=venv/('Scripts/capy-acceptor.exe' if os.name=='nt' else 'bin/capy-acceptor')
        subprocess.run([str(py),'-m','pip','install','--no-index','--no-deps',str(wheel)],check=True,env=env,timeout=120,capture_output=True)
        copied=work/'oracle';shutil.copytree(ROOT/'oracle',copied)
        module=importlib.util.spec_from_file_location('copied_oracle',copied/'oracle.py')
        oracle=importlib.util.module_from_spec(module);module.loader.exec_module(oracle)
        def command(args, expected=0, selected_env=None):
            result=subprocess.run([str(cli),*args,'--json'],env=selected_env or env,cwd=work,capture_output=True,timeout=180)
            check(result.returncode==expected, f'{args[0]} exit {result.returncode}: {result.stdout[:500]!r}')
            check(not result.stderr, f'unexpected CLI stderr: {result.stderr[:300]!r}')
            document=json.loads(result.stdout);check(result.stdout==canon(document)+b'\n','CLI canonical framing')
            return document,result.stdout
        doctor,_=command(['doctor']);check(doctor['release']==release and doctor['model_calls']==0,'installed identity')
        command(['profile','inspect','--profile',str(FIX/'csv-mean.capya')])
        if not doctor['execution']['available']:
            check(sys.platform=='darwin','unqualified CI platform')
            refusal,_=command(['accept','--candidate',str(FIX/'mean.capyrc'),'--profile',str(FIX/'csv-mean.capya')],2)
            check(refusal['code']=='EXECUTION_CONTAINMENT_UNAVAILABLE','macOS fail closed')
            with sqlite3.connect(Path(env['CAPY_ACCEPTOR_DATA_ROOT'])/'acceptor.sqlite3') as db:
                aid=db.execute('SELECT acceptance_id FROM attempts').fetchone()[0]
            inspected,_=command(['acceptance','inspect','--acceptance-id',aid])
            check(inspected['status']=='FAILED' and inspected['document'] is None,'macOS receipt withheld')
            result=subprocess.run([str(py),'-I',str(ROOT/'tools/nonexecution_probe.py'),str(ROOT),str(work/'nonexecution')],env=env,cwd=work,capture_output=True,timeout=60)
            check(result.returncode==0,f'nonexecution probe: {result.stderr[:1000]!r}')
            facts=json.loads(result.stdout)
            folder=ROOT/'tests/fixtures/oracle-revision'
            oracle.validate((folder/'candidate.capyrc').read_bytes(),(folder/'profile.capya').read_bytes(),(folder/'document.json').read_bytes(),json.loads((folder/'release.json').read_bytes()))
            rows=[{'name':'macos_fail_closed_cli','passed':True},{'name':'installed_nonexecution_portability','passed':facts['passed'],'facts':facts},{'name':'independent_copied_receipt','passed':True}]
            receipt={'schema':'capy.acceptor-qualification/v0','release':release,'build':build_receipt,'rows':rows,'passed':True,'portable':{},'model_calls':0,'execution_supported':False}
            (output/'QUALIFICATION.json').write_bytes(canon(receipt))
            return receipt
        def trial(name, candidate, profile, expected_code, classification):
            folder=output/'journeys'/name;folder.mkdir(parents=True,exist_ok=True)
            cp=folder/'candidate.capyrc';pp=folder/'profile.capya';cp.write_bytes(candidate);pp.write_bytes(profile)
            document,framed=command(['accept','--candidate',str(cp),'--profile',str(pp)],expected_code)
            code=document.get('classification',document.get('code'))
            check(code==classification, f'{name}: {code} != {classification}')
            if expected_code<2:
                data=canon(document);(folder/'document.json').write_bytes(data)
                oracle.validate(candidate,profile,data,release)
                aid=document['acceptance_id']
                inspected,_=command(['acceptance','inspect','--acceptance-id',aid])
                check(inspected['document']==document and not inspected['live'],'inspect/restart')
                check(inspected['document_sha256']==sha(data),'content-addressed document')
                replay,replayed=command(['accept','--candidate',str(cp),'--profile',str(pp)],expected_code)
                check(replayed==framed,'exact terminal CLI replay')
                if expected_code==1:check(document['schema']=='capy.independent-application-rejection/v0','no acceptance receipt for rejection')
                portable[name]={'acceptance_id':aid,'classification':code,'document_sha256':sha(data),'cases':document['cases']}
            rows.append({'name':name,'passed':True,'classification':code,'candidate_sha256':sha(candidate),'profile_sha256':sha(profile)})
            return document
        mean_profile=(FIX/'csv-mean.capya').read_bytes();artifact_profile=(FIX/'csv-summary-artifact.capya').read_bytes()
        wrong=(FIX/'total.capyrc').read_bytes();mean=(FIX/'mean.capyrc').read_bytes();artifact=(FIX/'artifact.capyrc').read_bytes()
        trial('A_verified_total',wrong,mean_profile,1,'REJECTED_INTERACTION_MISMATCH')
        accepted=trial('B_verified_mean',mean,mean_profile,0,'ACCEPTED')
        trial('C_verified_artifact',artifact,artifact_profile,0,'ACCEPTED')
        expected={'missing':'REJECTED_ARTIFACT_SET_MISMATCH','extra':'REJECTED_ARTIFACT_SET_MISMATCH','wrong_bytes':'REJECTED_ARTIFACT_BYTES_MISMATCH','undeclared':'REJECTED_APPLICATION_EXIT'}
        for name,candidate in artifact_controls(artifact):trial('C_control_'+name,candidate,artifact_profile,1,expected[name])
        trial('D_other_candidate',artifact,mean_profile,2,'APPLICATION_PROFILE_MISMATCH')
        trial('D_other_profile',mean,artifact_profile,2,'APPLICATION_PROFILE_MISMATCH')
        trial('D_historical_v0',(ROOT/'tests/fixtures/accepted-v0.capyrc').read_bytes(),mean_profile,2,'RELEASE_CANDIDATE_VERSION_UNSUPPORTED')
        for name,change in [
            ('schema',lambda m:m.update(schema='capy.application-release-candidate/v99')),
            ('execution',lambda m:m['application'].update(contract='capy.script/other')),
            ('interaction',lambda m:m['application']['interaction'].update(schema='capy.application-interaction/other')),
            ('binding',lambda m:m['toolchain'].update(release_binding_commit='0'*40)),
            ('wheel',lambda m:m['toolchain'].update(wheel_sha256='0'*64)),
            ('bundle',lambda m:m['toolchain']['authoring_bundle'].update(sha256='0'*64)),
        ]:
            candidate=reseal(mean,manifest_change=change)
            # Exact malformed identity controls must fail before execution.
            folder=output/'journeys'/('D_'+name);folder.mkdir(parents=True,exist_ok=True)
            cp=folder/'candidate.capyrc';cp.write_bytes(candidate)
            document,_=command(['accept','--candidate',str(cp),'--profile',str(FIX/'csv-mean.capya')],2)
            check(document['status']=='ERROR','D tool error')
            rows.append({'name':'D_'+name,'passed':True,'classification':document['code']})
        # Installed package replay with execution replaced by a failing spy.
        probe=work/'replay.py';probe.write_text('''import hashlib,sys
from pathlib import Path
from capy_application_acceptor import service
from capy_application_acceptor.release_identity import get
def forbidden(*args,**kwargs): raise AssertionError("application execution on replay")
service.evaluate=forbidden
data=service.Service(Path(sys.argv[1]),get()).accept(Path(sys.argv[2]).read_bytes(),Path(sys.argv[3]).read_bytes())
print(hashlib.sha256(data).hexdigest())
''')
        result=subprocess.run([str(py),'-I',str(probe),env['CAPY_ACCEPTOR_DATA_ROOT'],str(FIX/'mean.capyrc'),str(FIX/'csv-mean.capya')],env=env,cwd=work,capture_output=True,timeout=15)
        check(result.returncode==0 and result.stdout.decode().strip()==sha(canon(accepted)),'zero-execution installed replay')
        rows.append({'name':'B_zero_execution_replay','passed':True})
        # Actual installed CLI interruption while a case is active, then restart.
        other_env=dict(env,CAPY_ACCEPTOR_DATA_ROOT=str(work/'interrupted'))
        proc=subprocess.Popen([str(cli),'accept','--candidate',str(FIX/'mean.capyrc'),'--profile',str(FIX/'csv-mean.capya'),'--json'],env=other_env,cwd=work,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+30;aid=None
            while time.monotonic()<deadline and proc.poll() is None:
                dbpath=Path(other_env['CAPY_ACCEPTOR_DATA_ROOT'])/'acceptor.sqlite3'
                if dbpath.is_file():
                    try:
                        with sqlite3.connect(dbpath) as db: row=db.execute("SELECT acceptance_id FROM events WHERE kind='case_started' LIMIT 1").fetchone()
                        if row:aid=row[0];break
                    except sqlite3.Error:pass
                time.sleep(.02)
            check(aid is not None,'active case before interruption')
            duplicate,_=command(['accept','--candidate',str(FIX/'mean.capyrc'),'--profile',str(FIX/'csv-mean.capya')],2,other_env)
            check(duplicate['code']=='ACCEPTANCE_IN_PROGRESS','one live owner per identity')
            command(['accept','--candidate',str(FIX/'total.capyrc'),'--profile',str(FIX/'csv-mean.capya')],1,other_env)
            proc.kill();proc.wait(timeout=10)
            deadline=time.monotonic()+15
            while True:
                state,_=command(['acceptance','inspect','--acceptance-id',aid],0,other_env)
                if not state['live']:break
                check(time.monotonic()<deadline,'guardian ownership release');time.sleep(.02)
            check(state['status']=='INTERRUPTED' and state['document'] is None,'durable interruption')
            check(not list((Path(other_env['CAPY_ACCEPTOR_DATA_ROOT'])/'work').iterdir()),'owned root cleanup')
            retried,raw=command(['accept','--candidate',str(FIX/'mean.capyrc'),'--profile',str(FIX/'csv-mean.capya')],0,other_env)
            check(canon(retried)==canon(accepted),'retry exact receipt')
            rows.append({'name':'E_interruption_concurrency_recovery','passed':True,'acceptance_id':aid})
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=10)
        # Original frozen vectors stay byte-for-byte intact. This separate score
        # exercises the installed core with their original synthetic release ID.
        original=ROOT/'campaigns/independent_application_acceptance_v0/oracle-original'
        vector_output=output/'original-vectors'
        check(not vector_output.exists(),'qualification output must be fresh')
        result=subprocess.run([str(py),str(original/'qualify.py'),'--python',str(py),'--driver',str(ROOT/'tools/core_driver.py'),'--out',str(vector_output)],env=env,cwd=work,capture_output=True,timeout=900)
        (output/'original-vectors.log').write_bytes(result.stdout+result.stderr)
        check(result.returncode==0,'original frozen vector regression')
        vectors=json.loads((vector_output/'RESULT.json').read_bytes());check(vectors['passed']==65 and vectors['total']==65,'all original vectors')
        rows.append({'name':'original_65_vectors','passed':True,'passed_vectors':65})
    receipt={'schema':'capy.acceptor-qualification/v0','release':release,'build':build_receipt,'rows':rows,'passed':all(r['passed'] for r in rows),'portable':portable,'model_calls':0,'execution_supported':True}
    (output/'QUALIFICATION.json').write_bytes(canon(receipt))
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'build/qualification')
    result=qualify(parser.parse_args().output)
    print(json.dumps({'passed':result['passed'],'checks':len(result['rows']),'wheel_sha256':result['build']['sha256']},sort_keys=True))
