"""Fail if the three qualification receipts differ in portable product facts."""
import json
from pathlib import Path
import sys

paths=sorted(Path(sys.argv[1]).glob('qualify-*/QUALIFICATION.json'))
if {p.parent.name for p in paths}!={'qualify-ubuntu-latest','qualify-macos-latest','qualify-windows-latest'}:
    raise SystemExit('missing platform receipt')
receipts=[json.loads(p.read_bytes()) for p in paths]
reference=next(r for r in receipts if r['execution_supported'])
for receipt in receipts:
    if not receipt['passed'] or receipt['model_calls']!=0:
        raise SystemExit('failed platform qualification')
    keys=('release','build','portable','rows') if receipt['execution_supported'] else ('release','build')
    for key in keys:
        if receipt[key]!=reference[key]:raise SystemExit('cross-platform mismatch: '+key)
mac=json.loads(next(p for p in paths if p.parent.name=='qualify-macos-latest').read_bytes())
if mac['execution_supported'] or mac['portable']:raise SystemExit('macOS execution must fail closed')
print(json.dumps({'passed':True,'platforms':3,'wheel_sha256':reference['build']['sha256'],
                  'portable_documents':len(reference['portable']),'release':reference['release']},sort_keys=True))
