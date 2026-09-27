"""Public replay and ordering checks on constructed graphs, not benchmark results."""
from copy import deepcopy
import json
import inspect
import networkx as nx
import numpy as np
import pytest
from cut_audit_er.audit import run_audit
from cut_audit_er.scores import PairScores
from scripts.review_v4.replay import (observable,graph_from_observable,run_trace,
    write_bundle,check_bundle,digest)

def fixture():
    g=nx.Graph();g.add_nodes_from(['z','a','c','b','isolate'])
    g.add_edges_from([('z','b'),('z','a'),('a','c'),('b','c')])
    ids=tuple(g); matrix=np.full((5,5),.3);np.fill_diagonal(matrix,1.)
    for u,v in g.edges:g.edges[u,v]['p']=.3
    truth={'z':'A','a':'A','c':'B','b':'B','isolate':'C'}
    return g,PairScores(ids,matrix),truth

@pytest.mark.parametrize('method',['edge_betweenness','cut_plan_fixed','cut_plan_fixed_singleton'])
def test_alias_export_preserves_every_trace_and_metrics(tmp_path,method):
    g,s,t=fixture(); run=run_audit(g,s,t,method,4,match_threshold=.6)
    report=write_bundle(tmp_path/'bundle',g,s,[('case',run)],t,label='synthetic_correctness',source_hashes={})
    assert report['status']=='PASS'
    assert check_bundle(tmp_path/'bundle')['new_oracle_answers']==0
    data=(tmp_path/'bundle/observable.json').read_text()
    assert 'isolate' not in data
    assert 'truth' not in inspect.signature(run_trace).parameters

def test_ordered_roundtrip_preserves_nodes_adjacency_and_isolates():
    g,s,_=fixture(); data=observable(g,s)
    h,loaded=graph_from_observable(data,s.matrix)
    assert list(h)==list(g)
    assert [list(h.adj[u]) for u in h]==[list(g.adj[u]) for u in g]
    assert loaded.ids==s.ids
    assert loaded.matrix.tobytes()==s.matrix.tobytes()
    bad=deepcopy(data);bad['adjacency'][0][1].pop()
    with pytest.raises(ValueError,match='Asymmetric adjacency'):graph_from_observable(bad,s.matrix)

def test_alias_that_changes_lexical_ties_rejected():
    g,s,_=fixture();names=list(g)
    aliases={n:str(i) for i,n in enumerate(reversed(sorted(g)))}
    with pytest.raises(ValueError,match='lexical'):observable(g,s,aliases)

def test_recorded_answer_gap_and_stop_mismatch_rejected():
    g,s,t=fixture();run=run_audit(g,s,t,'cut_plan_fixed',4,match_threshold=.6)
    bad=deepcopy(run);bad['decisions'][0]['spent']=7
    with pytest.raises(ValueError,match='gap'):run_trace(g,s,bad)
    bad=deepcopy(run);bad['decisions']=bad['decisions'][:-1]
    with pytest.raises((ValueError,AssertionError)):run_trace(g,s,bad)
    bad=deepcopy(run);bad['score_accesses']+=1
    with pytest.raises(AssertionError,match='logical'):run_trace(g,s,bad)

def test_hash_mismatch_rejected_before_replay(tmp_path):
    g,s,t=fixture();run=run_audit(g,s,t,'edge_betweenness',4,match_threshold=.6)
    write_bundle(tmp_path/'b',g,s,[('case',run)],t,label='synthetic_correctness',source_hashes={})
    p=tmp_path/'b/scores.npy';p.write_bytes(p.read_bytes()+b'X')
    with pytest.raises(ValueError,match='hash'):check_bundle(tmp_path/'b')

def test_reference_cannot_rescue_missing_paid_answers(tmp_path):
    g,s,t=fixture();run=run_audit(g,s,t,'cut_plan_fixed_singleton',4,match_threshold=.6)
    write_bundle(tmp_path/'b',g,s,[('case',run)],t,label='synthetic_correctness',source_hashes={})
    path=tmp_path/'b/paid_cases.json';cases=json.loads(path.read_text())
    cases[0]['run']['decisions']=[];path.write_text(json.dumps(cases))
    manifest=tmp_path/'b/manifest.json';value=json.loads(manifest.read_text())
    value['files_sha256']['paid_cases.json']=digest(path);manifest.write_text(json.dumps(value))
    with pytest.raises(AssertionError,match='unrecorded'):check_bundle(tmp_path/'b')


def rewrite_cases(folder, change):
    path=folder/'paid_cases.json'; cases=json.loads(path.read_text())
    change(cases); path.write_text(json.dumps(cases))
    path=folder/'manifest.json'; manifest=json.loads(path.read_text())
    manifest['files_sha256']['paid_cases.json']=digest(folder/'paid_cases.json')
    path.write_text(json.dumps(manifest))


