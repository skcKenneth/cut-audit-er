"""Semantic evidence mutations must fail even after the file hash is updated."""
from pathlib import Path
import csv
import json
import shutil
import pytest
from scripts.validate_evidence import validate,sha,table
from scripts.check_public_release import allowed_name

ROOT=Path(__file__).resolve().parents[1]

def mutation(tmp_path,name,change):
    out=tmp_path/'evidence';shutil.copytree(ROOT/'evidence',out)
    path=out/(name+'.csv')
    with path.open(encoding='utf-8',newline='') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;rows=list(reader)
    change(rows)
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    path=out/'manifest.json';m=json.loads(path.read_text())
    m['files_sha256'][name+'.csv']=sha(out/(name+'.csv'));path.write_text(json.dumps(m))
    return out

def test_public_grid_and_missing_rows_retained():
    report=validate(ROOT/'evidence')
    assert report['natural_slots']==27 and report['natural_completed']==27
    assert report['synthetic_reference_slots']==180 and report['synthetic_reference_completed']==178
    assert len([r for r in table(ROOT/'evidence','synthetic_endpoints') if r['loss'] is None])==2

@pytest.mark.parametrize('field,value',[('loss','99999'),('fp_removed','-1'),('spent','1.5')])
def test_rehashed_bad_event_accounting_rejected(tmp_path,field,value):
    column='loss_after' if field=='loss' else field
    out=mutation(tmp_path,'natural_events',lambda rows: rows[0].update({column:value}))
    with pytest.raises(ValueError):validate(out)

def test_rehashed_missing_synthetic_metric_is_not_filled(tmp_path):
    def change(rows):
        r=next(r for r in rows if r['status']!='completed');r.update(fp='0',fn='0',loss='0')
    out=mutation(tmp_path,'synthetic_endpoints',change)
    with pytest.raises(ValueError,match='imputed'):validate(out)

def test_unlisted_file_is_rejected(tmp_path):
    out=tmp_path/'evidence';shutil.copytree(ROOT/'evidence',out)
    (out/'extra.json').write_text('{}')
    with pytest.raises(ValueError,match='Unlisted'):validate(out)

@pytest.mark.parametrize('name',['.git/config','../outside.json','paper/main.tex','paper/main.pdf',
    'data/processed/records.csv','replay/wdc/scores.npy','credentials.json'])
def test_private_and_unsafe_paths_rejected(name):
    with pytest.raises(ValueError):allowed_name(name)

def test_allowed_dblp_derived_replay_is_explicit():
    assert allowed_name('replay/dblp_unused/scores.npy')

def test_dblp_extra_reverse_mapping_cannot_be_published(tmp_path):
    from scripts.check_public_release import check
    replay=tmp_path/'replay/dblp_unused';replay.mkdir(parents=True)
    for name in ('observable.json','scores.npy','paid_cases.json','evaluator_reference.json','manifest.json','reverse_mapping.json'):
        (replay/name).write_text('{}')
    with pytest.raises(ValueError,match='Unlisted DBLP'):check(tmp_path)
