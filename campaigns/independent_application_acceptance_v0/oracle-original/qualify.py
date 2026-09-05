"""Frozen black-box qualification controller. Oracle itself imports no product."""
import argparse
import copy
import json
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import tomllib
import zipfile
import io
from oracle import BASE,NAMES,TRUST,BUNDLE,canon,sha,pack,unpack,candidate,profile,expected,validate,CLAIMS


def reseal(data,change_app=None,change_manifest=None,change_receipt=None):
    parts=unpack(data);m=json.loads(parts[NAMES[0]]);v=json.loads(parts[NAMES[3]])
    if change_app:
        app=unpack(parts[NAMES[1]]);change_app(app);parts[NAMES[1]]=pack(app)
        m['application']['archive'].update(sha256=sha(parts[NAMES[1]]),size_bytes=len(parts[NAMES[1]]))
        m['application']['descriptor_sha256']=sha(app['capability.toml'])
        descriptor=tomllib.loads(app['capability.toml'].decode());m['application']['id']=descriptor['id'];v['application_id']=descriptor['id']
        v['application_archive']={k:m['application']['archive'][k] for k in ['sha256','size_bytes']}
        parts[NAMES[2]]=canon(json.loads(app['interaction.json']))
        ib=m['application']['interaction'];ib.update(sha256=sha(parts[NAMES[2]]),size_bytes=len(parts[NAMES[2]]),source_sha256=sha(app['interaction.json']))
        ib['operation_id']=json.loads(app['interaction.json'])['operation']['operation_id'];v['interaction_contract']['operation_id']=ib['operation_id']
        v['interaction_contract'].update(canonical_sha256=ib['sha256'],canonical_size_bytes=ib['size_bytes'],source_sha256=ib['source_sha256'])
        for stage in v['stages']:
            if stage['name']=='archive_preserve':stage['facts']=v['application_archive'].copy()
            if stage['name']=='package_compare':stage['facts']={'sha256_a':v['application_archive']['sha256'],'sha256_b':v['application_archive']['sha256'],'size_a':v['application_archive']['size_bytes'],'size_b':v['application_archive']['size_bytes']}
            if stage['name']=='interaction_preserve':stage['facts'].update(source_sha256=ib['source_sha256'],canonical_sha256=ib['sha256'],canonical_size_bytes=ib['size_bytes'])
    if change_receipt:change_receipt(v)
    parts[NAMES[3]]=canon(v);m['verification']['receipt'].update(sha256=sha(parts[NAMES[3]]),size_bytes=len(parts[NAMES[3]]))
    if change_manifest:change_manifest(m)
    a=m['application'];i=a['interaction'];t=m['toolchain']
    identity={'schema':m['schema'],'project_id':m['project']['project_id'],'application_id':a['id'],'source':m['source'],'application_archive_sha256':a['archive']['sha256'],'application_descriptor_sha256':a['descriptor_sha256'],'interaction':{'schema':i['schema'],'source_sha256':i['source_sha256'],'canonical_sha256':i['sha256'],'operation_id':i['operation_id']},'verification_receipt_sha256':m['verification']['receipt']['sha256'],'toolchain':{'release_binding_commit':t['release_binding_commit'],'authoring_bundle_sha256':t['authoring_bundle']['sha256'],'wheel_sha256':t['wheel_sha256'],'interaction_contract':t['interaction_contract']}}
    m['identity_sha256']=sha(canon(identity));m['release_candidate_id']='rc_'+m['identity_sha256'][:32];parts[NAMES[0]]=canon(m)
    return pack(parts)


def profile_change(data,fn):
    parts=unpack(data);doc=json.loads(parts['ACCEPTANCE-PROFILE.json']);fn(doc);parts['ACCEPTANCE-PROFILE.json']=canon(doc);return pack(parts)


