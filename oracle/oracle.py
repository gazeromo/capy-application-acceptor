"""Copied-byte oracle revision1: independently approved O1/O2 corrections.
Standard library only; imports no product module. Original experiment oracle
remains immutable under campaigns/independent_application_acceptance_v0/oracle-original."""
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tomllib
import zipfile
from urllib.parse import urlsplit

BASE=Path(__file__).resolve().parent
NAMES=['RELEASE-CANDIDATE.json','application/application.zip','application/interaction.json','evidence/verification.json','toolchain/authoring-bundle.zip']
TRUST={'release_binding_commit':'24b6418c0ee2dada5a08f78ff6752bb43f9d8e16','implementation_commit':'1211861edbb512aaefae8c20b207f590fac34c35','wheel_filename':'capy_script_devkit-0.1.0-py3-none-any.whl','wheel_sha256':'56c9f6c930b21d600a2e8f10da7a3e92f5cfbf1c6d91490d170d1790e5555603','interaction_contract':'capy.application-interaction/dev-v0'}
BUNDLE='12e492ec2dce11b4227d10bdf9385705a60bc12a88fec0073ff48a87b2a57a57'
CLAIMS=json.loads((BASE/'non_claims.json').read_bytes())

def need(value,label):
    if not value:raise ValueError(label)
