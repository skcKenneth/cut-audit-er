"""Public replay fixtures; no downloads, fitting or formal acquisitions."""
from copy import deepcopy
import json
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

from cut_audit_er.audit import run_audit
from cut_audit_er.oracle import BudgetedOracle
from cut_audit_er.scores import PairScores
from scripts.review_v5 import public_replay as p, study as s


def fixture(method='cut_plan_cover_fixed',budget=3):
    graph=nx.Graph();graph.add_nodes_from(['private-isolate','private-d','private-c','private-b','private-a'])
    graph.add_edges_from([('private-d','private-c'),('private-c','private-a'),
                          ('private-a','private-b'),('private-b','private-c')])
    ids=tuple(sorted(graph));matrix=np.full((len(ids),len(ids)),.1);np.fill_diagonal(matrix,1.)
    for u,v in graph.edges:graph.edges[u,v]['p']=.1
    scores=PairScores(ids,matrix);truth={node:node for node in graph}
    run=run_audit(graph,scores,truth,method,budget)
    case={'id':'fixture_case','graph':'dblp_exposed','method':method,'budget':budget,'status':'completed',
          'paid_lower_bound':run['spent'],'paid_upper_bound':run['spent'],'run':run}
    return graph,scores,truth,case


def write(tmp_path,method='cut_plan_cover_fixed',budget=3):
    graph,scores,truth,case=fixture(method,budget)
    out=tmp_path/'bundle'
    p.write_bundle(out,{'dblp_exposed':(graph,scores)},[case],{'dblp_exposed':{'natural':truth}},
                   kind='dblp',label='software fixture',source_hashes={'fixture':'0'*64})
    return out,graph,scores,truth,case


def rehash(folder,name):
    manifest=p.read(folder/'manifest.json');manifest['files_sha256'][name]=p.digest(folder/name)
    (folder/'manifest.json').write_bytes(s.blob(manifest))


@pytest.mark.parametrize('method',s.NATURAL_METHODS)
def test_full_alias_trace_and_no_oracle_access(tmp_path,monkeypatch,method):
    graph,scores,truth,case=fixture(method)
    monkeypatch.setattr(BudgetedOracle,'query',lambda *a:pytest.fail('Public replay bought an answer'))
    out=tmp_path/'bundle'
    manifest=p.write_bundle(out,{'dblp_exposed':(graph,scores)},[case],{'dblp_exposed':{'natural':truth}},
                            kind='dblp',label='fixture',source_hashes={'source':'1'*64})
    result=p.check_bundle(out)
    assert result['completed_cases']==1 and result['new_oracle_answers']==0
    assert result['recorded_paid_answers']==case['paid_lower_bound']
    assert manifest['counts']['planned_cases']==1
    for path in out.rglob('*.json'):
        assert b'private-' not in path.read_bytes()
    observed=p.read(out/'graphs/dblp_exposed/observable.json')
    assert observed['nodes'][0]=='r000004' # Insertion-order isolate preserved.
    assert observed['score_ids']==sorted(observed['score_ids'])


def test_prefix_and_never_started_case_remain_missing(tmp_path):
    graph,scores,truth,case=fixture(budget=3)
    prefix=deepcopy(case);prefix.update(status='timeout',paid_lower_bound=2,paid_upper_bound=3)
    prefix['run']['decisions']=prefix['run']['decisions'][:2]
    prefix['run']['trace']=prefix['run']['trace'][:3]
    missing={**case,'id':'unstarted','status':'not_started_limit','paid_lower_bound':0,'paid_upper_bound':0,'run':None}
    out=tmp_path/'bundle'
    p.write_bundle(out,{'dblp_exposed':(graph,scores)},[prefix,missing],{'dblp_exposed':{'natural':truth}},
                   kind='dblp',label='fixture',source_hashes={'source':'1'*64})
    report=p.check_bundle(out)
    assert report['planned_cases']==report['missing_cases']==2 and report['completed_cases']==0
    assert report['prefix_cases']==1 and report['paid_lower_bound']==2 and report['paid_upper_bound']==3
    cases=p.read(out/'cases.json')
    assert cases[0]['expected']['stop_reason']=='recorded_prefix_only'
    assert cases[0]['expected']['batches'][-1]['batch_fully_recorded'] is False


def test_missing_complete_answer_cannot_be_filled_from_reference(tmp_path):
    graph,scores,truth,case=fixture(budget=3)
    case['run']['decisions']=case['run']['decisions'][:-1]
    with pytest.raises(ValueError,match='unrecorded|Paid action|cost/stop'):
        p.write_bundle(tmp_path/'bad',{'dblp_exposed':(graph,scores)},[case],
                       {'dblp_exposed':{'natural':truth}},kind='dblp',label='fixture',source_hashes={'source':'1'*64})
    assert not (tmp_path/'bad').exists()


