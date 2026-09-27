"""Finite public saved-answer checks; never call acquisition or a gold oracle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from scripts.validate_evidence import table, validate
from scripts.review_v4.replay import check_bundle
from scripts.review_v4.synthetic import check_analysis


def check(root):
    root = Path(root).resolve()
    evidence = validate(root / 'evidence')
    natural = table(root / 'evidence', 'natural_endpoints')
    outcomes = []
    for dataset, name in [('dblp_acm', 'dblp_exposed'), ('dblp_unused', 'dblp_unused')]:
        expected = sum(row['dataset'] == dataset and row['status'] == 'completed' for row in natural)
        folder = root / 'replay' / name
        if expected:
            report = check_bundle(folder)
            if report['cases'] != expected or report['new_oracle_answers'] != 0:
                raise ValueError('Public DBLP replay inventory differs: ' + name)
            outcomes.append({'bundle': name, **report})
        elif folder.exists():
            raise ValueError('Unexpected replay bundle for zero completed cohort cases')
        else:
            outcomes.append({'bundle': name, 'status': 'not_available', 'reason': 'No complete declared cases'})
    synthetic = check_analysis(root / 'replay/synthetic/study', root / 'replay/synthetic/analysis')
    manifest = json.loads((root / 'evidence/manifest.json').read_text(encoding='utf-8'))
    if synthetic['completed_acquisitions'] != manifest['counts']['synthetic_acquisitions_completed']:
        raise ValueError('Synthetic replay count differs from canonical evidence')
    return {'status': 'PASS', 'evidence': evidence, 'natural_replays': outcomes,
            'synthetic_replay': synthetic, 'new_oracle_answers': 0,
            'scope': 'Saved-answer reconstruction only; no acquisition, fitting or external assets'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    result = check(args.root)
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        with args.receipt.open('x', encoding='utf-8') as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
            handle.write('\n')
    print(json.dumps(result, indent=2, allow_nan=False))
