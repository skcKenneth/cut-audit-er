"""V6 branch correctness fixtures: no network, benchmark fitting or acquisition."""
import csv
from io import StringIO
import json
from pathlib import Path
import zipfile
import pytest

from scripts.review_v6 import external as e
from scripts.review_v5 import external as legacy


def gate_fixture(tmp_path, monkeypatch, *, unknown=0, mismatch=0):
    monkeypatch.setattr(e, 'check_method', lambda root: {'fixture':True})
    e.s.write(tmp_path/e.SESSION/'freeze.json', {'fixture':True})
    (tmp_path/'source.py').write_text('fixture')
    pins={}
    fixture_rows=[]
    for index in range(301):
        phase='natural' if index<241 else 'synthetic'
        dataset='wdc' if index<73 else 'dblp_acm' if index<157 else 'dblp_unused' if index<241 else 'k1_uniform'
        fixture_rows.append({'id':f'fixture_{index:03d}', 'run_id':'fixture', 'phase':phase,
            'dataset':dataset, 'cohort':'synthetic' if phase=='synthetic' else dataset,
            'budget':12 if phase=='natural' else 6, 'batch':index+1,
            'worker_seconds':30 if phase=='synthetic' else 120,
            'suite_seconds':900 if phase=='synthetic' else 2700,
            'status':'timeout_unknown' if index<unknown else 'passed'})
    for kind in ('visible','evaluator'):
        folder=tmp_path/e.SESSION/kind
        e.s.write(folder/'data.json', {'fixture':True})
        path=folder/'manifest.json'
        e.s.write(path, {'schema':f'cut-audit-v6-{kind}-suite-v1',
            'status':'completed_with_unknown' if unknown else 'passed',
            'planned_states':301, 'completed_states':301-unknown,'unknown_states':unknown,
            'phase_counts':{'natural':241,'synthetic':60},
            'rows':fixture_rows,
            'technical_mismatch_count':mismatch,'technical_mismatches':[],
            'code_sha256':{'source.py':e.s.digest(tmp_path/'source.py')},
            'source_manifest_sha256':e.s.digest(tmp_path/e.SESSION/'visible/manifest.json') if kind=='evaluator' else 'f'*64,
            'files_sha256':{'data.json':e.s.digest(folder/'data.json')}})
        pins[path.relative_to(tmp_path).as_posix()]=e.s.digest(path)
    gate={'schema':'cut-audit-v6-audit-gate-v1',
          'method_freeze_sha256':e.s.digest(tmp_path/e.SESSION/'freeze.json'),
          'audit_manifests_sha256':pins,'scopes_finalized':True,'mismatches':0,
          'technical_errors':0,'eligible':True,'timeout_unknown_states':unknown}
    e.s.write(tmp_path/e.SESSION/'audit_gate.json',gate)
    return gate


def test_new_branch_is_separate_and_keeps_fixed_21_recipe():
    assert e.EXTERNAL!=legacy.EXTERNAL
    assert e.normalize_archive is legacy.normalize_archive
    old=legacy.fixed_config(); new=e.fixed_config()
    for key in old:
        if key!='schema': assert new[key]==old[key]
    assert not new['v5_gate_rewritten']
    assert len(e.planned_slots())==21
    assert [r['budget'] for r in e.planned_slots()]==[12]*7+[24]*7+[48]*7
    assert [r['method'] for r in e.planned_slots()[:7]]==list(e.s.NATURAL_METHODS)


def test_v6_gate_never_calls_failed_v5_gate(tmp_path,monkeypatch):
    gate_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(legacy,'checked_gate',lambda *a:(_ for _ in ()).throw(AssertionError('Legacy gate called')))
    result=e.checked_gate(tmp_path)
    assert result['v5_progression_gate_not_used']
    assert result['audit_gate_sha256']==e.s.digest(tmp_path/e.SESSION/'audit_gate.json')
    assert result['audit_gate_sha256'] not in result['audit_manifests_sha256'].values()


