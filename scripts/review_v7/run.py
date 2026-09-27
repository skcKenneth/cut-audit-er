"""Separate visible/reference CLI stages for fixed known-law diagnostics."""
from __future__ import annotations
import argparse
import csv
import json
import os
from pathlib import Path
import time

from scripts.review_v5 import study as s
from . import freeze


def csv_write(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with Path(path).open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True, separators=(',',':')) if isinstance(v,(dict,list,tuple)) else v
                             for k,v in row.items()})


def seal(out, metadata):
    pins = {p.relative_to(out).as_posix():s.digest(p) for p in sorted(out.rglob('*')) if p.is_file()}
    value = {**metadata, 'files_sha256':pins}
    s.write(out/'integrity.json', value)
    return value


def run_visible(out, freeze_pin, *, root=freeze.ROOT):
    from .controls import visible_case, audit_initial_decision
    root = Path(root); freeze.check(root)
    s.require(s.digest(root/freeze.SESSION/'freeze.json') == freeze_pin, 'Freeze pin mismatch')
    config = s.read(root/freeze.CONFIG)
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    s.write(out/'started.json', {'stage':'visible','pid':os.getpid(),'utc':s.utc(),'freeze_sha256':freeze_pin})
    cases = []
    for spec in config['cases']:
        decision = audit_initial_decision(visible_case(spec))
        s.write(out/(spec['id']+'.json'), decision)
        cases.append({'case':spec['id'],'path':spec['id']+'.json','pool_count':decision['pool_count'],
                      'scored_count':decision['scored_count'],'certificate_status':decision['certificate_status']})
    return seal(out, {'schema':'cut-audit-v7-visible-manifest','status':'passed','cases':cases,
                     'config_sha256':s.digest(root/freeze.CONFIG),'freeze_sha256':freeze_pin,
                     'selector_invocations':len(cases),'new_oracle_answers':0,'elapsed_seconds':time.perf_counter()-start})


def run_evaluate(out, visible_manifest, visible_pin, freeze_pin, *, root=freeze.ROOT):
    # Reference code loads only here, in its own post-visible CLI invocation.
    from .evaluate import evaluate_case
    root = Path(root); freeze.check(root)
    s.require(s.digest(root/freeze.SESSION/'freeze.json') == freeze_pin, 'Freeze pin mismatch')
    manifest = freeze.checked_manifest(visible_manifest, visible_pin)
    s.require(manifest['status'] == 'passed' and manifest['freeze_sha256'] == freeze_pin, 'Visible stage not frozen/passed')
    config = s.read(root/freeze.CONFIG)
    s.require(manifest['config_sha256'] == s.digest(root/freeze.CONFIG), 'Configuration mismatch')
    s.require([r['case'] for r in manifest['cases']] == [r['id'] for r in config['cases']], 'Case inventory mismatch')
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    s.write(out/'started.json', {'stage':'reference','pid':os.getpid(),'utc':s.utc(),'visible_manifest_sha256':visible_pin})
    summaries, actions, worlds = [], [], []
    for spec, saved in zip(config['cases'], manifest['cases']):
        decision = s.read(s.relative(Path(visible_manifest).parent, saved['path']))
        value = evaluate_case(spec, decision)
        s.write(out/(spec['id']+'.json'), value)
        summaries.append(value['summary']); actions.extend(value['actions'])
        worlds.extend({'case':spec['id'],'world_id':w['id'],'weight':w['weight'],'reference':w['reference']} for w in value['worlds'])
    summary = {'schema':'cut-audit-v7-known-law-summary','status':'passed','cases':summaries,
               'finite_worlds':len(worlds), 'initial_decisions':len(summaries), 'natural_acquisitions':0,
               'new_oracle_answers':0,'reference_evaluation_only':True,
               'config_sha256':s.digest(root/freeze.CONFIG),'visible_manifest_sha256':visible_pin,
               'scope':'Constructive known-law initial single-batch diagnostics; not natural data or sampled independent observations'}
    s.write(out/'controls_summary.json', summary)
    csv_write(out/'controls_actions.csv', actions); csv_write(out/'controls_worlds.csv', worlds)
    # Check the complete visible package again after the reference process.
    freeze.checked_manifest(visible_manifest, visible_pin)
    return seal(out, {'schema':'cut-audit-v7-reference-manifest','status':'passed','finite_worlds':len(worlds),
                     'action_rows':len(actions),'visible_manifest_sha256':visible_pin,'freeze_sha256':freeze_pin,
                     'elapsed_seconds':time.perf_counter()-start,'new_oracle_answers':0})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('visible','evaluate')); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--freeze-sha256', required=True)
    parser.add_argument('--visible-manifest', type=Path); parser.add_argument('--visible-manifest-sha256')
    args = parser.parse_args()
    if args.stage == 'visible':
        result = run_visible(args.out, args.freeze_sha256)
    else:
        s.require(args.visible_manifest is not None and args.visible_manifest_sha256, 'Visible source and hash required')
        result = run_evaluate(args.out, args.visible_manifest, args.visible_manifest_sha256, args.freeze_sha256)
    print(json.dumps({k:v for k,v in result.items() if k != 'files_sha256'}, indent=2))
