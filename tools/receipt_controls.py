"""Independent copied-byte receipt mutations; no product imports or execution."""
import copy
import hashlib
import json


def matrix(oracle, candidate, profile, document, release):
    canonical=lambda value: json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    original=json.loads(document)
    oracle.validate(candidate,profile,document,release)
    changes=[
        ('schema',lambda d:d.update(schema='capy.independent-application-acceptance/v99')),
        ('status',lambda d:d.update(status='REJECTED')),
        ('classification',lambda d:d.update(classification='REJECTED_RESULT_MISMATCH')),
        ('acceptance_id',lambda d:d.update(acceptance_id='acc_'+'0'*32)),
        ('identity_digest',lambda d:d.update(identity_sha256='0'*64)),
        ('candidate_digest',lambda d:d['identity'].update(candidate_bundle_sha256='0'*64)),
        ('profile_digest',lambda d:d['identity'].update(profile_bundle_sha256='0'*64)),
        ('acceptor_commit',lambda d:d['identity']['acceptor'].update(implementation_commit='0'*40)),
        ('source_binding',lambda d:d['source'].update(commit='0'*40)),
        ('toolchain_binding',lambda d:d['toolchain'].update(wheel_sha256='0'*64)),
        ('application_archive',lambda d:d['application'].update(archive_sha256='0'*64)),
        ('nonclaims',lambda d:d['non_claims'].pop()),
        ('cleanup',lambda d:d.update(cleanup={'status':'UNCONFIRMED'})),
        ('secret_scan',lambda d:d['secret_scan'].update(findings=['SECRET_PATTERN'])),
        ('case_missing',lambda d:d['cases'].pop()),
        ('case_order',lambda d:d['cases'].reverse()),
        ('case_identity',lambda d:d['cases'][0].update(case_id='unknown')),
        ('match_boolean_alias',lambda d:d['cases'][0].update(matched=1)),
        ('expected_result',lambda d:d['cases'][0]['expected'].update(result_sha256='0'*64)),
        ('observed_result',lambda d:d['cases'][0]['observed'].update(result_sha256='0'*64)),
        ('artifact_bytes',lambda d:d['cases'][0]['observed']['artifacts'][0].update(sha256='0'*64)),
        ('artifact_boolean_size',lambda d:d['cases'][0]['observed']['artifacts'][0].update(size_bytes=True)),
        ('artifact_float_size',lambda d:d['cases'][0]['observed']['artifacts'][0].update(size_bytes=19.0)),
        ('artifact_unsafe_name',lambda d:d['cases'][0]['observed']['artifacts'][0].update(filename='../unsafe.txt')),
        ('artifact_missing',lambda d:d['cases'][0]['observed']['artifacts'].clear()),
        ('unknown_field',lambda d:d.update(extra=True)),
    ]
    rows=[]
    for name,change in changes:
        value=copy.deepcopy(original);change(value);raw=canonical(value)
        try:oracle.validate(candidate,profile,raw,release)
        except ValueError as error:
            rows.append({'name':name,'rejected':True,'reason':str(error),'document_sha256':hashlib.sha256(raw).hexdigest()})
        else:raise AssertionError('oracle accepted receipt mutation: '+name)
    return {'schema':'capy.acceptor-receipt-tamper-matrix/v0','valid_original':True,
            'document_sha256':hashlib.sha256(document).hexdigest(),'total':len(rows),'rejected':len(rows),'rows':rows}