def test_timeout_unknown_is_not_a_favorable_result_gate(tmp_path,monkeypatch):
    gate_fixture(tmp_path,monkeypatch,unknown=5)
    assert e.checked_gate(tmp_path)['timeout_unknown_states']==5


def test_actual_auditor_gate_contract_integrates_with_external(tmp_path,monkeypatch):
    from scripts.review_v6.audit_runner import make_gate
    gate_fixture(tmp_path,monkeypatch,unknown=2)
    result=make_gate(tmp_path,e.s.digest(tmp_path/e.SESSION/'freeze.json'),
        tmp_path/e.SESSION/'visible/manifest.json',tmp_path/e.SESSION/'evaluator/manifest.json',
        tmp_path/e.SESSION/'constructed_gate.json')
    e.s.write(tmp_path/e.SESSION/'audit_gate.json',result,replace=True)
    assert e.checked_gate(tmp_path)['timeout_unknown_states']==4


def test_manifest_mismatch_cannot_be_hidden_by_eligible_flag(tmp_path,monkeypatch):
    gate_fixture(tmp_path,monkeypatch,mismatch=1)
    with pytest.raises(ValueError,match='technical mismatch'):e.checked_gate(tmp_path)


@pytest.mark.parametrize('field,value', [('mismatches',1),('technical_errors',1),('scopes_finalized',False),('eligible',False)])
def test_gate_failure_precedes_archive_access(tmp_path,monkeypatch,field,value):
    gate=gate_fixture(tmp_path,monkeypatch);gate[field]=value
    e.s.write(tmp_path/e.SESSION/'audit_gate.json',gate,replace=True)
    with pytest.raises(ValueError):e.qualify(tmp_path/'absent.zip',tmp_path/'none.json',root=tmp_path)
    assert not (tmp_path/e.EXTERNAL).exists()


def test_source_manifest_payload_and_gate_hash_errors_fail(tmp_path,monkeypatch):
    gate=gate_fixture(tmp_path,monkeypatch)
    (tmp_path/e.SESSION/'visible/data.json').write_text('tampered')
    with pytest.raises(ValueError,match='Source hash mismatch'):e.checked_gate(tmp_path)


def test_missing_second_scope_is_not_success(tmp_path,monkeypatch):
    gate=gate_fixture(tmp_path,monkeypatch)
    gate['audit_manifests_sha256']={n:h for n,h in gate['audit_manifests_sha256'].items() if '/visible/' in n}
    e.s.write(tmp_path/e.SESSION/'audit_gate.json',gate,replace=True)
    with pytest.raises(ValueError,match='Both visible'):e.checked_gate(tmp_path)


@pytest.mark.parametrize('field,value',[('planned_states',300),('phase_counts',{'natural':241,'synthetic':59}),
                                      ('completed_states',299),('source_manifest_sha256','a'*64)])
def test_incomplete_or_unbound_evaluator_rejected(tmp_path,monkeypatch,field,value):
    gate=gate_fixture(tmp_path,monkeypatch)
    path=tmp_path/e.SESSION/'evaluator/manifest.json'
    report=e.s.read(path);report[field]=value;e.s.write(path,report,replace=True)
    gate['audit_manifests_sha256'][path.relative_to(tmp_path).as_posix()]=e.s.digest(path)
    e.s.write(tmp_path/e.SESSION/'audit_gate.json',gate,replace=True)
    with pytest.raises(ValueError):e.checked_gate(tmp_path)


def role_fixture(tmp_path):
    records=[{'record_id':f'r{i:02d}_{j}','entity_id':f'e{i:02d}','text':f'Camera title {i} {j}'}
             for i in range(10) for j in range(2)]
    stream=StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=['record_id','entity_id','text'],lineterminator='\n')
    writer.writeheader();writer.writerows(records)
    out=tmp_path/e.EXTERNAL;(out/'normalized').mkdir(parents=True)
    (out/'normalized/records.csv').write_bytes(stream.getvalue().encode())
    roles,membership=e.split_cohort(records,e.s.digest(out/'normalized/records.csv'),**e.fixed_config()['cohort'])
    e.s.write(out/'memberships.json',membership)
    for role,rows in roles.items():e.s.write(out/'roles'/f'{role}.json',rows)
    return out,roles,membership


