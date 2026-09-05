"""Frozen black-box campaign entrypoint for the contributor-owned core."""
import argparse
import json
from pathlib import Path
import tempfile
from capy_application_acceptor.candidate import read_candidate
from capy_application_acceptor.profile import read_profile
from capy_application_acceptor.acceptance import evaluate
from capy_application_acceptor.errors import AcceptorError


def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--profile',type=Path,required=True);p.add_argument('--release',type=Path,required=True)
    args=p.parse_args()
    try:
        candidate=read_candidate(args.candidate.read_bytes());profile=read_profile(args.profile.read_bytes())
        release=json.loads(args.release.read_bytes())
        with tempfile.TemporaryDirectory(prefix='capy-core-driver-') as temp:
            result=evaluate(candidate,profile,release,Path(temp))
            if list(Path(temp).iterdir()):
                raise AcceptorError('CLEANUP_FAILED')
        print(json.dumps(result.document,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False))
        return 0 if result.status=='ACCEPTED' else 1
    except AcceptorError as ex:
        print(json.dumps({'status':'ERROR','code':ex.code},sort_keys=True,separators=(',',':')))
        return 2


if __name__=='__main__':raise SystemExit(main())
