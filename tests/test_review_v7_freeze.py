from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.review_v5 import study as s
from scripts.review_v7 import freeze as f, run


def test_manifest_rejects_tamper_missing_and_traversal(tmp_path):
    source = tmp_path/'x.json'; s.write(source, {'visible':True})
    manifest = tmp_path/'integrity.json'
    s.write(manifest, {'files_sha256':{'x.json':s.digest(source)}})
    pin = s.digest(manifest)
    assert f.checked_manifest(manifest, pin)
    with pytest.raises(ValueError, match='Manifest hash'):
        f.checked_manifest(manifest, '0'*64)
    source.write_text('{}')
    with pytest.raises(ValueError, match='hash'):
        f.checked_manifest(manifest, pin)
    source.unlink()
    with pytest.raises(ValueError): f.checked_manifest(manifest, pin)
    with pytest.raises(ValueError): s.check_hashes(tmp_path, {'../x':'0'*64})


def test_visible_and_reference_stages_pin_sources_and_refuse_reuse(tmp_path, monkeypatch):
    root = Path(__file__).parents[1]
    config = s.read(root/f.CONFIG)
    # One small fixture law exercises lifecycle; not a new formal study slot.
    config['cases'] = [config['cases'][2]]
    s.write(tmp_path/f.CONFIG, config)
    s.write(tmp_path/f.SESSION/'freeze.json', {'fixture':True})
    monkeypatch.setattr(f, 'check', lambda root: {})
    pin = s.digest(tmp_path/f.SESSION/'freeze.json')
    visible = tmp_path/'visible'
    result = run.run_visible(visible, pin, root=tmp_path)
    assert result['selector_invocations'] == 1 and result['new_oracle_answers'] == 0
    manifest = visible/'integrity.json'; saved = s.digest(manifest)
    with pytest.raises(FileExistsError): run.run_visible(visible, pin, root=tmp_path)
    out = tmp_path/'reference'
    evaluation = run.run_evaluate(out, manifest, saved, pin, root=tmp_path)
    assert evaluation['finite_worlds'] == 8
    assert s.digest(manifest) == saved
    assert s.read(out/'controls_summary.json')['cases'][0]['expected_decision_gap'] == '3/20'
    with pytest.raises(FileExistsError): run.run_evaluate(out, manifest, saved, pin, root=tmp_path)
    with pytest.raises(ValueError, match='pin mismatch'):
        run.run_visible(tmp_path/'bad', '0'*64, root=tmp_path)
    assert not (tmp_path/'bad').exists()
    (visible/'path_reversal.json').write_text('{}')
    with pytest.raises(ValueError, match='hash'):
        run.run_evaluate(tmp_path/'bad_ref', manifest, saved, pin, root=tmp_path)
    assert not (tmp_path/'bad_ref').exists()


def test_check_rejects_changed_snapshot_and_v6_source(tmp_path, monkeypatch):
    monkeypatch.setattr(f.predecessor, 'check', lambda root: {})
    s.write(tmp_path/f.predecessor.SESSION/'freeze.json', {'predecessor':True})
    payload = tmp_path/'test.py'; payload.write_text('x=1')
    snapshot = tmp_path/'snapshot'; snapshot.mkdir(); (snapshot/'test.py').write_text('x=1')
    receipt = tmp_path/'receipt.json'; s.write(receipt, {'exit_code':0})
    value = {'schema':f.SCHEMA,'v6_freeze_sha256':s.digest(tmp_path/f.predecessor.SESSION/'freeze.json'),
             'files_sha256':{'test.py':s.digest(payload)}, 'snapshot':'snapshot',
             'baseline':{'path':'receipt.json','sha256':s.digest(receipt)},'validation':[]}
    s.write(tmp_path/f.SESSION/'freeze.json', value)
    assert f.check(tmp_path) == value
    (snapshot/'test.py').write_text('x=2')
    with pytest.raises(ValueError, match='hash'): f.check(tmp_path)
    (snapshot/'test.py').write_text('x=1')
    (tmp_path/f.predecessor.SESSION/'freeze.json').write_text('{}')
    with pytest.raises(ValueError, match='V6 freeze'): f.check(tmp_path)
