"""V6 guards fail closed on changed source or validation artifacts."""
from pathlib import Path
import pytest
from scripts.review_v5 import study as s
from scripts.review_v6 import freeze


def frozen_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(s, 'checked_freeze', lambda root: None)
    v5 = tmp_path/s.SESSION/'freeze.json'
    s.write(v5, {'historical':'unchanged'})
    src = tmp_path/'src'/'visible.py'
    src.parent.mkdir()
    src.write_text('answer = 1\n', encoding='utf-8')
    snap = tmp_path/'snapshot'/'src'/'visible.py'
    snap.parent.mkdir(parents=True)
    snap.write_bytes(src.read_bytes())
    receipt = tmp_path/'checks'/'command.json'
    s.write(receipt, {'exit_code':0, 'command':['python','-m','pytest','-q']})
    pin = {'path':'checks/command.json', 'sha256':s.digest(receipt)}
    data = {'schema':freeze.SCHEMA, 'v5_freeze_sha256':s.digest(v5),
            'snapshot':'snapshot', 'files_sha256':{'src/visible.py':s.digest(src)},
            'baseline':pin, 'validation':[]}
    s.write(tmp_path/freeze.SESSION/'freeze.json', data)
    return src, snap, receipt, v5


@pytest.mark.parametrize('target', range(4))
def test_freeze_rejects_changed_live_snapshot_receipt_or_predecessor(tmp_path, monkeypatch, target):
    files = frozen_fixture(tmp_path, monkeypatch)
    assert freeze.check(tmp_path)['schema'] == freeze.SCHEMA
    files[target].write_bytes(files[target].read_bytes()+b' ')
    with pytest.raises(ValueError, match='changed|mismatch'):
        freeze.check(tmp_path)


def test_failed_or_tampered_validation_cannot_authorize_freeze(tmp_path):
    folder = tmp_path/'check'
    folder.mkdir()
    (folder/'stdout.txt').write_text('fixture failure', encoding='utf-8')
    path = folder/'command.json'
    s.write(path, {'exit_code':1, 'command':['python'], 'output_sha256':{}})
    with pytest.raises(ValueError, match='did not pass'):
        freeze.passed_receipt(tmp_path, path)
    s.write(path, {'exit_code':0, 'command':['python'],
                  'output_sha256':{'stdout.txt':'0'*64}}, replace=True)
    with pytest.raises(ValueError, match='output hash'):
        freeze.passed_receipt(tmp_path, path)