def raw_vectors():
    c=(BASE/'fixed-v1.capyrc').read_bytes();p=(BASE/'greeting.capya').read_bytes()
    artifact=(BASE/'artifact-v1.capyrc').read_bytes();ap=(BASE/'report.capya').read_bytes()
    cp=(BASE/'csv-mean.capya').read_bytes();cc=(BASE/'csv-correct.capyrc').read_bytes()
    yield 'csv_resource_valid',cc,cp,0,'ACCEPTED'
    yield 'csv_resource_wrong_value',(BASE/'csv-wrong-value.capyrc').read_bytes(),cp,1,'REJECTED_RESULT_MISMATCH'
    yield 'csv_resource_total_contract',(BASE/'csv-total.capyrc').read_bytes(),cp,1,'REJECTED_INTERACTION_MISMATCH'
    cm=unpack(cp);cm['fixtures/normal/products.csv']=b'price\n1\n';yield 'profile_fixture_replacement',cc,pack(cm),2,None
    yield 'profile_duplicate_slot',cc,profile_change(cp,lambda d:d['cases'][0]['resources'].append(copy.deepcopy(d['cases'][0]['resources'][0]))),2,None
    for label,mut in [('comment',lambda z,i:setattr(z,'comment',b'x')),('mode',lambda z,i:setattr(i,'external_attr',0o100755<<16)),('timestamp',lambda z,i:setattr(i,'date_time',(2001,1,1,0,0,0)))]:
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for n,b in unpack(p).items():
                info=zipfile.ZipInfo(n,(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o100644<<16;mut(z,info);z.writestr(info,b)
        yield 'profile_metadata_'+label,c,stream.getvalue(),2,None
    for label,data in [('candidate',c),('profile',p)]:
        stream=io.BytesIO()
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(stream,'w') as z:
                for n,b in list(unpack(data).items())+[next(iter(unpack(data).items()))]:
                    info=zipfile.ZipInfo(n,(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o100644<<16;z.writestr(info,b)
        yield label+'_duplicate_member',stream.getvalue() if label=='candidate' else c,stream.getvalue() if label=='profile' else p,2,None
    yield 'greeting_valid',c,p,0,'ACCEPTED'
    yield 'artifact_valid',artifact,ap,0,'ACCEPTED'
    yield 'historical_v0',(BASE/'accepted-v0.capyrc').read_bytes(),p,2,'RELEASE_CANDIDATE_VERSION_UNSUPPORTED'
    members=unpack(c)
    yield 'candidate_trailing',c+b'trailer',p,2,None
    for label,fn in [('reordered',lambda x:dict(reversed(list(x.items())))),('extra',lambda x:{**x,'extra.txt':b'x'}),('absolute',lambda x:{**x,'/private.txt':b'x'}),('traversal',lambda x:{**x,'../escape':b'x'}),('backslash',lambda x:{**x,'a\\b':b'x'})]:yield 'candidate_'+label,pack(fn(members)),p,2,None
    for index in [0,1,2,3,4]:
        changed=dict(members);changed[NAMES[index]]+=b' ';yield 'candidate_member_'+str(index),pack(changed),p,2,None
    for label,edit in [('comment',lambda z,i:setattr(z,'comment',b'x')),('timestamp',lambda z,i:setattr(i,'date_time',(2000,1,1,0,0,0))),('compression',lambda z,i:setattr(i,'compress_type',8)),('mode',lambda z,i:setattr(i,'external_attr',0o100755<<16)),('system',lambda z,i:setattr(i,'create_system',0))]:
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:
            for n,b in members.items():
                i=zipfile.ZipInfo(n,(1980,1,1,0,0,0));i.create_system=3;i.external_attr=0o100644<<16;edit(z,i);z.writestr(i,b)
        yield 'candidate_'+label,stream.getvalue(),p,2,None
    for label,mut in [('status',lambda v:v.update(status='FAILED')),('classification',lambda v:v.update(classification='UNVERIFIED')),('stage',lambda v:v['stages'][0].update(status='FAILED')),('stage_truth',lambda v:v['stages'][1]['facts'].update(candidate_unchanged=False)),('source',lambda v:v['source'].update(tree='3'*40))]:yield 'verification_'+label,reseal(c,change_receipt=mut),p,2,None
    yield 'weakened_handoff',reseal(c,change_manifest=lambda m:m['handoff'].update(independent_acceptance='performed')),p,2,None
    yield 'cross_application',reseal(c,change_receipt=lambda v:v.update(application_id='demo.other')),p,2,None
    for label,mut in [('unknown',lambda d:d.update(extra=1)),('unknown_case',lambda d:d['cases'][0].update(extra=1)),('boolean_limit',lambda d:d['limits'].update(max_cases=True)),('limit',lambda d:d['limits'].update(timeout_seconds=31)),('no_negative',lambda d:d['cases'].pop()),('no_positive',lambda d:d['cases'].pop(0)),('duplicate_case',lambda d:d['cases'][1].update(case_id='normal')),('state',lambda d:d['candidate_requirements'].update(state_required=True)),('connections',lambda d:d['candidate_requirements'].update(connections=[{}])),('side_effect',lambda d:d['candidate_requirements'].update(side_effect='external_effect')),('toolchain',lambda d:d['candidate_requirements'].update(toolchain_wheel_sha256='0'*64)),('bad_member',lambda d:d['cases'][0]['resources'].append({'slot':'products','filename':'../x','member':'fixtures/normal/../x','sha256':'0'*64}))]:yield 'profile_'+label,c,profile_change(p,mut),2,None
    pm=unpack(p);pm['extra.txt']=b'x';yield 'profile_extra',c,pack(pm),2,None
    yield 'profile_noncanonical',c,profile_change(p,lambda d:None)+b'x',2,None
    changed=unpack(ap);changed['expected/normal/text-report.txt']=b'wrong';yield 'profile_artifact_digest',artifact,pack(changed),2,None
    yield 'profile_pairing',c,profile_change(p,lambda d:d.update(application_id='demo.other')),2,'APPLICATION_PROFILE_MISMATCH'
    yield 'interaction_purpose',c,profile_change(p,lambda d:d['interaction_expectations'].update(purpose='Owner requires a different purpose.')),1,'REJECTED_INTERACTION_MISMATCH'
    for label,request in [('wrong_field',{'other':'hello'}),('wrong_value',{'message':'incorrect'}),('extra_field',{'message':'hello','extra':1})]:
        text='from capy_script import Context\nctx=Context()\nif ctx.request: ctx.fail("REQUEST_INVALID")\nctx.complete('+repr(request)+')\n'
        changed=reseal(c,change_app=lambda app,text=text:app.update({'main.py':text.encode()}))
        yield 'semantic_'+label,changed,p,1,'REJECTED_RESULT_MISMATCH'
    yield 'semantic_failure_code',reseal(c,change_app=lambda app:app.update({'main.py':app['main.py'].replace(b'REQUEST_INVALID',b'WRONG_FAILURE')})),p,1,'REJECTED_FAILURE_CODE_MISMATCH'
    yield 'semantic_unexpected_success',reseal(c,change_app=lambda app:app.update({'main.py':b'from capy_script import Context\nContext().complete({"message":"hello"})\n'})),p,1,'REJECTED_RESULT_MISMATCH'
    yield 'semantic_unexpected_failure',reseal(c,change_app=lambda app:app.update({'main.py':b'from capy_script import Context\nContext().fail("REQUEST_INVALID")\n'})),p,1,'REJECTED_RESULT_MISMATCH'
    timeout=profile_change(p,lambda d:d['limits'].update(timeout_seconds=1))
    yield 'semantic_timeout',reseal(c,change_app=lambda app:app.update({'main.py':b'import time\ntime.sleep(3)\n'})),timeout,1,'REJECTED_CASE_TIMEOUT'
    yield 'semantic_output_limit',reseal(c,change_app=lambda app:app.update({'main.py':b'print("x"*1000000)\n'})),p,1,'REJECTED_OUTPUT_LIMIT'
    yield 'semantic_secret',reseal(c,change_app=lambda app:app.update({'canary.txt':b'CAPY_ACCEPTOR_SECRET_CANARY_V0'})),p,1,'REJECTED_SECRET_BOUNDARY'
    yield 'semantic_artifact_missing',reseal(artifact,change_app=lambda app:app.update({'main.py':app['main.py'].replace(b'    ctx.artifact("text-report.txt", report.encode("utf-8"))',b'    pass')})),ap,1,'REJECTED_ARTIFACT_SET_MISMATCH'
    yield 'semantic_artifact_extra',reseal(artifact,change_app=lambda app:app.update({'main.py':app['main.py'].replace(b'    ctx.complete({',b'    ctx.artifact("extra.txt", b"extra")\n    ctx.complete({')})),ap,1,'REJECTED_ARTIFACT_SET_MISMATCH'
    yield 'semantic_artifact_bytes',reseal(artifact,change_app=lambda app:app.update({'main.py':app['main.py'].replace(b'report.encode("utf-8")',b'b"wrong"')})),ap,1,'REJECTED_ARTIFACT_BYTES_MISMATCH'


def vectors():
    profile_integrity={'profile_fixture_replacement','profile_metadata_comment','profile_metadata_mode','profile_metadata_timestamp','profile_duplicate_member','profile_extra','profile_noncanonical','profile_artifact_digest'}
    for name,c,p,exitcode,classification in raw_vectors():
        if exitcode==2 and classification is None:
            if name=='profile_toolchain':classification='TOOLCHAIN_UNTRUSTED'
            elif name in profile_integrity:classification='ACCEPTANCE_PROFILE_INTEGRITY_FAILED'
            elif name.startswith('profile_'):classification='ACCEPTANCE_PROFILE_INVALID'
            else:classification='RELEASE_CANDIDATE_INTEGRITY_FAILED'
        yield name,c,p,exitcode,classification


def process_table():
    """PID/parent/birth metadata only; never inspect argv or environments."""
    text=subprocess.check_output(['ps','-axo','pid=,ppid=,lstart='],text=True,timeout=3)
    table={}
    for line in text.splitlines():
        fields=line.split(None,2)
        if len(fields)==3:table[int(fields[0])]=(int(fields[1]),fields[2])
    return table


def stop_trial(proc):
    if os.name=='nt':
        try:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        except (OSError,subprocess.TimeoutExpired):pass
    else:
        try:
            table=process_table();owned={proc.pid};changed=True
            while changed:
                descendants={pid for pid,(parent,_) in table.items() if parent in owned}
                changed=not descendants<=owned;owned|=descendants
            # Capture before killing the root so newly sessionized children remain attributable.
            current=process_table()
            for pid in sorted(owned-{proc.pid},reverse=True):
                if pid in current and current[pid]==table.get(pid):
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
        except (OSError,subprocess.SubprocessError):pass
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    if proc.poll() is None:proc.kill()


def invoke(argv,timeout):
    kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
    proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**kwargs)
    try:
        out,err=proc.communicate(timeout=timeout)
        return proc.returncode,out,err,False
    except subprocess.TimeoutExpired as initial:
        stop_trial(proc)
        try:out,err=proc.communicate(timeout=10)
        except subprocess.TimeoutExpired as cleanup:
            out=cleanup.output or initial.output or b'';err=cleanup.stderr or initial.stderr or b''
            for stream in [proc.stdout,proc.stderr]:
                if stream:stream.close()
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
        return proc.returncode,out,err,True


def golden(c,p,release):
    m,_,_=candidate(c);doc,parts=profile(p);a=m['application'];identity={'candidate_bundle_sha256':sha(c),'candidate_release_candidate_id':m['release_candidate_id'],'profile_bundle_sha256':sha(p),'profile_id':doc['profile_id'],'application_id':a['id'],'acceptor':release};h=sha(canon(identity))
    return {'schema':'capy.independent-application-acceptance/v0','acceptance_id':'acc_'+h[:32],'identity_sha256':h,'identity':identity,'status':'ACCEPTED','classification':'ACCEPTED','source':m['source'],'application':{'archive_sha256':a['archive']['sha256'],'descriptor_sha256':a['descriptor_sha256'],'interaction_sha256':a['interaction']['sha256'],'execution_contract':a['contract'],'interaction_contract':a['interaction']['schema']},'toolchain':m['toolchain'],'cases':[{'case_id':case['case_id'],'matched':True,'classification':'CASE_MATCHED','expected':expected(case,parts),'observed':expected(case,parts)} for case in doc['cases']],'secret_scan':{'status':'PASSED','findings':[]},'cleanup':{'status':'CONFIRMED'},'non_claims':CLAIMS}


def selfcheck():
    release=json.loads((BASE/'release.json').read_bytes());count=0
    for name,c,p,exitcode,classification in vectors():
        if exitcode in (0,1):candidate(c);profile(p);count+=1
    for name in ['greeting','report']:
        c=(BASE/('fixed-v1.capyrc' if name=='greeting' else 'artifact-v1.capyrc')).read_bytes();p=(BASE/(name+'.capya')).read_bytes();doc=golden(c,p,release);validate(c,p,canon(doc),release)
        for mut in [lambda d:d.update(acceptance_id='acc_'+'0'*32),lambda d:d['identity'].update(profile_bundle_sha256='0'*64),lambda d:d['identity']['acceptor'].update(implementation_commit='3'*40),lambda d:d['cases'][0]['observed'].update(result_sha256='0'*64),lambda d:d['cases'][0].update(matched=False,classification='REJECTED_RESULT_MISMATCH'),lambda d:d['toolchain'].update(wheel_sha256='0'*64),lambda d:d['source'].update(tree='0'*40),lambda d:d['non_claims'].pop()]:
            altered=copy.deepcopy(doc);mut(altered)
            try:validate(c,p,canon(altered),release)
            except ValueError:pass
            else:raise AssertionError('oracle accepted a receipt mutation')
    c=(BASE/'fixed-v1.capyrc').read_bytes();p=(BASE/'greeting.capya').read_bytes();doc=golden(c,p,release)
    for mutation in [lambda x:x.update(profile_id='../bad'),lambda x:x['interaction_expectations'].update(operation_id=1),lambda x:x['candidate_requirements'].update(state_required=0),lambda x:x['interaction_expectations']['resource_fields'].append({'slot':'missing','required':True,'min_items':1,'max_items':1})]:
        try:profile(profile_change(p,mutation))
        except ValueError:pass
        else:raise AssertionError('oracle accepted invalid profile')
    rejected=copy.deepcopy(doc);rejected.update(status='REJECTED',schema='capy.independent-application-rejection/v0',classification='REJECTED_RESULT_MISMATCH');rejected['cases'][0].update(matched=False,classification='REJECTED_RESULT_MISMATCH');rejected['cases'][0]['observed']['result_sha256']='0'*64;validate(c,p,canon(rejected),release)
    for mutation in [lambda x:x['cases'][0]['observed'].update(status='invented'),lambda x:x['cases'][0]['observed'].update(result_sha256=3),lambda x:x['cases'][0]['observed'].update(artifacts=[{'raw_path':'/Users/private'}]),lambda x:x.update(secret_scan={'raw_secret':'public-canary'})]:
        altered=copy.deepcopy(rejected);mutation(altered)
        try:validate(c,p,canon(altered),release)
        except ValueError:pass
        else:raise AssertionError('oracle accepted malformed rejection')
    return {'valid_semantic_vectors':count,'receipt_tampers_rejected':20,'invalid_profiles_rejected':4,'vector_count':sum(1 for _ in vectors())}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--python',default='python3');ap.add_argument('--driver',type=Path);ap.add_argument('--out',type=Path);ap.add_argument('--selfcheck',action='store_true');a=ap.parse_args()
    if a.selfcheck:print(json.dumps(selfcheck(),sort_keys=True));return 0
    a.out.mkdir(parents=True,exist_ok=False);release=json.loads((BASE/'release.json').read_bytes());rows=[]
    for name,c,p,exitcode,classification in vectors():
        folder=a.out/name;folder.mkdir();(folder/'candidate.capyrc').write_bytes(c);(folder/'profile.capya').write_bytes(p)
        code,stdout,stderr,timed_out=invoke([a.python,str(a.driver),'--candidate',str(folder/'candidate.capyrc'),'--profile',str(folder/'profile.capya'),'--release',str(BASE/'release.json')],180)
        (folder/'stdout').write_bytes(stdout);(folder/'stderr').write_bytes(stderr);ok=code==exitcode and not timed_out;reason=['TRIAL_TIMEOUT'] if timed_out else []
        try:
            doc=json.loads(stdout)
            if exitcode==2:ok=ok and type(doc) is dict and set(doc)=={'status','code'} and doc['status']=='ERROR' and doc['code']==classification
            else:
                ok=ok and doc.get('classification')==classification
                validate(c,p,canon(doc),release)
        except (ValueError,KeyError,TypeError,zipfile.BadZipFile) as ex:ok=False;reason.append(type(ex).__name__)
        rows.append({'name':name,'passed':ok,'expected_exit':exitcode,'observed_exit':code,'expected_classification':classification,'reason':reason})
        print(json.dumps(rows[-1]),flush=True)
    (a.out/'RESULT.json').write_text(json.dumps({'passed':sum(r['passed'] for r in rows),'total':len(rows),'rows':rows},indent=2)+'\n')
    return 0 if all(r['passed'] for r in rows) else 1

if __name__=='__main__':raise SystemExit(main())
