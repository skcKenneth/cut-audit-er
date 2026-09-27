"""Pin a new finite diagnostic scope without changing the V6 acquisition engine."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from scripts.review_v5 import study as s
from scripts.review_v6 import freeze as predecessor

ROOT = Path(__file__).resolve().parents[2]
SESSION = 'outputs/session_20260927_v7'
CONFIG = 'configs/review_v7_controls.json'
PROTOCOL = 'research/review_v7/PROTOCOL.md'
SCHEMA = 'cut-audit-v7-method-freeze'


def source_names(root):
    prior = s.read(Path(root)/predecessor.SESSION/'freeze.json')
    names = set(prior['files_sha256'])
    names.update([CONFIG, PROTOCOL])
    names.update('scripts/review_v7/'+n+'.py' for n in ('__init__','common','controls','evaluate','run','freeze','same_pool'))
    names.update('tests/'+n for n in ('test_review_v7_controls.py','test_review_v7_freeze.py','test_review_v7_same_pool.py'))
    return sorted(names)


def create(validation, smoke, *, root=ROOT):
    root = Path(root).resolve()
    predecessor.check(root)
    baseline = predecessor.passed_receipt(root, root/SESSION/'baseline_tests/command.json')
    checks = [predecessor.passed_receipt(root, path) for path in (validation, smoke)]
    pins = {name:s.digest(root/name) for name in source_names(root)}
    snapshot = root/SESSION/'source_snapshot'; snapshot.mkdir(parents=True, exist_ok=False)
    for name in pins:
        dest = snapshot/name; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/name, dest)
    s.check_hashes(snapshot, pins)
    archives = {p.name:hashlib.file_digest(p.open('rb'),'sha256').hexdigest() for p in sorted(root.glob('*.zip'))}
    value = {'schema':SCHEMA, 'created_utc':s.utc(), 'files_sha256':pins,
             'snapshot':snapshot.relative_to(root).as_posix(),
             'v6_freeze_sha256':s.digest(root/predecessor.SESSION/'freeze.json'),
             'baseline':baseline, 'validation':checks, 'old_archives_sha256':archives,
             'authorization':'User requested implementation of the V7 constructive-diagnostic proposal',
             'scope':'Four fixed initial decisions; 20 finite reference worlds plus one analytic law; same-pool census301',
             'natural_acquisition':False, 'sealed_test_access':False, 'deployment':False, 'submission':False}
    s.write(root/SESSION/'freeze.json', value)
    return value


def check(root=ROOT):
    root = Path(root).resolve(); value = s.read(root/SESSION/'freeze.json')
    s.require(value.get('schema') == SCHEMA, 'Wrong V7 freeze schema')
    s.require(value['v6_freeze_sha256'] == s.digest(root/predecessor.SESSION/'freeze.json'), 'V6 freeze changed')
    predecessor.check(root)
    s.check_hashes(root, value['files_sha256'])
    s.check_hashes(s.relative(root, value['snapshot']), value['files_sha256'])
    for receipt in [value['baseline'], *value['validation']]:
        s.require(s.digest(s.relative(root, receipt['path'])) == receipt['sha256'], 'Receipt changed')
    return value


def checked_manifest(path, pin):
    path = Path(path)
    s.require(s.digest(path) == pin, 'Manifest hash mismatch')
    value = s.read(path)
    s.require(bool(value.get('files_sha256')), 'Missing payload hash manifest')
    s.check_hashes(path.parent, value['files_sha256'])
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('create','check'))
    parser.add_argument('--validation', type=Path); parser.add_argument('--smoke', type=Path)
    args = parser.parse_args()
    if args.action == 'create':
        s.require(args.validation is not None and args.smoke is not None, 'Validation/smoke required')
        value = create(args.validation, args.smoke)
    else:
        value = check()
    print(json.dumps({'status':'PASS','schema':SCHEMA,'files':len(value['files_sha256'])}))