def test_whole_entity_memberships_recomputed_and_overlap_rejected(tmp_path):
    out,roles,membership=role_fixture(tmp_path)
    assert e.validate_memberships(tmp_path)==membership
    roles['evaluation'].append(roles['train'][0])
    e.s.write(out/'roles/evaluation.json',roles['evaluation'],replace=True)
    with pytest.raises(ValueError,match='Role records differ'):e.validate_memberships(tmp_path)


def test_changed_entity_manifest_rejected(tmp_path):
    out,roles,membership=role_fixture(tmp_path)
    membership['entity_overlap']=1;e.s.write(out/'memberships.json',membership,replace=True)
    with pytest.raises(ValueError,match='Whole-entity'):e.validate_memberships(tmp_path)


def qualification_fixture(tmp_path,monkeypatch):
    gate_fixture(tmp_path,monkeypatch)
    path=tmp_path/'constructed_camera.zip'
    mapping='entity_id,spec_id\n'+''.join(f'e{i:02d},fixture.test//{i:02d}_{j}\n' for i in range(10) for j in range(2))
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('camera/mapping.csv',mapping)
        for i in range(10):
            for j in range(2):archive.writestr(f'camera/fixture.test/{i:02d}_{j}.json',json.dumps({'<page title>':f'Camera {i} title {j}'}))
    expected={'labeled_records':20,'entities':10,'records':20,'sources':1}
    monkeypatch.setattr(e,'normalize_archive',lambda path:legacy.normalize_archive(path,expected=expected))
    provenance=tmp_path/'provenance.json'
    value={'provider_url':e.PROVIDER,'archive_sha256':e.s.digest(path),
        'download_url':'https://example.invalid/constructed-fixture.zip',
        'license_review':{'local_research_use_supported':True,'basis':'Software fixture, not a real license finding.',
                          'embedded_notices_reviewed_sha256':{}},
        'historical_exposure_review':{'previously_used':False,'basis':'Constructed for this unit test only.'}}
    e.s.write(provenance,value)
    return path,provenance


def test_qualification_keeps_exact_recipe_and_is_consumed_once(tmp_path,monkeypatch):
    path,provenance=qualification_fixture(tmp_path,monkeypatch)
    report=e.qualify(path,provenance,root=tmp_path)
    assert report['status']=='qualified'
    membership=e.validate_memberships(tmp_path)
    assert membership['selected_records']==20 and membership['entity_overlap']==0
    assert e.s.read(tmp_path/e.EXTERNAL/'config.json')==e.fixed_config()
    with pytest.raises(FileExistsError):e.qualify(path,provenance,root=tmp_path)


@pytest.mark.parametrize('field,value',[('archive_sha256','a'*64),
    ('license_review',{'local_research_use_supported':False}),
    ('historical_exposure_review',{'previously_used':True})])
def test_qualification_failures_are_preserved_not_retried(tmp_path,monkeypatch,field,value):
    path,provenance=qualification_fixture(tmp_path,monkeypatch)
    data=e.s.read(provenance);data[field]=value;e.s.write(provenance,data,replace=True)
    with pytest.raises(ValueError):e.qualify(path,provenance,root=tmp_path)
    assert e.s.read(tmp_path/e.EXTERNAL/'qualification.json')['status']=='blocked'
    with pytest.raises(FileExistsError):e.qualify(path,provenance,root=tmp_path)


def blocked_fixture(tmp_path,monkeypatch):
    monkeypatch.setattr(e,'check_method',lambda root:{'fixture':True})
    e.s.write(tmp_path/e.SESSION/'freeze.json',{'fixture':True})
    receipt=tmp_path/e.SESSION/'provider_review/transport.json'
    e.s.write(receipt,{'schema':'cut-audit-v6-provider-transport-review-v1',
        'status':'blocked_expired_official_share','provider_url':e.PROVIDER,
        'expired_share_message_found':True,'archive_downloaded':False})
    return receipt


