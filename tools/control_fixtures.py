"""Synthetic, explicitly resealed negative controls; never Developer verifications.

The accepted Developer candidates are immutable. These derived mutations update
only their mechanical integrity fields to reach semantic/error branches.
"""
import hashlib
import io
import json
import tomllib
import zipfile

NAMES = ['RELEASE-CANDIDATE.json','application/application.zip','application/interaction.json','evidence/verification.json','toolchain/authoring-bundle.zip']
def canon(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(data): return hashlib.sha256(data).hexdigest()
def unpack(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z: return {n:z.read(n) for n in z.namelist()}
def pack(members):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        for name,data in members.items():
            i=zipfile.ZipInfo(name,(1980,1,1,0,0,0));i.create_system=3;i.external_attr=0o100644<<16;z.writestr(i,data)
    return output.getvalue()

def reseal(data, app_change=None, manifest_change=None):
    parts=unpack(data);m=json.loads(parts[NAMES[0]]);v=json.loads(parts[NAMES[3]])
    if app_change:
        app=unpack(parts[NAMES[1]]);app_change(app);parts[NAMES[1]]=pack(app)
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
    parts[NAMES[3]]=canon(v);m['verification']['receipt'].update(sha256=sha(parts[NAMES[3]]),size_bytes=len(parts[NAMES[3]]))
    if manifest_change:manifest_change(m)
    a=m['application'];i=a['interaction'];t=m['toolchain']
    identity={'schema':m['schema'],'project_id':m['project']['project_id'],'application_id':a['id'],'source':m['source'],'application_archive_sha256':a['archive']['sha256'],'application_descriptor_sha256':a['descriptor_sha256'],'interaction':{'schema':i['schema'],'source_sha256':i['source_sha256'],'canonical_sha256':i['sha256'],'operation_id':i['operation_id']},'verification_receipt_sha256':m['verification']['receipt']['sha256'],'toolchain':{'release_binding_commit':t['release_binding_commit'],'authoring_bundle_sha256':t['authoring_bundle']['sha256'],'wheel_sha256':t['wheel_sha256'],'interaction_contract':t['interaction_contract']}}
    m['identity_sha256']=sha(canon(identity));m['release_candidate_id']='rc_'+m['identity_sha256'][:32];parts[NAMES[0]]=canon(m)
    return pack(parts)

def profile_change(data, change):
    parts=unpack(data);document=json.loads(parts['ACCEPTANCE-PROFILE.json']);change(document)
    parts['ACCEPTANCE-PROFILE.json']=canon(document);return pack(parts)

def artifact_controls(data):
    source=unpack(unpack(data)[NAMES[1]])['main.py']
    line=next(line for line in source.splitlines(keepends=True) if b'ctx.artifact(' in line)
    changes={
        'missing':source.replace(line,b'    pass\n'),
        'extra':source.replace(line,line+b'    ctx.artifact("extra.json", b"{}")\n'),
        'wrong_bytes':source.replace(line,b'    ctx.artifact("summary.json", b"{}")\n'),
        'undeclared':source.replace(line,line+b'    import os\n    from pathlib import Path\n    (Path(os.environ["CAPY_OUTPUT_DIR"]) / "undeclared.json").write_bytes(b"{}")\n'),
    }
    for name, replacement in changes.items():
        yield name, reseal(data, app_change=lambda app,replacement=replacement:app.update({'main.py':replacement}))
