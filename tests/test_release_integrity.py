import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('check_release', Path(__file__).resolve().parents[1] / 'scripts/check_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.mark.parametrize('name', ['../secret', '/outside', 'folder/../../secret', 'folder\\secret'])
def test_member_rejects_path_escape(tmp_path, name):
    with pytest.raises(ValueError):
        release.member(tmp_path, name)


def test_manifest_detects_changed_or_missing_evidence(tmp_path):
    (tmp_path / 'provenance').mkdir()
    protected = tmp_path / 'provenance/RETAINED_PAYLOAD_SHA256.json'
    protected.write_text(json.dumps({'files_sha256':{}}))
    evidence = tmp_path / 'evidence.csv'; evidence.write_text('fp,fn\n1,0\n')
    files = {p.relative_to(tmp_path).as_posix():{'sha256':release.sha(p),'bytes':p.stat().st_size}
             for p in (evidence, protected)}
    (tmp_path / 'MANIFEST_SHA256.json').write_text(json.dumps({'schema':'cut-audit-public-release-manifest-v1','files':files}))
    assert release.verify_manifest(tmp_path) == (2, 0)
    evidence.write_text('fp,fn\n0,0\n')
    with pytest.raises(ValueError, match='hash mismatch'):
        release.verify_manifest(tmp_path)
    evidence.unlink()
    with pytest.raises(ValueError, match='inventory differs'):
        release.verify_manifest(tmp_path)


def test_figure_projection_checks_values_not_only_names(tmp_path):
    for directory in (tmp_path / 'figures/data', tmp_path / 'rebuilt/data'):
        directory.mkdir(parents=True)
        for i in range(6):
            (directory / f'{i}.json').write_text(json.dumps({'loss':i}))
    (tmp_path / 'rebuilt/data/3.json').write_text('{"loss": 0}')
    with pytest.raises(ValueError, match='numeric projection mismatch'):
        release.verify_figures(tmp_path, tmp_path / 'rebuilt')