def canon(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(value):return hashlib.sha256(value).hexdigest()
def keys(value,names):need(type(value) is dict and set(value)==set(names),'closed_object')
def pairs(values):
    d={}
    for k,v in values:need(k not in d,'duplicate_json');d[k]=v
    return d

def finite(v,depth=0):
    need(depth<=32,'json_depth')
    if isinstance(v,dict):
        for k,x in v.items():need(isinstance(k,str),'json_key');finite(x,depth+1)
    elif isinstance(v,list):
        for x in v:finite(x,depth+1)
    elif isinstance(v,str):v.encode('utf8');need('\x00' not in v,'nul')
    else:need(v is None or type(v) in (bool,int,float),'json_type')

def parse(raw):
    v=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite')))
    finite(v);need(canon(v)==raw,'canonical_json');return v

def safe(name):
    need(isinstance(name,str) and name and '\\' not in name and ':' not in name,'unsafe_path')
    for part in name.split('/'):
        need(bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',part)) and not part.endswith('.'),'unsafe_segment')
        need(part.split('.')[0].upper() not in ['CON','PRN','AUX','NUL']+[f'{p}{i}' for p in ['COM','LPT'] for i in range(1,10)],'device_name')

def safe_source(name):
    need(isinstance(name,str) and name and "\\" not in name and ":" not in name,'unsafe_source')
    for part in name.split('/'):
        need(bool(re.fullmatch(r'[A-Za-z0-9._-]{1,128}',part)) and part not in ['.','..'] and not part.endswith('.'),'unsafe_source_segment')
        need(part.casefold() not in ['.git','.hg','.svn'],'source_control_path')
        need(part.split('.')[0].upper() not in ['CON','PRN','AUX','NUL']+[f'{p}{i}' for p in ['COM','LPT'] for i in range(1,10)],'source_device_name')

def pack(members):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for n,b in members.items():
            info=zipfile.ZipInfo(n,(1980,1,1,0,0,0));info.create_system=3;info.external_attr=0o100644<<16;info.compress_type=0;z.writestr(info,b)
    return stream.getvalue()

def unpack(raw,canonical=False,maximum=64*1024*1024,source_paths=False):
    need(len(raw)<=maximum,'zip_size');members={};folded=set()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist();need(len(infos)<=2048 and sum(i.file_size for i in infos)<=64*1024*1024,'expanded_bound')
        for i in infos:
            (safe_source if source_paths else safe)(i.filename);need(i.filename.casefold() not in folded,'duplicate_path');folded.add(i.filename.casefold())
            need(not i.is_dir() and not (i.flag_bits&1) and ((i.external_attr>>16)&0o170000) in (0,0o100000),'unsafe_member')
            members[i.filename]=z.read(i)
    if canonical:need(pack(members)==raw,'canonical_zip')
    return members

def shape(value,example):
    if type(example) is dict:
        keys(value,example)
        for k in example:shape(value[k],example[k])
    elif type(example) is list:
        need(type(value) is list,'array')
        if example:
            need(len(value)==len(example),'array_shape')
            for x,y in zip(value,example):shape(x,y)
    elif example is None:need(value is None,'null')
    else:need(type(value) is type(example),'scalar_type')

def text(value,maximum=4000):
    need(type(value) is str and 0<len(value)<=maximum and value.strip()==value and '\x00' not in value,'plain_text')

def scalar_ok(value,schema):
    typ=schema['type']
    valid=(type(value) is str if typ=='string' else type(value) is bool if typ=='boolean' else type(value) is int if typ=='integer' else type(value) in (int,float))
    if not valid:return False
    if 'enum' in schema and not any(type(value) is type(x) and value==x for x in schema['enum']):return False
    if typ in ('integer','number') and any((value<schema[k] if k=='minimum' else value>schema[k]) for k in ['minimum','maximum'] if k in schema):return False
    if typ=='string' and any((len(value)<schema[k] if k=='minLength' else len(value)>schema[k]) for k in ['minLength','maxLength'] if k in schema):return False
    return True

def leaves(schema,prefix='',required=True,result=False):
    need(type(schema) is dict and schema.get('type') in ['object','string','boolean','integer','number','array'],'schema_type')
    typ=schema['type']
    if typ=='object':
        need(set(schema)<=set(['type','properties','required','additionalProperties']) and schema.get('additionalProperties') is False,'closed_schema')
        props=schema.get('properties',{});req=schema.get('required',[]);need(type(props) is dict and type(req) is list and len(set(req))==len(req) and all(x in props for x in req),'schema_required')
        out={}
        for key,sub in props.items():
            identifier(key);need('.' not in key,'schema_property');out.update(leaves(sub,(prefix+'.' if prefix else '')+key,required and key in req,result))
        return out
    if typ=='array':
        need(result and prefix=='artifact_filenames' and set(schema)=={'type','items'} and type(schema['items']) is dict and set(schema['items'])=={'type','enum'} and schema['items']['type']=='string','schema_array')
        strings(schema['items']['enum']);return {}
    allowed={'type','enum','minimum','maximum'} if typ in ['integer','number'] else {'type','enum','minLength','maxLength'} if typ=='string' else {'type','enum'}
    need(set(schema)<=allowed,'scalar_schema')
    if 'enum' in schema:need(type(schema['enum']) is list and schema['enum'] and all(scalar_ok(x,{k:v for k,v in schema.items() if k!='enum'}) for x in schema['enum']),'schema_enum')
    return {prefix:(schema,required)}

def interaction_check(d,i,members):
    keys(d,['schema','id','name','description','entrypoint','side_effect','timeout_seconds','memory_mb','state_required','resources','connections','input_schema','result_schema'])
    identifier(d['id']);need('.' in d['id'] and type(d['state_required']) is bool and d['state_required'] is False and d['connections']==[] and d['side_effect'] in ['read_only','artifact_generation'],'descriptor_support')
    need(type(d['timeout_seconds']) is int and d['timeout_seconds']>0 and type(d['memory_mb']) is int and d['memory_mb']>0,'descriptor_limits')
    text(d['name']);text(d['description']);safe_source(d['entrypoint']);need(d['entrypoint'].endswith('.py') and d['entrypoint'] in members,'python_entrypoint')
    inputs=leaves(d['input_schema']);results=leaves(d['result_schema'],result=True)
    keys(i,['schema','application_id','title','purpose','not_for','operation','boundaries']);text(i['title']);text(i['purpose']);strings(i['not_for']);need(i['not_for'],'not_for')
    op=i['operation'];keys(op,['operation_id','title','user_outcome','description','request_fields','resource_fields','examples','common_misunderstandings','result']);identifier(op['operation_id'])
    for k in ['title','user_outcome','description']:text(op[k])
    strings(op['examples']);strings(op['common_misunderstandings']);need(type(op['request_fields']) is list and type(op['resource_fields']) is list,'fields')
    seen=set()
    for f in op['request_fields']:
        keys(f,['field_id','label','description','required','input_kind','safe_default','examples','clarification_question']);fid=f['field_id'];need(fid in inputs and fid not in seen,'input_coverage');seen.add(fid);schema,required=inputs[fid]
        need(type(f['required']) is bool and f['required']==required,'input_required')
        kinds=['choice'] if schema['type']=='string' and 'enum' in schema else ['text','long_text'] if schema['type']=='string' else ['boolean'] if schema['type']=='boolean' else ['number']
        need(f['input_kind'] in kinds and (f['safe_default'] is None or not required and scalar_ok(f['safe_default'],schema)),'input_kind_default')
        for k in ['label','description','clarification_question']:text(f[k])
        strings(f['examples'],16)
    need(seen==set(inputs),'input_coverage')
    slots={};need(type(d['resources']) is list,'descriptor_resources')
    for r in d['resources']:
        keys(r,['name','required','min_items','max_items']);identifier(r['name']);need(r['name'] not in slots and type(r['required']) is bool and type(r['min_items']) is int and type(r['max_items']) is int and 0<=r['min_items']<=r['max_items']<=16 and (not r['required'] or r['min_items']>0),'descriptor_resource');slots[r['name']]=r
    seen=set()
    for f in op['resource_fields']:
        keys(f,['slot','label','description','required','minimum_count','maximum_count','input_kind','examples','clarification_question']);need(f['slot'] in slots and f['slot'] not in seen,'resource_coverage');seen.add(f['slot']);r=slots[f['slot']]
        need(type(f['required']) is bool and type(f['minimum_count']) is int and type(f['maximum_count']) is int and f['required']==r['required'] and f['minimum_count']==r['min_items'] and f['maximum_count']==r['max_items'] and f['input_kind']=='file','resource_binding')
        for k in ['label','description','clarification_question']:text(f[k])
        strings(f['examples'])
    need(seen==set(slots),'resource_coverage')
    result=op['result'];keys(result,['presentation','facts','artifacts']);need(type(result['facts']) is list and type(result['artifacts']) is list,'result_lists');seen=set()
    for f in result['facts']:
        keys(f,['path','label']);need(f['path'] in results and f['path'] not in seen,'result_fact');seen.add(f['path']);text(f['label'])
    names=[]
    for a in result['artifacts']:
        keys(a,['filename','label']);safe(a['filename']);need('/' not in a['filename'],'artifact_name');names.append(a['filename']);text(a['label'])
    need(len(set(n.casefold() for n in names))==len(names),'artifact_duplicates')
    if d['side_effect']=='read_only':need(names==[] and result['presentation']=='facts','readonly_artifacts')
    else:need(names and set(names)==set(d['result_schema']['properties']['artifact_filenames']['items']['enum']) and result['presentation']=='artifact_result','artifact_binding')
    need(type(i['boundaries']) is list and 1<=len(i['boundaries'])<=64,'boundaries');seen=set()
    for b in i['boundaries']:
        keys(b,['boundary_id','request_class','explanation','nearest_operation_ids']);identifier(b['boundary_id']);need(b['boundary_id'] not in seen and b['nearest_operation_ids']==[op['operation_id']],'boundary');seen.add(b['boundary_id']);text(b['request_class']);text(b['explanation'])


def candidate(raw):
    parts=unpack(raw,True);need(list(parts)==NAMES,'candidate_members')
    m=parse(parts[NAMES[0]]);v=parse(parts[NAMES[3]])
    template=json.loads((BASE/'manifest_shape.json').read_bytes());verification_template=json.loads((BASE/'verification_shape.json').read_bytes())
    # Remote identity is allowed; shape alone must not force the local null example.
    remote=m.get('source',{}).get('repository',{}).get('kind')=='remote'
    if remote:template['source']['repository']['public_identity']='git://public'
    shape(m,template);shape(v,verification_template)
    need(m['schema']==template['schema'] and v['schema']==verification_template['schema'] and v['pipeline']==verification_template['pipeline'],'schema')
    need(m['handoff']==template['handoff'],'handoff')
    for obj,fields,pattern in [(m['source'],['commit','tree','base_commit'],r'[0-9a-f]{40}'),(m,['identity_sha256'],r'[0-9a-f]{64}')]:
        for k in fields:need(bool(re.fullmatch(pattern,obj[k])),'identity_syntax')
    for val,prefix in [(m['project']['project_id'],'prj_'),(m['verification']['verification_id'],'ver_'),(v['session_id'],'ses_')]:need(bool(re.fullmatch(prefix+r'[0-9a-f]{32}',val)),'id_syntax')
    a=m['application'];t=m['toolchain'];interaction=a['interaction']
    for binding,name in [(a['archive'],NAMES[1]),(interaction,NAMES[2]),(m['verification']['receipt'],NAMES[3]),(t['authoring_bundle'],NAMES[4])]:
        need(binding['member']==name and binding['sha256']==sha(parts[name]) and type(binding['size_bytes']) is int and binding['size_bytes']==len(parts[name]),'member_binding')
    need(all(t[k]==x for k,x in TRUST.items()) and sha(parts[NAMES[4]])==BUNDLE,'trusted_toolchain')
    app=unpack(parts[NAMES[1]],source_paths=True);d=tomllib.loads(app['capability.toml'].decode());i=parse(parts[NAMES[2]])
    need(d['schema']==a['contract']=='capy.script/dev-v0' and d['id']==a['id']==i['application_id']==v['application_id'],'application_binding')
    need(sha(app['capability.toml'])==a['descriptor_sha256'],'descriptor_binding')
    need(len(app['interaction.json'])<=65536,'interaction_size');interaction_check(d,i,app)
    need(canon(json.loads(app['interaction.json'],object_pairs_hook=pairs))==parts[NAMES[2]],'interaction_source')
    need(interaction['source_member']=='interaction.json' and interaction['source_sha256']==sha(app['interaction.json']) and interaction['schema']==i['schema']==TRUST['interaction_contract'] and interaction['operation_id']==i['operation']['operation_id'],'interaction_binding')
    safe_source(d['entrypoint']);need(d['entrypoint'] in app,'entrypoint')
    need(v['status']=='PASSED' and v['classification']=='VERIFIED','verification_status')
    need(v['project_id']==m['project']['project_id'] and v['verification_id']==m['verification']['verification_id'] and v['source']=={k:m['source'][k] for k in ('commit','tree','base_commit')},'verification_identity')
    need(v['verified_at']==m['verified_at'] and m['verified_at'].endswith('Z'),'time_binding')
    need(v['application_archive']=={k:a['archive'][k] for k in ['sha256','size_bytes']},'verification_archive')
    expected_i={'schema':interaction['schema'],'source_member':'interaction.json','source_sha256':interaction['source_sha256'],'canonical_sha256':interaction['sha256'],'canonical_size_bytes':interaction['size_bytes'],'operation_id':interaction['operation_id']}
    need(v['interaction_contract']==expected_i,'verification_interaction')
    need(v['toolchain']=={'contract':a['contract'],'lock_digest':v['toolchain']['lock_digest'],'authoring_bundle_sha256':BUNDLE,**TRUST},'verification_toolchain')
    for stage,example in zip(v['stages'],verification_template['stages']):
        need(stage['name']==example['name'] and stage['status']=='PASSED' and stage['exit_code']==example['exit_code'],'verification_stage')
        for k,x in stage['facts'].items():
            if type(x) is bool:need(x==example['facts'][k],'verification_fact')
        for k in ['stored_stdout_bytes','stored_stderr_bytes','stdout_truncated_bytes','stderr_truncated_bytes']:need(stage[k]>=0,'counter')
    facts={x['name']:x['facts'] for x in v['stages']}
    need(facts['archive_preserve']==v['application_archive'],'preservation')
    need(facts['package_compare']=={'sha256_a':a['archive']['sha256'],'sha256_b':a['archive']['sha256'],'size_a':a['archive']['size_bytes'],'size_b':a['archive']['size_bytes']},'package_comparison')
    need(facts['interaction_preserve']=={'candidate_unchanged':True,'timed_out':False,'source_sha256':interaction['source_sha256'],'canonical_sha256':interaction['sha256'],'canonical_size_bytes':interaction['size_bytes']},'interaction_preserve')
    repository=m['source']['repository'];need(bool(re.fullmatch(r'[0-9a-f]{64}',repository['identity_sha256'])),'repository_hash')
    if remote:
        public=repository['public_identity'];uri=urlsplit(public)
        need(public.startswith('git://') and not any(ord(ch)<=32 or ord(ch)==127 for ch in public) and uri.hostname and uri.username is None and uri.password is None and not uri.query and not uri.fragment,'repository_identity')
        need(bool(re.fullmatch(r'[A-Za-z0-9.-]+(?::[0-9]{1,5})?',uri.netloc)) and uri.path.startswith('/') and (uri.port is None or 1<=uri.port<=65535),'repository_address')
        need(all(re.fullmatch(r'[A-Za-z0-9._~-]+',part) and part not in ('.','..') for part in uri.path[1:].split('/')),'repository_path')
        need(sha(public.encode())==repository['identity_sha256'],'repository_hash')
    else:need(repository['kind']=='local' and repository['public_identity'] is None,'local_repository')
    identity={'schema':m['schema'],'project_id':m['project']['project_id'],'application_id':a['id'],'source':m['source'],'application_archive_sha256':a['archive']['sha256'],'application_descriptor_sha256':a['descriptor_sha256'],'interaction':{'schema':interaction['schema'],'source_sha256':interaction['source_sha256'],'canonical_sha256':interaction['sha256'],'operation_id':interaction['operation_id']},'verification_receipt_sha256':m['verification']['receipt']['sha256'],'toolchain':{'release_binding_commit':t['release_binding_commit'],'authoring_bundle_sha256':BUNDLE,'wheel_sha256':t['wheel_sha256'],'interaction_contract':t['interaction_contract']}}
    need(m['identity_sha256']==sha(canon(identity)) and m['release_candidate_id']=='rc_'+m['identity_sha256'][:32],'candidate_identity')
    bundle=unpack(parts[NAMES[4]]);need(sha(bundle['wheel/'+t['wheel_filename']])==t['wheel_sha256'],'wheel_integrity')
    return m,d,i

def identifier(value):
    need(type(value) is str and bool(re.fullmatch(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*',value)) and len(value)<=128,'identifier')

def strings(values,maximum=64):
    need(type(values) is list and len(values)<=maximum,'string_list')
    need(all(type(v) is str and 0<len(v)<=4000 and v.strip()==v for v in values),'string_value')
    need(len(values)==len(set(values)),'duplicate_string')

def expectations(ie):
    keys(ie,['purpose','operation_id','not_for','request_fields','resource_fields','result_fact_paths','artifact_filenames','boundaries'])
    need(ie['purpose'] is None or type(ie['purpose']) is str and 0<len(ie['purpose'])<=4000,'purpose')
    identifier(ie['operation_id']);strings(ie['not_for']);strings(ie['result_fact_paths']);strings(ie['artifact_filenames'])
    for path in ie['result_fact_paths']:identifier(path)
    for name in ie['artifact_filenames']:safe(name);need('/' not in name,'artifact_basename')
    need(len(set(n.casefold() for n in ie['artifact_filenames']))==len(ie['artifact_filenames']),'artifact_alias')
    fields=set();slots={};boundaries=set()
    for name in ['request_fields','resource_fields','boundaries']:need(type(ie[name]) is list and len(ie[name])<=64,'expectation_list')
    for f in ie['request_fields']:
        keys(f,['field_id','required']);identifier(f['field_id']);need(type(f['required']) is bool and f['field_id'] not in fields,'request_field');fields.add(f['field_id'])
    for f in ie['resource_fields']:
        keys(f,['slot','required','min_items','max_items']);identifier(f['slot']);need(f['slot'] not in slots and type(f['required']) is bool,'resource_slot')
        need(type(f['min_items']) is int and type(f['max_items']) is int and 0<=f['min_items']<=f['max_items']<=16 and (not f['required'] or f['min_items']>0),'resource_bounds');slots[f['slot']]=f
    for b in ie['boundaries']:
        keys(b,['boundary_id','nearest_operation_ids']);identifier(b['boundary_id']);strings(b['nearest_operation_ids']);need(b['boundary_id'] not in boundaries and b['nearest_operation_ids']==[ie['operation_id']],'boundary');boundaries.add(b['boundary_id'])
    return slots


def profile(raw):
    parts=unpack(raw,True,32*1024*1024);p=parse(parts['ACCEPTANCE-PROFILE.json'])
    keys(p,['schema','profile_id','application_id','candidate_requirements','interaction_expectations','cases','limits','non_goals'])
    need(p['schema']=='capy.application-acceptance-profile/v0' and p['non_goals']==CLAIMS,'profile_identity')
    identifier(p['application_id']);need('.' in p['application_id'],'application_identifier')
    pid=p['profile_id'];need(type(pid) is str and bool(re.fullmatch(r'[a-z][a-z0-9._/-]{0,127}',pid)) and all(x not in ['', '.', '..'] for x in pid.split('/')),'profile_id')
    r=p['candidate_requirements'];keys(r,['release_candidate_schema','execution_contract','interaction_contract','toolchain_release_binding_commit','toolchain_wheel_sha256','toolchain_authoring_bundle_sha256','side_effect','state_required','connections'])
    need(type(r['state_required']) is bool,'state_type')
    need(r=={'release_candidate_schema':'capy.application-release-candidate/v1','execution_contract':'capy.script/dev-v0','interaction_contract':TRUST['interaction_contract'],'toolchain_release_binding_commit':TRUST['release_binding_commit'],'toolchain_wheel_sha256':TRUST['wheel_sha256'],'toolchain_authoring_bundle_sha256':BUNDLE,'side_effect':r['side_effect'],'state_required':False,'connections':[]} and r['side_effect'] in ['read_only','artifact_generation'],'profile_support')
    ie=p['interaction_expectations'];declared_slots=expectations(ie)
    ceilings={'max_cases':32,'max_resources_per_case':16,'max_fixture_bytes':8388608,'max_expected_artifact_bytes':8388608,'max_request_bytes':65536,'timeout_seconds':30,'max_stdout_bytes':1048576,'max_stderr_bytes':1048576,'max_total_artifact_bytes':8388608};keys(p['limits'],ceilings)
    need(all(type(p['limits'][k]) is int and 0<p['limits'][k]<=v for k,v in ceilings.items()),'profile_limits')
    cases=p['cases'];need(type(cases) is list and 2<=len(cases)<=p['limits']['max_cases'],'case_count')
    seen=set();referenced=[];counts={'fixtures':0,'expected':0};statuses=set()
    for c in cases:
        keys(c,['case_id','request','resources','expect']);cid=c['case_id'];need(isinstance(cid,str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',cid) and cid not in seen,'case_id');seen.add(cid)
        need(type(c['request']) is dict and len(canon(c['request']))<=p['limits']['max_request_bytes'],'request')
        need(type(c['resources']) is list and len(c['resources'])<=p['limits']['max_resources_per_case'],'resources')
        ex=c['expect'];keys(ex,['status','result','artifacts','failure_code']);statuses.add(ex['status'])
        if ex['status']=='ok':need(type(ex['result']) is dict and ex['failure_code'] is None,'ok_expect')
        else:need(ex['status']=='failed' and ex['result'] is None and ex['artifacts']==[] and bool(re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',ex['failure_code'])),'failed_expect')
        need(type(ex['artifacts']) is list,'artifact_list')
        if ex['status']=='ok':need(sorted(x['filename'] for x in ex['artifacts'])==sorted(ie['artifact_filenames']),'expected_artifact_declarations')
        for slot,f in declared_slots.items():
            actual=sum(1 for x in c['resources'] if x.get('slot')==slot);need(f['min_items']<=actual<=f['max_items'],'resource_counts')
        for kind,entries in [('fixtures',c['resources']),('expected',ex['artifacts'])]:
            slots=set();names=set()
            for e in entries:
                keys(e,['slot','filename','member','sha256'] if kind=='fixtures' else ['filename','member','sha256'])
                safe(e['filename']);need('/' not in e['filename'] and e['filename'].casefold() not in names,'file_alias');names.add(e['filename'].casefold())
                if kind=='fixtures':need(e['slot'] in declared_slots and e['slot'] not in slots,'duplicate_or_unknown_slot');slots.add(e['slot'])
                name=kind+'/'+cid+'/'+e['filename'];need(e['member']==name and name in parts and sha(parts[name])==e['sha256'],'profile_member')
                referenced.append(name);counts[kind]+=len(parts[name])
    need(statuses=={'ok','failed'},'positive_and_negative')
    need(counts['fixtures']<=p['limits']['max_fixture_bytes'] and counts['expected']<=p['limits']['max_expected_artifact_bytes'],'profile_byte_limit')
    need(len(referenced)==len(set(referenced)) and list(parts)==['ACCEPTANCE-PROFILE.json']+sorted(n for n in referenced if n.startswith('fixtures/'))+sorted(n for n in referenced if n.startswith('expected/')),'profile_members')
    return p,parts

def expected(case,parts):
    x=case['expect']
    return {'status':x['status'],'result_sha256':sha(canon(x['result'])) if x['status']=='ok' else None,'failure_code':x['failure_code'],'artifacts':sorted([{'filename':a['filename'],'sha256':a['sha256'],'size_bytes':len(parts[a['member']])} for a in x['artifacts']],key=lambda a:a['filename'])}

def pairing(profile,descriptor,interaction):
    wanted=profile['interaction_expectations'];operation=interaction['operation']
    checks=[profile['candidate_requirements']['side_effect']==descriptor['side_effect'],wanted['operation_id']==operation['operation_id'],
            wanted['purpose'] is None or wanted['purpose']==interaction['purpose'],set(wanted['not_for'])<=set(interaction['not_for'])]
    requested=[{k:f[k] for k in ('field_id','required')} for f in operation['request_fields']]
    resources=[{'slot':f['slot'],'required':f['required'],'min_items':f['minimum_count'],'max_items':f['maximum_count']} for f in operation['resource_fields']]
    checks.extend([canon(requested)==canon(wanted['request_fields']),canon(resources)==canon(wanted['resource_fields']),
                   [f['path'] for f in operation['result']['facts']]==wanted['result_fact_paths'],
                   [f['filename'] for f in operation['result']['artifacts']]==wanted['artifact_filenames']])
    boundaries={b['boundary_id']:b['nearest_operation_ids'] for b in interaction['boundaries']}
    checks.extend(boundaries.get(b['boundary_id'])==b['nearest_operation_ids'] for b in wanted['boundaries'])
    return all(checks)

def validate(candidate_bytes,profile_bytes,document_bytes,release):
    m,d,i=candidate(candidate_bytes);p,parts=profile(profile_bytes);doc=parse(document_bytes)
    keys(release,['contract','version','implementation_commit','implementation_tree'])
    need(release['contract']=='capy.independent-application-acceptance/v0' and release['version']=='0.1.0' and all(type(release[k]) is str and re.fullmatch(r'[0-9a-f]{40}',release[k]) for k in ['implementation_commit','implementation_tree']),'acceptor_release')
    keys(doc,['schema','acceptance_id','identity_sha256','identity','status','classification','source','application','toolchain','cases','secret_scan','cleanup','non_claims'])
    identity={'candidate_bundle_sha256':sha(candidate_bytes),'candidate_release_candidate_id':m['release_candidate_id'],'profile_bundle_sha256':sha(profile_bytes),'profile_id':p['profile_id'],'application_id':m['application']['id'],'acceptor':release}
    need(canon(doc['identity'])==canon(identity) and p['application_id']==m['application']['id'],'acceptance_binding')
    h=sha(canon(identity));need(doc['identity_sha256']==h and doc['acceptance_id']=='acc_'+h[:32],'acceptance_identity')
    a=m['application'];need(canon(doc['source'])==canon(m['source']) and canon(doc['toolchain'])==canon(m['toolchain']),'portable_binding')
    need(doc['application']=={'archive_sha256':a['archive']['sha256'],'descriptor_sha256':a['descriptor_sha256'],'interaction_sha256':a['interaction']['sha256'],'execution_contract':a['contract'],'interaction_contract':a['interaction']['schema']},'application_projection')
    need(doc['non_claims']==CLAIMS and doc['cleanup']=={'status':'CONFIRMED'},'nonclaims_cleanup')
    need(doc['status'] in ['ACCEPTED','REJECTED'],'status')
    keys(doc['secret_scan'],['status','findings']);need(doc['secret_scan'] in [{'status':'PASSED','findings':[]},{'status':'REJECTED','findings':['SECRET_PATTERN']}],'secret_scan')
    need(type(doc['cases']) is list and type(doc['classification']) is str,'report_types')
    early=doc['classification'] in ['REJECTED_SECRET_BOUNDARY','REJECTED_INTERACTION_MISMATCH'] and not doc['cases']
    compatible=pairing(p,d,i)
    if doc['status']=='ACCEPTED':need(compatible,'interaction_pairing')
    if doc['classification']=='REJECTED_INTERACTION_MISMATCH':need(not compatible,'interaction_rejection_cause')
    if not early:need(len(doc['cases'])==len(p['cases']),'case_coverage')
    for row,case in zip(doc['cases'],p['cases']):
        keys(row,['case_id','matched','classification','expected','observed']);need(row['case_id']==case['case_id'] and canon(row['expected'])==canon(expected(case,parts)),'case_expected')
        keys(row['observed'],['status','result_sha256','artifacts','failure_code'])
        observation=row['observed'];need(observation['status'] in ['ok','failed','error'],'observed_status')
        if observation['status']=='ok':need(type(observation['result_sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',observation['result_sha256']) and observation['failure_code'] is None,'observed_ok')
        else:need(observation['result_sha256'] is None,'observed_null_result')
        if observation['status']=='failed':need(type(observation['failure_code']) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',observation['failure_code']),'observed_failure')
        elif observation['status']=='error':need(observation['failure_code'] is None,'observed_error')
        need(type(observation['artifacts']) is list and len(observation['artifacts'])<=1024,'observed_artifacts');names=[]
        for artifact in observation['artifacts']:
            keys(artifact,['filename','sha256','size_bytes']);safe(artifact['filename']);need('/' not in artifact['filename'],'observed_artifact_name');names.append(artifact['filename'])
            need(type(artifact['size_bytes']) is int and 0<=artifact['size_bytes']<=8388608 and type(artifact['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}',artifact['sha256']),'observed_artifact_integrity')
        need(names==sorted(names) and len(set(n.casefold() for n in names))==len(names),'observed_artifact_set')
        need(type(row['matched']) is bool,'case_match_type')
        if row['matched']:need(canon(row['observed'])==canon(row['expected']) and row['classification']=='CASE_MATCHED','forged_case_match')
        else:
            need(row['classification'] in ['REJECTED_SECRET_BOUNDARY','REJECTED_CASE_TIMEOUT','REJECTED_OUTPUT_LIMIT','REJECTED_APPLICATION_EXIT','REJECTED_FAILURE_CODE_MISMATCH','REJECTED_RESULT_MISMATCH','REJECTED_ARTIFACT_SET_MISMATCH','REJECTED_ARTIFACT_BYTES_MISMATCH'],'causal_case')
            need(canon(row['observed'])!=canon(row['expected']) or row['classification'] in ['REJECTED_SECRET_BOUNDARY','REJECTED_OUTPUT_LIMIT','REJECTED_APPLICATION_EXIT','REJECTED_ARTIFACT_SET_MISMATCH'],'false_mismatch')
    secret_failure=doc['classification']=='REJECTED_SECRET_BOUNDARY' or any(x['classification']=='REJECTED_SECRET_BOUNDARY' for x in doc['cases'])
    need((doc['secret_scan']['status']=='REJECTED')==secret_failure,'secret_scan_causality')
    if doc['status']=='ACCEPTED':
        need(doc['schema']=='capy.independent-application-acceptance/v0' and doc['classification']=='ACCEPTED' and doc['cases'] and all(x['matched'] for x in doc['cases']) and doc['secret_scan']=={'status':'PASSED','findings':[]},'forged_acceptance')
    else:
        need(doc['schema']=='capy.independent-application-rejection/v0' and (early or any(not x['matched'] for x in doc['cases'])),'rejection')
        if not early:need(doc['classification']==next(x['classification'] for x in doc['cases'] if not x['matched']),'first_cause')
    return True

if __name__=='__main__':
    try:
        validate(Path(sys.argv[1]).read_bytes(),Path(sys.argv[2]).read_bytes(),Path(sys.argv[3]).read_bytes(),json.loads(Path(sys.argv[4]).read_bytes()))
        print('ORACLE_VALID')
    except (ValueError,KeyError,TypeError,OSError,zipfile.BadZipFile) as ex:
        print('ORACLE_INVALID:'+type(ex).__name__);raise SystemExit(1)