def test_evaluator_never_changes_selector_and_is_checked_afterwards(tmp_path):
    out,*_=write(tmp_path)
    evaluation=p.read(out/'evaluator_reference.json')
    evaluation['references']['dblp_exposed']['natural']={k:'same' for k in evaluation['references']['dblp_exposed']['natural']}
    (out/'evaluator_reference.json').write_bytes(s.blob(evaluation));rehash(out,'evaluator_reference.json')
    assert p.check_bundle(out,evaluate=False)['status']=='PASS'
    with pytest.raises(ValueError,match='fixed paid answer|metrics differ'):
        p.check_bundle(out)


@pytest.mark.parametrize('mutation',['corrupt','unlisted','traversal','candidate','metric'])
def test_integrity_and_semantic_tampering_rejected(tmp_path,mutation):
    out,*_=write(tmp_path)
    if mutation=='corrupt':
        with (out/'cases.json').open('ab') as stream:stream.write(b' ')
    elif mutation=='unlisted':
        (out/'private.txt').write_text('not allowed')
    elif mutation=='traversal':
        manifest=p.read(out/'manifest.json');manifest['files_sha256']['../outside.json']='0'*64
        (out/'manifest.json').write_bytes(s.blob(manifest))
    elif mutation=='candidate':
        cases=p.read(out/'cases.json');cases[0]['expected']['batches'][0]['planned_action']=[]
        (out/'cases.json').write_bytes(s.blob(cases));rehash(out,'cases.json')
    else:
        values=p.read(out/'evaluator_reference.json');values['cases']['fixture_case']['natural']['final']['loss']+=1
        (out/'evaluator_reference.json').write_bytes(s.blob(values));rehash(out,'evaluator_reference.json')
    with pytest.raises(ValueError):p.check_bundle(out)


@pytest.mark.parametrize('key',['wdc','alaska','raw_records','../dblp_exposed'])
def test_forbidden_graph_families_cannot_export(tmp_path,key):
    graph,scores,truth,case=fixture()
    with pytest.raises(ValueError,match='Only declared'):
        p.write_bundle(tmp_path/'bundle',{key:(graph,scores)},[],{key:{'natural':truth}},
                       kind='dblp',label='fixture',source_hashes={'source':'1'*64})


def test_synthetic_reuses_one_trace_under_two_references(tmp_path):
    graph=nx.path_graph(['r0','r1','r2']);scores=PairScores(tuple(graph),np.full((3,3),.1))
    for u,v in graph.edges:graph.edges[u,v]['p']=.1
    h0={'r0':'a','r1':'b','r2':'c'};h9={'r0':'a','r1':'b','r2':'a'}
    run=run_audit(graph,scores,h0,'cut_plan_cover_fixed',2)
    case={'id':'synthetic_fixture','graph':'k1_uniform','method':run['method'],'budget':2,
          'status':'completed','paid_lower_bound':2,'paid_upper_bound':2,'run':run}
    out=tmp_path/'bundle'
    p.write_bundle(out,{'k1_uniform':(graph,scores)},[case],{'k1_uniform':{'H0':h0,'H9':h9}},
                   kind='synthetic',label='fixture',source_hashes={'source':'1'*64})
    report=p.check_bundle(out);assert report['recorded_paid_answers']==2 and report['planned_cases']==1
    evaluation=p.read(out/'evaluator_reference.json')['cases']['synthetic_fixture']
    assert set(evaluation)=={'H0','H9'} and evaluation['H9']['final']['fn']==1


def test_existing_bundle_preserved(tmp_path):
    out,graph,scores,truth,case=write(tmp_path)
    before={p.name:p.read_bytes() for p in out.iterdir() if p.is_file()}
    with pytest.raises(ValueError,match='Fresh'):
        p.write_bundle(out,{'dblp_exposed':(graph,scores)},[case],{'dblp_exposed':{'natural':truth}},
                       kind='dblp',label='fixture',source_hashes={'source':'1'*64})
    assert before=={p.name:p.read_bytes() for p in out.iterdir() if p.is_file()}


def test_source_endpoint_disagreement_is_not_hidden_by_replay(tmp_path):
    graph,scores,truth,case=fixture()
    case=deepcopy(case);case['run']['final']=dict(case['run']['final'])
    case['run']['final']['loss']+=1
    with pytest.raises(ValueError,match='Source final metrics'):
        p.write_bundle(tmp_path/'bundle',{'dblp_exposed':(graph,scores)},[case],
                       {'dblp_exposed':{'natural':truth}},kind='dblp',label='fixture',source_hashes={'source':'1'*64})


