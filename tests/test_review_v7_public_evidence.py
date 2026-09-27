"""Corruption rejection of the public exact-law and aggregate evidence bundle."""
import csv
import json
from pathlib import Path
import shutil

import pytest

from scripts.review_v7 import validate_evidence as v

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence(tmp_path):
    source = ROOT / 'evidence'
    if not (source / 'v7_manifest.json').is_file():
        source = ROOT / 'publication_v7/evidence'
    target = tmp_path / 'evidence'
    shutil.copytree(source, target)
    (tmp_path / 'configs').mkdir()
    shutil.copyfile(source.parent / 'configs/review_v7_controls.json', tmp_path / 'configs/review_v7_controls.json')
    return target


def change_json(path, mutation):
    value = v.read(path); mutation(value); path.write_bytes(v.blob(value))


def reseal(evidence, name):
    change_json(evidence/'v7_manifest.json', lambda value: value['files_sha256'].update({name:v.sha(evidence/name)}))


def test_public_recomputation_needs_no_private_assets(evidence, monkeypatch):
    monkeypatch.setattr('scripts.review_v7.controls.audit_initial_decision', lambda *_: pytest.fail('Selector invoked'))
    result = v.validate(evidence)
    assert result['status'] == 'PASS' and result['finite_worlds'] == 20
    assert result['same_pool_states'] == 301 and result['new_selector_invocations'] == 0


@pytest.mark.parametrize('name', sorted(v.PAYLOADS))
def test_hash_corruption_is_rejected(evidence, name):
    with (evidence/name).open('ab') as stream: stream.write(b' ')
    with pytest.raises(ValueError, match='hash mismatch'): v.validate(evidence)


def test_resealed_expected_gap_cannot_change_science(evidence):
    change_json(evidence/'controls_summary.json', lambda x: x['cases'][2].update(expected_decision_gap='0'))
    reseal(evidence, 'controls_summary.json')
    with pytest.raises(ValueError, match='expectation summary'): v.validate(evidence)


def test_resealed_missing_visible_case_rejected(evidence):
    change_json(evidence/'controls_visible.json', lambda x: x['cases'].pop())
    reseal(evidence, 'controls_visible.json')
    with pytest.raises(ValueError, match='Missing/extra'): v.validate(evidence)


def test_resealed_world_membership_rejected(evidence):
    path = evidence/'controls_worlds.csv'
    path.write_text(path.read_text().replace('v3', 'another_node'), encoding='utf-8')
    reseal(evidence, path.name)
    with pytest.raises(ValueError, match='Recomputed table'): v.validate(evidence)


def test_resealed_samepool_denominator_rejected(evidence):
    path = evidence/'same_pool_states.csv'
    # Empty pools have no defined fraction: replacing null by zero is not harmless.
    rows = v.raw_rows(path)
    row = next(r for r in rows if r['pool_count'] == '0')
    assert row['scored_fraction'] == ''
    row['scored_fraction'] = '0'
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows)
    reseal(evidence, path.name)
    with pytest.raises(ValueError, match='Zero-denominator'): v.validate(evidence)


def test_resealed_hidden_natural_field_is_rejected(evidence):
    path = evidence/'same_pool_states.csv'
    lines = path.read_text().splitlines()
    path.write_text('\n'.join(line+',gold' for line in lines)+'\n', encoding='utf-8')
    reseal(evidence, path.name)
    with pytest.raises(ValueError, match='fields/inventory'): v.validate(evidence)


def test_manifest_cannot_add_unsafe_member(evidence):
    change_json(evidence/'v7_manifest.json', lambda x: x['files_sha256'].update({'../secret':'0'*64}))
    with pytest.raises(ValueError, match='inventory'): v.validate(evidence)


def test_config_change_rejected(evidence):
    change_json(evidence.parent/'configs/review_v7_controls.json', lambda x: x.update(score_cap=65))
    with pytest.raises(ValueError, match='Configuration hash'): v.validate(evidence)