def test_blocked_transport_retains_all_missing_rows_without_passed_gate(tmp_path,monkeypatch):
    receipt=blocked_fixture(tmp_path,monkeypatch)
    report=e.record_blocked(receipt,root=tmp_path)
    assert len(report['runs'])==21 and report['paid_queries']==0
    assert {r['status'] for r in report['runs']}=={'not_started_download_blocked'}
    assert all(r['loss'] is None and r['paid_queries'] is None for r in report['runs'])
    assert not report['audit_gate_claimed_passed'] and report['archive_downloads']==0
    with pytest.raises(FileExistsError):e.record_blocked(receipt,root=tmp_path)


def test_started_branch_cannot_be_written_as_never_started(tmp_path,monkeypatch):
    receipt=blocked_fixture(tmp_path,monkeypatch)
    e.s.write(tmp_path/e.EXTERNAL/'qualification_consumed.json',{'fixture':True})
    with pytest.raises(ValueError,match='acquired or attempted'):e.record_blocked(receipt,root=tmp_path)


def test_successful_archive_cannot_be_relabelled_expired(tmp_path,monkeypatch):
    receipt=blocked_fixture(tmp_path,monkeypatch)
    value=e.s.read(receipt);value['archive_downloaded']=True;e.s.write(receipt,value,replace=True)
    with pytest.raises(ValueError,match='does not demonstrate'):e.record_blocked(receipt,root=tmp_path)


def test_prefit_hash_change_rejected_before_any_fit(tmp_path,monkeypatch):
    out=tmp_path/e.EXTERNAL;out.mkdir(parents=True)
    (tmp_path/'source.py').write_text('changed')
    e.s.write(out/'prefit_freeze.json',{'schema':'cut-audit-v6-alaska-prefit-freeze-v1','config':e.fixed_config(),
        'slots':e.planned_slots(),'method_freeze_sha256':'a'*64,'files_sha256':{'source.py':'b'*64},'snapshot':'snapshot'})
    real=e.s.digest
    monkeypatch.setattr(e.s,'digest',lambda p:'a'*64 if str(p).endswith('freeze.json') else real(p))
    with pytest.raises(ValueError,match='Source hash mismatch'):e.check_prefit(tmp_path)


def prepare_fixture(tmp_path,monkeypatch):
    from scripts.new_domain.cohort import split_cohort
    records=[{'record_id':f'r{i:02d}_{j}','entity_id':f'e{i:02d}','text':f'Camera {i} title {j}'}
             for i in range(10) for j in range(2)]
    roles,memberships=split_cohort(records,'a'*64,**e.fixed_config()['cohort'])
    out=tmp_path/e.EXTERNAL
    for role,rows in roles.items():e.s.write(out/'roles'/f'{role}.json',rows)
    e.s.write(out/'memberships.json',memberships);e.s.write(out/'prefit_freeze.json',{'fixture':True})
    monkeypatch.setattr(e,'check_prefit',lambda root:None)
    for key,value in e.s.ENV.items():monkeypatch.setenv(key,value)
    return out,roles,memberships