@pytest.mark.parametrize('method',s.NATURAL_METHODS)
def test_compact_one_case_layout_preserves_full_trace_hash(tmp_path,monkeypatch,method):
    import hashlib
    original,*_=write(tmp_path,method)
    expected=p.read(original/'cases.json')[0]['expected']
    pin=hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    compact=tmp_path/'compact';receipt=p.compact_bundle(original,compact)
    assert original.exists() and receipt['selector_reexecution_during_transform'] is False
    rows=p.read(compact/'cases.json');case=p.read(compact/rows[0]['case_file'])
    assert rows[0]['expected_sha256']==case['expected_sha256']==pin
    assert 'expected' not in case and rows[0]['has_run'] and receipt['compact_bytes']<receipt['original_bytes']
    monkeypatch.setattr(BudgetedOracle,'query',lambda *a:pytest.fail('Compact replay bought an answer'))
    assert p.check_bundle(compact)['status']=='PASS'
    assert p.read(compact/'manifest.json')['compaction']['original_cases_sha256']==p.digest(original/'cases.json')


@pytest.mark.parametrize('mutation',['expected_hash','candidate','unlisted','path'])
def test_compact_corruption_or_whole_trace_change_is_rejected(tmp_path,mutation):
    original,*_=write(tmp_path);compact=tmp_path/'compact';p.compact_bundle(original,compact)
    rows=p.read(compact/'cases.json');name=rows[0]['case_file'];case=p.read(compact/name)
    if mutation=='expected_hash':
        case['expected_sha256']='1'*64
        p.compact_save(tmp_path/'modified.json',case);(compact/name).write_bytes((tmp_path/'modified.json').read_bytes());rehash(compact,name)
    elif mutation=='candidate':
        case['run']['decisions'][0]['selection_info']['candidate_trace']['scored_order']=[]
        (compact/name).write_bytes(s.blob(case));rehash(compact,name)
    elif mutation=='unlisted':(compact/'extra.json').write_text('{}')
    else:
        rows[0]['case_file']='../outside.json';(compact/'cases.json').write_bytes(s.blob(rows));rehash(compact,'cases.json')
    with pytest.raises(ValueError):p.check_bundle(compact)


def test_compact_prefix_and_missing_inventory_are_preserved(tmp_path):
    graph,scores,truth,case=fixture(budget=3)
    prefix=deepcopy(case);prefix.update(status='timeout',paid_lower_bound=2,paid_upper_bound=3)
    prefix['run']['decisions']=prefix['run']['decisions'][:2];prefix['run']['trace']=prefix['run']['trace'][:3]
    missing={**case,'id':'unstarted','status':'not_started_limit','paid_lower_bound':0,'paid_upper_bound':0,'run':None}
    original=tmp_path/'original'
    p.write_bundle(original,{'dblp_exposed':(graph,scores)},[prefix,missing],{'dblp_exposed':{'natural':truth}},
                   kind='dblp',label='fixture',source_hashes={'source':'1'*64})
    compact=tmp_path/'compact';p.compact_bundle(original,compact);result=p.check_bundle(compact)
    assert result['planned_cases']==result['missing_cases']==2 and result['prefix_cases']==1
    assert result['paid_lower_bound']==2 and result['paid_upper_bound']==3


def test_stream_array_handles_small_chunks_and_escaped_strings(tmp_path):
    value=[{'x':'escaped \\" quote\n漢字', 'values':list(range(20))},{'second':False},{}]
    path=tmp_path/'array.json';path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    assert list(p.iter_json_array(path,chunk_size=7))==value
    path.write_text('[{},]',encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):list(p.iter_json_array(path,chunk_size=2))


def test_semantic_hash_covers_candidate_order_float_and_intermediate_state():
    import math
    graph,scores,_,case=fixture();value=p.a.semantic(p.a.visible_replay(graph,scores,p.visible_run(case['run'],True),complete=True))
    base=p.semantic_hash(value)
    for key in ('cost','state','float'):
        changed=deepcopy(value)
        if key=='cost':changed['logical_score_accesses']+=1
        elif key=='state':changed['states'][0]['partition'].reverse()
        else:changed['batches'][0]['selection_info']['selected_proxy_score']=math.nextafter(changed['batches'][0]['selection_info']['selected_proxy_score'],math.inf)
        assert p.semantic_hash(changed)!=base


def test_compact_replay_rejects_changed_intermediate_trace_with_identical_final_loss(tmp_path):
    original,*_=write(tmp_path);cases=p.read(original/'cases.json')
    # Final loss/events/costs stay identical; the full intermediate expectation differs.
    cases[0]['expected']['states'][0]['partition'].reverse()
    (original/'cases.json').write_bytes(s.blob(cases));rehash(original,'cases.json')
    compact=tmp_path/'compact';p.compact_bundle(original,compact)
    with pytest.raises(ValueError,match='semantic replay hash differs'):p.check_bundle(compact)