@pytest.mark.parametrize('mutation', ['empty','short','extra','spent','initial','final','reduction','secondary'])
def test_complete_metric_ledger_required(tmp_path,mutation):
    g,s,t=fixture(); run=run_audit(g,s,t,'edge_betweenness',4,match_threshold=.6)
    folder=tmp_path/'b'; write_bundle(folder,g,s,[('case',run)],t,label='fixture',source_hashes={})
    def change(cases):
        r=cases[0]['run']
        if mutation=='empty': r['trace']=[]
        elif mutation=='short': r['trace'].pop()
        elif mutation=='extra': r['trace'].append(deepcopy(r['trace'][-1]))
        elif mutation=='spent': r['trace'][1]['spent']=77
        elif mutation=='initial': r['initial']['fp']+=1
        elif mutation=='final': r['final']['fn']+=1
        elif mutation=='reduction': r['loss_reduction']+=1
        else: r['trace'][1]['precision']+=.2
    rewrite_cases(folder,change)
    with pytest.raises(AssertionError,match='Offline'):check_bundle(folder)


@pytest.mark.parametrize('name',['observable.json','scores.npy','paid_cases.json','evaluator_reference.json'])
def test_every_required_payload_must_be_hash_pinned(tmp_path,name):
    g,s,t=fixture();run=run_audit(g,s,t,'edge_betweenness',4,match_threshold=.6)
    folder=tmp_path/'b';write_bundle(folder,g,s,[('case',run)],t,label='fixture',source_hashes={})
    path=folder/'manifest.json'; manifest=json.loads(path.read_text())
    del manifest['files_sha256'][name];path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='four payload'):check_bundle(folder)


def test_case_count_and_duplicate_identity_rejected(tmp_path):
    g,s,t=fixture();run=run_audit(g,s,t,'edge_betweenness',4,match_threshold=.6)
    folder=tmp_path/'b';write_bundle(folder,g,s,[('case',run)],t,label='fixture',source_hashes={})
    path=folder/'manifest.json';manifest=json.loads(path.read_text())
    manifest['cases']=2;path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='case count'):check_bundle(folder)
    rewrite_cases(folder,lambda cases:cases.append(deepcopy(cases[0])))
    with pytest.raises(ValueError,match='unique case'):check_bundle(folder)
    with pytest.raises(ValueError,match='unique strings'):
        write_bundle(tmp_path/'duplicate',g,s,[('same',run),('same',run)],t,label='fixture',source_hashes={})


def test_every_row_of_committed_batch_has_same_metadata():
    g,s,t=fixture();run=run_audit(g,s,t,'cut_plan_fixed',4,match_threshold=.6)
    assert run['decisions'][0]['batch']==run['decisions'][1]['batch']
    bad=deepcopy(run)
    bad['decisions'][1]['selection_info']=deepcopy(bad['decisions'][1]['selection_info'])
    bad['decisions'][1]['selection_info']['planned_depth']=77
    with pytest.raises(AssertionError,match='metadata'):run_trace(g,s,bad)


@pytest.mark.parametrize('method',['edge_betweenness','cut_plan_fixed','cut_plan_fixed_singleton'])
def test_changed_evaluator_gold_keeps_full_replay_without_oracle(tmp_path,monkeypatch,method):
    from cut_audit_er.metrics import evaluate
    from cut_audit_er.oracle import BudgetedOracle
    g,s,t=fixture();run=run_audit(g,s,t,method,4,match_threshold=.6)
    def forbidden(*args,**kwargs):raise AssertionError('Replay called an oracle')
    monkeypatch.setattr(BudgetedOracle,'query',forbidden)
    changed=deepcopy(run);other_truth={n:'same_entity' for n in g}
    h=g.copy(); changed['trace']=[{'spent':0,**evaluate(h,other_truth)}]
    for d in changed['decisions']:
        if not d['observed_match']:h.remove_edge(*d['pair'])
        changed['trace'].append({'spent':d['spent'],**evaluate(h,other_truth)})
    changed.update(initial=changed['trace'][0],final=changed['trace'][-1],
                   loss_reduction=changed['trace'][0]['loss']-changed['trace'][-1]['loss'])
    assert changed['initial']['fp']!=run['initial']['fp']
    assert changed['decisions']==run['decisions']
    assert run_trace(g,s,changed)==run_trace(g,s,run)
    for name,r,truth in [('original',run,t),('changed_evaluator',changed,other_truth)]:
        write_bundle(tmp_path/name,g,s,[(method,r)],truth,label='gold_isolation_fixture',source_hashes={})
        assert check_bundle(tmp_path/name)['new_oracle_answers']==0
