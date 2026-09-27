"""Pin the authorized V6 method/audit protocol without changing V5 or test gates."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.review_v5 import study as s

SESSION = 'outputs/session_20260927_v6'
PROTOCOL = 'research/review_v6/PROTOCOL.md'
SCHEMA = 'cut-audit-v6-method-freeze'


def sources(root):
    names = set(s.source_names(root))
    names.update({PROTOCOL, 'scripts/review_v6/__init__.py',
                  'scripts/review_v6/freeze.py', 'scripts/review_v6/audit.py',
                  'scripts/review_v6/audit_runner.py', 'scripts/review_v6/external.py',
                  'scripts/review_v5/external.py', 'scripts/new_domain/run.py',
                  'scripts/new_domain/cohort.py', 'research/review_v6/THEORY.md',
                  'tests/test_review_v6_freeze.py', 'research/review_v6/ALASKA_SOURCE_REVIEW.md'})
    names.update(p.relative_to(root).as_posix() for p in (root/'tests').glob('test_review_v6_audit*.py'))
    names.update(p.relative_to(root).as_posix() for p in (root/'tests').glob('test_review_v6_external*.py'))
    return sorted(names)


def passed_receipt(root, path):
    path = Path(path).resolve()
    s.require(path.is_relative_to(root), 'Validation receipt outside workspace')
    value = s.read(path)
    s.require(value.get('exit_code') == 0 and not value.get('timed_out'), 'Validation did not pass')
    for name, pin in value.get('output_sha256', {}).items():
        s.require(name in ('stdout.txt', 'stderr.txt') and s.digest(path.parent/name) == pin,
                  'Validation output hash mismatch')
    return {'path':path.relative_to(root).as_posix(), 'sha256':s.digest(path),
            'command':value['command'], 'output_sha256':value.get('output_sha256', {})}


def create(validation, smoke, *, root=ROOT):
    root = Path(root).resolve()
    s.checked_freeze(root)
    baseline = passed_receipt(root, root/SESSION/'baseline_tests/command.json')
    checks = [passed_receipt(root, validation), passed_receipt(root, smoke)]
    s.require(all(root.joinpath(n).is_file() for n in sources(root)), 'Required V6 source absent')
    pins = {n:s.digest(root/n) for n in sources(root)}
    snapshot = root/SESSION/'source_snapshot'
    snapshot.mkdir(parents=True, exist_ok=False)
    for name in pins:
        dest = snapshot/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root/name, dest)
    s.check_hashes(snapshot, pins)
    result = {'schema':SCHEMA, 'created_utc':s.utc(), 'files_sha256':pins,
              'snapshot':snapshot.relative_to(root).as_posix(),
              'v5_freeze_sha256':s.digest(root/s.SESSION/'freeze.json'),
              'baseline':baseline, 'validation':checks,
              'scope':'V6 mechanism audits and one prospective Camera development branch',
              'authorization':'Direct user V6 implementation request; no human approval impersonation',
              'v5_external_gate_changed':False, 'sealed_test_access':False,
              'deployment':False, 'submission':False, 'new_selector_methods':0,
              'existing_physical_batch_states':{'natural':241, 'synthetic':60}}
    s.write(root/SESSION/'freeze.json', result)
    return result


def check(root=ROOT):
    root = Path(root).resolve()
    value = s.read(root/SESSION/'freeze.json')
    s.require(value.get('schema') == SCHEMA, 'Wrong V6 method freeze')
    s.require(value['v5_freeze_sha256'] == s.digest(root/s.SESSION/'freeze.json'), 'V5 freeze changed')
    s.checked_freeze(root)
    s.check_hashes(root, value['files_sha256'])
    s.check_hashes(s.relative(root, value['snapshot']), value['files_sha256'])
    for receipt in [value['baseline'], *value['validation']]:
        s.require(s.digest(s.relative(root, receipt['path'])) == receipt['sha256'], 'Validation receipt changed')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('create', 'check'))
    parser.add_argument('--validation', type=Path)
    parser.add_argument('--smoke', type=Path)
    args = parser.parse_args()
    if args.action == 'create':
        s.require(args.validation is not None and args.smoke is not None, 'Validation and smoke receipts required')
        value = create(args.validation, args.smoke)
    else:
        value = check()
    print(s.blob({'status':'PASS', 'schema':value['schema'], 'files':len(value['files_sha256'])}).decode())


if __name__ == '__main__':
    main()
