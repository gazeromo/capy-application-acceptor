"""Public fixture construction only. No product modules or validators imported."""
import hashlib
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures'
RELEASE = {'contract':'capy.independent-application-acceptance/v0','version':'0.1.0',
           'implementation_commit':'1'*40,'implementation_tree':'2'*40}

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()

def digest(data):return hashlib.sha256(data).hexdigest()

def archive(members, comment=b''):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        z.comment=comment
        for name,data in members.items():
            item=zipfile.ZipInfo(name,(1980,1,1,0,0,0));item.create_system=3
            item.external_attr=0o100644<<16;item.compress_type=zipfile.ZIP_STORED
            z.writestr(item,data)
    return output.getvalue()

def unpack(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:return {n:z.read(n) for n in z.namelist()}

def profile_document(artifact=False):
    """Expectations for already accepted public test-owned greeting/report vectors."""
    if artifact:
        app='demo.text_report';operation='text_report.create'
        purpose='Create one deterministic plain-text report from supplied text.'
        not_for=['publishing, sending, or storing the report outside the returned artifact']
        fields=[{'field_id':'text','required':True},{'field_id':'heading','required':False}]
        facts=['character_count'];files=['text-report.txt'];boundary='text_report.publish'
        cases=[{'case_id':'normal','request':{'text':'Hello','heading':'Brief'},'resources':[],
                'expect':{'status':'ok','result':{'character_count':5,'artifact_filenames':['text-report.txt']},
                          'artifacts':[{'filename':'text-report.txt','member':'expected/normal/text-report.txt','sha256':digest(b'Brief\n=====\n\nHello\n')}],'failure_code':None}},
               {'case_id':'invalid','request':{'text':''},'resources':[],
                'expect':{'status':'failed','result':None,'artifacts':[],'failure_code':'TEXT_REQUIRED'}}]
    else:
        app='demo.interaction_fixture';operation='hello.show';purpose='Return one deterministic greeting.'
        not_for=['sending messages or changing external state'];fields=[];facts=['message'];files=[];boundary='hello.send'
        cases=[{'case_id':'normal','request':{},'resources':[],
                'expect':{'status':'ok','result':{'message':'hello'},'artifacts':[],'failure_code':None}},
               {'case_id':'invalid','request':{'unexpected':True},'resources':[],
                'expect':{'status':'failed','result':None,'artifacts':[],'failure_code':'REQUEST_INVALID'}}]
    return {'schema':'capy.application-acceptance-profile/v0','profile_id':'public-report/v0' if artifact else 'public-greeting/v0',
            'application_id':app,'candidate_requirements':{
             'release_candidate_schema':'capy.application-release-candidate/v1','execution_contract':'capy.script/dev-v0',
             'interaction_contract':'capy.application-interaction/dev-v0',
             'toolchain_release_binding_commit':'24b6418c0ee2dada5a08f78ff6752bb43f9d8e16',
             'toolchain_wheel_sha256':'56c9f6c930b21d600a2e8f10da7a3e92f5cfbf1c6d91490d170d1790e5555603',
             'toolchain_authoring_bundle_sha256':'12e492ec2dce11b4227d10bdf9385705a60bc12a88fec0073ff48a87b2a57a57',
             'side_effect':'artifact_generation' if artifact else 'read_only','state_required':False,'connections':[]},
            'interaction_expectations':{'purpose':purpose,'operation_id':operation,'not_for':not_for,
             'request_fields':fields,'resource_fields':[],'result_fact_paths':facts,'artifact_filenames':files,
             'boundaries':[{'boundary_id':boundary,'nearest_operation_ids':[operation]}]},
            'cases':cases,'limits':{'max_cases':8,'max_resources_per_case':4,'max_fixture_bytes':1048576,
             'max_expected_artifact_bytes':1048576,'max_request_bytes':65536,'timeout_seconds':5,
             'max_stdout_bytes':65536,'max_stderr_bytes':65536,'max_total_artifact_bytes':1048576},
            'non_goals':json.loads((ROOT/'spec/V0-NON-CLAIMS.json').read_text())}

def profile_bytes(document=None,artifact=False):
    doc=profile_document(artifact) if document is None else document
    members={'ACCEPTANCE-PROFILE.json':canonical(doc)}
    if artifact:members['expected/normal/text-report.txt']=b'Brief\n=====\n\nHello\n'
    return archive(members)