def test_prepare_exact_existing_matcher_graph_stage_contract_and_no_refit(tmp_path,monkeypatch):
    import networkx as nx
    import numpy as np
    from cut_audit_er.matcher import PairMatcher
    from cut_audit_er.scores import PairScores
    from scripts.new_domain import run as engine
    out,roles,memberships=prepare_fixture(tmp_path,monkeypatch)
    # Use the real class/attribute names, but never call fit or acquire labels.
    matcher=PairMatcher(7,50000,'char4')
    matcher.model.coef_=np.ones((1,4));matcher.model.intercept_=np.array([0.])
    matcher.calibrator.coef_=np.ones((1,1));matcher.calibrator.intercept_=np.array([0.])
    matcher.vectorizer.vocabulary_={'fixture':0};matcher.fit_diagnostics={'software_fixture':True}
    graph=nx.Graph(); ids=tuple(r['record_id'] for r in roles['evaluation']);graph.add_nodes_from(ids)
    scores=PairScores(ids,np.eye(len(ids))); calls=[]
    def bounded(name,args,seconds):
        calls.append((name,seconds))
        if name=='matcher':
            assert args==(roles['train'],roles['calibration'],e.fixed_config()['matcher'])
            return {'status':'completed','value':matcher}
        assert name=='graph' and args==(matcher,roles['evaluation'],.6,10)
        return {'status':'completed','value':(graph,scores,{'software_fixture':True})}
    monkeypatch.setattr(engine,'bounded_stage',bounded)
    report=e.prepare(root=tmp_path)
    assert report['status']=='completed' and calls==[('matcher',900),('graph',600)]
    observed=e.s.read(out/'graph/observable.json')
    assert observed['nodes']==memberships['roles']['evaluation']['record_ids']
    assert e.s.read(out/'graph/evaluator_reference.json')['reference']=={r['record_id']:r['entity_id'] for r in roles['evaluation']}
    frozen=e.s.read(out/'repair_freeze.json')
    assert frozen['preparation_sha256']==e.s.digest(out/'preparation.json') and frozen['slots']==e.planned_slots()
    assert report['evaluation_nodes']==len(ids) and report['evaluation_edges']==0
    assert not (out/'completion_graph').exists()
    with pytest.raises(FileExistsError):e.prepare(root=tmp_path)
    assert len(calls)==2


def test_failed_matcher_stage_retains_failure_and_cannot_retry(tmp_path,monkeypatch):
    from scripts.new_domain import run as engine
    out,_,_=prepare_fixture(tmp_path,monkeypatch);calls=[]
    def bounded(name,args,seconds):
        calls.append(name);return {'status':'timeout','error':'constructed stage timeout'}
    monkeypatch.setattr(engine,'bounded_stage',bounded)
    with pytest.raises(ValueError,match='did not complete'):e.prepare(root=tmp_path)
    assert e.s.read(out/'preparation.json')['status']=='failed'
    assert e.s.read(out/'preparation_stages/matcher.json')['status']=='timeout'
    with pytest.raises(FileExistsError):e.prepare(root=tmp_path)
    assert calls==['matcher'] and not (out/'repair_freeze.json').exists()


def test_repair_run_delegates_unchanged_21_grid_and_checks_each_cell(tmp_path,monkeypatch):
    import networkx as nx
    import numpy as np
    from cut_audit_er.scores import PairScores
    from scripts.review_v4.replay import observable
    out=tmp_path/e.EXTERNAL;folder=out/'graph';folder.mkdir(parents=True)
    graph=nx.Graph();graph.add_nodes_from(['b','a'])
    scores=PairScores(('b','a'),np.eye(2))
    e.s.write(folder/'observable.json',observable(graph,scores))
    np.save(folder/'scores.npy',scores.matrix,allow_pickle=False)
    e.s.write(folder/'evaluator_reference.json',{'reference':{'b':'e0','a':'e1'}})
    e.s.write(out/'repair_freeze.json',{'fixture':True})
    checks=[];monkeypatch.setattr(e,'check_repair',lambda root:checks.append(root))
    for key,value in e.s.ENV.items():monkeypatch.setenv(key,value)
    def execute(path,phase,declared,assets,freeze,**kwargs):
        assert path==out/'study' and phase=='natural' and declared==e.planned_slots()
        assert freeze==e.s.digest(out/'repair_freeze.json')
        g,p,truth=assets[e.DATASET]
        assert list(g)==['b','a'] and list(p.ids)==['b','a'] and truth=={'b':'e0','a':'e1'}
        kwargs['before_cell']()
        return {'fixture_grid_checked':True}
    monkeypatch.setattr(e.s,'execute_grid',execute)
    assert e.run(root=tmp_path)=={'fixture_grid_checked':True}
    assert len(checks)==2
