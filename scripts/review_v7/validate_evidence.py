"""Export and verify V7 public evidence without a selector or private assets.

Known-law expectations are recomputed exactly from the saved synthetic inputs.
Natural state counts are reconciled with the unchanged public V6 audit table;
private candidate/pair identities are outside this public verification scope.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import shutil

from .common import require
from .evaluate import evaluate_case
from .same_pool import FIELDS, blob, checked, csv_rows, manifest, read, sha, summarize

ROOT = Path(__file__).resolve().parents[2]
SESSION = 'outputs/session_20260927_v7'
PAYLOADS = {'controls_summary.json', 'controls_actions.csv', 'controls_worlds.csv',
            'controls_visible.json', 'same_pool_states.csv', 'same_pool_summary.json'}


def raw_rows(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def csv_value(value):
    if value is None: return ''
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(',', ':'))
    return str(value)


def compare_rows(path, expected):
    actual = raw_rows(path)
    fields = list(dict.fromkeys(k for row in expected for k in row))
    normalized = [{key: csv_value(row.get(key)) for key in fields} for row in expected]
    require(actual == normalized, 'Recomputed table differs: ' + Path(path).name)


def validate(evidence):
    evidence = Path(evidence).resolve()
    meta = read(evidence / 'v7_manifest.json')
    require(meta['schema'] == 'cut-audit-v7-public-evidence', 'Wrong V7 public schema')
    require(set(meta['files_sha256']) == PAYLOADS, 'V7 public inventory differs')
    for name, pin in meta['files_sha256'].items(): checked(evidence, name, pin)
    config = evidence.parent / 'configs/review_v7_controls.json'
    require(sha(config) == meta['config_sha256'], 'Configuration hash mismatch')
    specs = read(config)['cases']
    decisions = read(evidence / 'controls_visible.json')
    require(decisions['schema'] == 'cut-audit-v7-public-visible-controls', 'Visible schema differs')
    require([r['case'] for r in decisions['cases']] == [s['id'] for s in specs], 'Missing/extra visible case')
    summary = read(evidence / 'controls_summary.json')
    require(summary['status'] == 'passed' and summary['config_sha256'] == meta['config_sha256'], 'Controls not passed/pinned')
    require(summary['visible_manifest_sha256'] == meta['source_visible_manifest_sha256'], 'Visible source chain differs')
    results = [evaluate_case(spec, decision) for spec, decision in zip(specs, decisions['cases'])]
    require([r['summary'] for r in results] == summary['cases'], 'Exact expectation summary differs')
    actions = [row for value in results for row in value['actions']]
    worlds = [{'case': spec['id'], 'world_id': w['id'], 'weight': w['weight'], 'reference': w['reference']}
              for spec, value in zip(specs, results) for w in value['worlds']]
    require(summary['finite_worlds'] == len(worlds) == 20 and summary['initial_decisions'] == len(results) == 4,
            'Known-law fixed inventory differs')
    require(summary['natural_acquisitions'] == summary['new_oracle_answers'] == 0
            and summary['reference_evaluation_only'] is True, 'Known-law evidence scope differs')
    compare_rows(evidence / 'controls_actions.csv', actions)
    compare_rows(evidence / 'controls_worlds.csv', worlds)
    rows = csv_rows(evidence / 'same_pool_states.csv')
    require(len(rows) == 301 and all(set(r) == set(FIELDS) for r in rows), 'Same-pool fields/inventory differ')
    require(len({r['state'] for r in rows}) == 301, 'Repeated natural/synthetic state index')
    old = manifest(evidence / 'manifest.json', meta['predecessor_evidence_manifest_sha256'])
    original = {r['state']: r for r in csv_rows(evidence / 'visible_states.csv')}
    require(set(original) == {r['state'] for r in rows}, 'V6/V7 state membership differs')
    for row in rows:
        prior = original[row['state']]
        for key in ('unique_state', 'phase', 'dataset', 'budget', 'batch', 'status', 'certificate_status',
                    'pool_count', 'scored_count', 'pool_argmax_certified', 'fallback',
                    'graph_wide_bonds_complete', 'diagnostic_score_accesses', 'diagnostic_seconds'):
            require(row[key] == prior[key], 'Same-pool predecessor mismatch: ' + key)
        n, k = row['pool_count'], row['scored_count']
        require(0 <= k <= n and row['positive_certificate'] == prior['certificate_for_selected_positive'], 'Invalid count/certificate')
        strict = row['certificate_status'] == 'strict_upper_bound_separation'
        require(row['strict_pruned_count'] == (n-k if strict else 0), 'Strict pruning count differs')
        require(row['score_limit_unscored_count'] == (n-k if not strict else 0), 'Uncertified count differs')
        require(row['same_pool_additional_full_scores'] == n-k, 'Same-pool score difference differs')
        require(row['scored_fraction'] == (k/n if n else None), 'Zero-denominator/fraction differs')
    require(summarize(rows) == read(evidence / 'same_pool_summary.json'), 'Same-pool aggregate differs')
    return {'status': 'PASS', 'known_law_cases': len(results), 'finite_worlds': len(worlds),
            'analytic_cases': 1, 'candidate_rows': len(actions), 'same_pool_states': len(rows),
            'new_selector_invocations': 0, 'new_oracle_answers': 0,
            'public_scope': 'Exact constructed-law reference recomputation and public aggregate consistency; private natural candidate identities not revalidated.'}


def export(evidence, *, root=ROOT):
    root, evidence = Path(root).resolve(), Path(evidence).resolve()
    require(evidence.is_dir(), 'Prepare the public tree first')
    require(not any((evidence / name).exists() for name in PAYLOADS | {'v7_manifest.json'}), 'Preserve previous V7 export')
    base = root / SESSION
    visible = manifest(base / 'controls_visible/integrity.json', sha(base / 'controls_visible/integrity.json'))
    result = manifest(base / 'controls/integrity.json', sha(base / 'controls/integrity.json'))
    pool = manifest(base / 'same_pool/manifest.json', sha(base / 'same_pool/manifest.json'))
    require(visible['status'] == result['status'] == 'passed' and pool['status'] == 'PASS', 'Unpassed source stage')
    require(result['visible_manifest_sha256'] == sha(base / 'controls_visible/integrity.json'), 'Private result chain differs')
    decisions = {'schema': 'cut-audit-v7-public-visible-controls', 'synthetic_only': True,
                 'cases': [read(base / 'controls_visible' / row['path']) for row in visible['cases']]}
    (evidence / 'controls_visible.json').write_bytes(blob(decisions))
    for name in PAYLOADS - {'controls_visible.json'}:
        folder = 'same_pool' if name.startswith('same_pool') else 'controls'
        shutil.copyfile(base / folder / name, evidence / name)
    config = evidence.parent / 'configs'; config.mkdir(exist_ok=True)
    shutil.copyfile(root / 'configs/review_v7_controls.json', config / 'review_v7_controls.json')
    value = {'schema': 'cut-audit-v7-public-evidence', 'files_sha256': {n: sha(evidence/n) for n in sorted(PAYLOADS)},
             'config_sha256': sha(config/'review_v7_controls.json'),
             'source_visible_manifest_sha256': sha(base/'controls_visible/integrity.json'),
             'source_reference_manifest_sha256': sha(base/'controls/integrity.json'),
             'source_same_pool_manifest_sha256': sha(base/'same_pool/manifest.json'),
             'predecessor_evidence_manifest_sha256': sha(evidence/'manifest.json'),
             'new_natural_acquisitions': 0, 'natural_identifiers_exported': False}
    (evidence/'v7_manifest.json').write_bytes(blob(value))
    return validate(evidence)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, default=Path('evidence'))
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    print(json.dumps(export(args.evidence) if args.export else validate(args.evidence), sort_keys=True))
