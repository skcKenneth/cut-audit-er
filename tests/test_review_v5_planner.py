"""V5 software fixtures only: no benchmark acquisition or hidden-data access."""
from fractions import Fraction
from itertools import combinations
import inspect
import json
from math import inf, nextafter
import os
from pathlib import Path
import subprocess
import sys

import networkx as nx
import numpy as np
import pytest

from cut_audit_er import covered_planner as cp
from cut_audit_er.audit import run_audit
from cut_audit_er.bounded_planner import completion_score
from cut_audit_er.graph import edge_key
from cut_audit_er.policies import DEFAULT_METHODS, METHODS, select_action
from cut_audit_er.scores import PairScores


def scores_for(g, value=.2):
    ids = tuple(sorted(g))
    matrix = np.full((len(ids), len(ids)), value)
    np.fill_diagonal(matrix, 1.)
    for u, v in g.edges:
        g.edges[u, v]['p'] = value
    return PairScores(ids, matrix)


def choose(g, scores, method='cut_plan_cover_fixed', budget=4, verified=None, observations=None, state=None):
    return select_action(g, scores, verified or set(), budget, method,
                         np.random.default_rng(7), observations=observations, policy_state=state)


def independent_bonds(g, verified=(), depth=4):
    nodes = tuple(sorted(g)); answer = set()
    for mask in range(1 << (len(nodes)-1)):
        left = {nodes[0]} | {nodes[i+1] for i in range(len(nodes)-1) if mask & (1 << i)}
        right = set(nodes)-left
        if not right or not nx.is_connected(g.subgraph(left)) or not nx.is_connected(g.subgraph(right)):
            continue
        edges = tuple(sorted(edge_key(u, v) for u, v in g.edges if (u in left) != (v in left)))
        if 0 < len(edges) <= depth and not set(edges).intersection(verified):
            answer.add(edges)
    return answer


def test_enumeration_matches_independent_bipartitions_all_four_node_graphs():
    nodes = list('abcd'); edges = list(combinations(nodes, 2))
    for mask in range(1 << len(edges)):
        g = nx.Graph(); g.add_nodes_from(nodes)
        g.add_edges_from(e for i, e in enumerate(edges) if mask & (1 << i))
        if not nx.is_connected(g):
            continue
        for depth in (1, 2, 4):
            verified = {edges[0]} if g.has_edge(*edges[0]) else set()
            actual, info = cp.enumerate_visible_bonds(g, verified, depth)
            assert set(actual) == independent_bonds(g, verified, depth)
            assert info['status'] == 'complete'


def test_enumeration_limit_is_per_component_and_oversized_explicit():
    g = nx.cycle_graph([f'n{i:02}' for i in range(16)])
    plans, info = cp.enumerate_visible_bonds(g, set(), 4)
    assert info['enumerated_subsets'] == 2516 and len(plans) == 120
    g.add_node('extra'); g.add_edge('extra', 'n00')
    plans, info = cp.enumerate_visible_bonds(g, set(), 4)
    assert not plans and info['status'] == 'oversized_not_enumerated'
    assert info['enumerated_subsets'] == 0
    two = nx.disjoint_union(nx.cycle_graph(4), nx.cycle_graph(4))
    two = nx.relabel_nodes(two, str)
    pool = cp.build_cover_pool(two, scores_for(two), set(), 4, include_exact=True)
    assert pool.info['enumerated_subsets'] == 30
    assert pool.info['full_graph_bond_pool_complete'] and pool.info['global_enumeration_cap'] is None


def test_opt_in_only_and_no_hidden_arguments():
    assert len(DEFAULT_METHODS) == 16
    assert all(name in METHODS and name not in DEFAULT_METHODS for name in cp.COVER_METHODS)
    for function in (cp.select_covered_plan, cp.build_cover_pool, cp.completion_upper_bound):
        assert not {'truth', 'gold', 'labels', 'headroom'} & set(inspect.signature(function).parameters)


@pytest.mark.parametrize('method', cp.COVER_METHODS)
def test_budget_and_committed_positive_batch(method):
    g = nx.cycle_graph(list('abc'))
    scores = scores_for(g, .1)
    run = run_audit(g, scores, {n: 'one' for n in g}, method, 2)
    assert run['spent'] == 2 and all(d['observed_match'] for d in run['decisions'])
    assert run['initial']['n_edges'] == run['final']['n_edges'] == 3
    if method != 'cut_plan_cover_singleton':
        assert [d['batch'] for d in run['decisions']] == [1, 1]
    assert choose(g, scores.copy(), method, budget=0)[0] is None
    action, _ = choose(g, scores.copy(), method, budget=1)
    assert len(action) == 1


@pytest.mark.parametrize('method', cp.COVER_METHODS)
def test_negative_non_split_then_split_and_paid_gold_isolation(method):
    # Two references agree on every original graph edge but differ on nonedges.
    g = nx.path_graph(list('abc'))
    scores = scores_for(g, .1)
    first = run_audit(g, scores, {'a':'a', 'b':'b', 'c':'c'}, method, 2)
    second = run_audit(g, scores, {'a':'same', 'b':'b', 'c':'same'}, method, 2)
    assert [(x['pair'], x['observed_match']) for x in first['decisions']] == [
        (x['pair'], x['observed_match']) for x in second['decisions']]
    assert [x['selection_info']['candidate_trace'] for x in first['decisions']] == [
        x['selection_info']['candidate_trace'] for x in second['decisions']]
    triangle = nx.cycle_graph(list('abc'))
    run = run_audit(triangle, scores_for(triangle, .1), {n:n for n in triangle}, method, 2)
    assert run['trace'][0]['n_components'] == run['trace'][1]['n_components']
    assert run['trace'][2]['n_components'] > run['trace'][1]['n_components']


def test_singleton_filter_precedes_ub_and_does_not_save_generation():
    g = nx.cycle_graph(list('abc')); g.add_edge('x', 'y')
    scores = scores_for(g)
    _, full = choose(g, scores.copy())
    _, single = choose(g, scores.copy(), 'cut_plan_cover_singleton')
    for stage in ('legacy_generated', 'enumerated', 'union_generated', 'validated_order'):
        assert full['candidate_trace'][stage] == single['candidate_trace'][stage]
    assert single['bound_evaluations'] == 1
    assert all(len(x['edges']) == 1 for x in single['candidate_trace']['bound_records'])
    assert single['enumerated_subsets'] == full['enumerated_subsets']
    assert single['candidate_trace']['capped_order'] == single['candidate_trace']['union_generated']
    assert single['cap_applied'] is False and single['candidate_truncated'] == 0


def test_score_limit_keeps_positive_uncertified_incumbent_and_tie_order():
    g = nx.Graph(); g.add_edges_from((f'a{i:03}', f'b{i:03}') for i in range(70))
    action, info = choose(g, scores_for(g, .2))
    assert action == (('a000', 'b000'),)
    assert info['scored_candidate_actions'] == 64 and info['score_limit_unscored'] == 6
    assert not info['surrogate_argmax_certified']
    assert info['surrogate_certificate_status'] == 'score_limit_uncertified'
    assert 'fallback' not in info
    assert len(info['candidate_trace']['capped_order']) == 70
    assert len(info['candidate_trace']['evaluation_prefix_order']) == 64


def test_strict_certificate_stops_early_but_equality_does_not(monkeypatch):
    g = nx.Graph(); g.add_edges_from([('a','b'), ('c','d')])
    scores = scores_for(g, 1.)
    matrix = scores.matrix.copy(); matrix[0,1] = matrix[1,0] = 0.
    action, info = choose(g, PairScores(scores.ids, matrix))
    assert action == (('a','b'),) and info['scored_candidate_actions'] == 1
    assert info['surrogate_certificate_status'] == 'strict_upper_bound_separation'
    # Equality cannot certify unseen ties: the second score must be visited.
    monkeypatch.setattr(cp, 'completion_upper_bound', lambda *args: (1., {'upper_bound':1.}))
    monkeypatch.setattr(cp, 'completion_score', lambda *args: (1., 1., 1.))
    _, info = choose(g, scores_for(g, .2))
    assert info['scored_candidate_actions'] == 2
    assert info['surrogate_certificate_status'] == 'all_searched_candidates_scored'


def test_certified_choices_match_independent_full_scoring_including_large_pool_and_near_ties():
    fixtures = []
    for graph in (nx.path_graph(list('abcde')), nx.cycle_graph(list('abcde')),
                  nx.complete_graph(list('abcd'))):
        fixtures.append((graph, scores_for(graph, .1)))
    many = nx.Graph(); many.add_edges_from((f'a{i:03}',f'b{i:03}') for i in range(70))
    score = scores_for(many, 1.)
    matrix = score.matrix.copy(); u,v = (score.index[n] for n in ('a000','b000'))
    matrix[u,v] = matrix[v,u] = .1
    fixtures.append((many,PairScores(score.ids,matrix)))
    # Real score operations at adjacent representable probabilities, not a
    # mocked comparison: full scoring supplies the exact existing tie key.
    near = nx.Graph(); near.add_edges_from([('a','b'),('c','d'),('e','f')])
    score = scores_for(near,.5); matrix = score.matrix.copy()
    matrix[0,1] = matrix[1,0] = np.nextafter(.5,1.)
    matrix[4,5] = matrix[5,4] = np.nextafter(.5,0.)
    fixtures.append((near,PairScores(score.ids,matrix)))
    certified = early_large = 0
    for graph,scores in fixtures:
        for method in ('cut_plan_bound_fixed','cut_plan_cover_fixed','cut_plan_cover_singleton'):
            action,info = choose(graph,scores.copy(),method)
            pool = cp.build_cover_pool(graph,scores.copy(),set(),4,
                                       include_exact=method!='cut_plan_bound_fixed')
            eligible = [p for p in pool.raw if p in pool.partitions
                        and (method!='cut_plan_cover_singleton' or len(p)==1)]
            scorer = scores.copy()
            ranked = [(completion_score(p,pool.partitions[p],scorer,pool.probabilities,{},1.)[0],p)
                      for p in eligible]
            if info['surrogate_argmax_certified'] and ranked:
                value,plan = min(ranked,key=lambda row:(-row[0],len(row[1]),row[1]))
                assert value == info['selected_proxy_score']
                if value>0:
                    assert action == tuple(sorted(plan,key=lambda e:(-pool.probabilities[e],e)))
                certified += 1
                early_large += len(eligible)>64 and info['scored_candidate_actions']<64
    assert certified>=9 and early_large==3


def test_bc_cap_truncates_raw_before_validation_without_refill(monkeypatch):
    g = nx.Graph(); g.add_edge('x','y'); scores = scores_for(g)
    invalid = [((f'a{i:03}', f'b{i:03}'),) for i in range(64)]
    valid = (('x','y'),); raw = tuple(invalid + [valid])
    weighted = {p[0]: 2. for p in invalid}; weighted[valid[0]] = 1.
    fake = cp.CoverPool(raw, {valid:(('x',),('y',))}, {valid[0]:.2}, weighted, {}, {})
    monkeypatch.setattr(cp, 'build_cover_pool', lambda *args, **kwargs: fake)
    action, info = choose(g, scores, 'cut_plan_cover_bccap')
    assert action == valid and info['scored_candidate_actions'] == 0
    assert info['cap_applied'] and info['candidate_truncated'] == 1
    assert info['candidate_trace']['capped_order'] == invalid
    assert info['surrogate_certificate_status'] == 'bc_cap_uncertified'
    assert info['fallback'] == 'error_weighted_edge_betweenness'
    assert info['fallback_trigger'] == 'empty_validated_pool'


def test_numeric_scan_charged_once_per_matrix_and_run_cache_is_private():
    g = nx.cycle_graph(list('abc')); scores = scores_for(g)
    state = {}; _, first = choose(g, scores, state=state)
    assert first['numeric_scan_score_entry_reads'] == 18
    assert scores.calls >= 18 and not first['numeric_scan_cache_hit']
    positive = ('a','b')
    action, second = choose(g, scores, state=state, verified={positive}, observations={positive:True})
    assert positive not in action
    assert second['numeric_scan_score_entry_reads'] == 0 and second['numeric_scan_cache_hit']
    assert second['topology_cache']['centrality_hits'] == 1
    g.remove_edge('b','c')
    _, changed = choose(g, scores, state=state, verified={positive}, observations={positive:True})
    assert changed['topology_cache']['centrality_misses'] == 1
    _, new_matrix = choose(g, scores.copy(), state=state)
    assert new_matrix['numeric_scan_score_entry_reads'] == 18
    _, other_run = choose(g, scores, state={})
    assert other_run['numeric_scan_score_entry_reads'] == 18


@pytest.mark.parametrize('profile, expected', [('uniform', .0702), ('ranked', .0624)])
def test_constructed_post_three_state_exposes_omitted_bond(profile, expected):
    # Reconstruct a declared fixture, without loading any saved result or gold.
    nodes = [f'r{i}' for i in range(9)]; g = nx.Graph(); g.add_nodes_from(nodes)
    matrix = np.full((9,9), .1); np.fill_diagonal(matrix, 1.)
    for offset in (0,3,6):
        for i,j in combinations(range(offset, offset+3), 2):
            g.add_edge(nodes[i], nodes[j]); matrix[i,j] = matrix[j,i] = .95
    for i in range(3):
        p = .7 if profile == 'uniform' else (.8,.7,.6)[i]
        matrix[i,i+3] = matrix[i+3,i] = p
        matrix[i+3,i+6] = matrix[i+6,i+3] = p
        g.add_edge(nodes[i+3], nodes[i+6])
    verified = {(f'r{i}',f'r{i+3}') for i in range(3)}
    observations = {e:False for e in sorted(verified)}
    scores = PairScores(nodes,matrix)
    raw, old = choose(g,scores.copy(),'cut_plan_fixed',3,verified,observations)
    chosen, info = choose(g,scores.copy(),'cut_plan_cover_fixed',3,verified,observations)
    target = (('r3','r6'),('r4','r7'),('r5','r8'))
    assert set(chosen) == set(target) and len(raw) == 2
    assert old['selected_proxy_score'] == pytest.approx(.0025)
    assert info['selected_proxy_score'] == pytest.approx(expected)
    trace = info['candidate_trace']
    assert target not in trace['legacy_generated'] and target in trace['enumerated']
    assert len(trace['legacy_generated']) == 8 and len(trace['validated_order']) == 10
    assert info['surrogate_argmax_certified']


@pytest.mark.parametrize('seed', range(8))
def test_upper_bound_covers_computed_scores_and_exact_linear_form(seed):
    rng = np.random.default_rng(seed)
    ids = tuple(f'n{i}' for i in range(10))
    matrix = rng.random((10,10)); matrix = (matrix+matrix.T)/2
    # Legal PairScores approximate asymmetry; orientation actually differs.
    matrix[0,6] += 2e-8
    scores = PairScores(ids,matrix)
    left,right = ids[:5], ids[5:]
    pairs = [edge_key(u,v) for u in left for v in right]
    plan = tuple(pairs[:4]); observations = {e:bool(i%2) for i,e in enumerate(pairs[4:])}
    probabilities = {e:scores.p(*e) for e in plan}
    delta, _ = cp._numeric_preprocessing(scores,{})
    for weight in (0.,1.,1e150):
        upper, info = cp.completion_upper_bound(plan,(right,left),probabilities,len(observations),weight,delta)
        actual,_,_ = completion_score(plan,(right,left),scores,probabilities,observations,weight)
        assert actual <= upper
        k = info['roundoff_k']
        assert Fraction.from_float(info['gamma_sum_error_upper']) >= Fraction(k*k,2**53-k)
        conditioned = dict(observations); conditioned.update({e:False for e in plan})
        exact = sum((Fraction.from_float(float(matrix[scores.index[u],scores.index[v]]))
                     for u in right for v in left), Fraction())
        exact += sum((int(a)-Fraction.from_float(scores.p(*e)) for e,a in conditioned.items()),Fraction())
        assert exact >= -Fraction.from_float(info['asymmetry_error_upper'])


@pytest.mark.parametrize('value', [0., nextafter(0.,1.), .1, nextafter(.5,0.), nextafter(1.,0.), 1.])
def test_endpoint_cancellation_zero_product_and_large_finite_weight(value):
    ids=('a','b','c','d'); matrix=np.full((4,4),value)
    scores=PairScores(ids,matrix); part=(ids[:2],ids[2:])
    plan=(('a','c'),('a','d'),('b','c'),('b','d'))
    probabilities={e:value for e in plan}
    for weight in (0.,1.,1e300):
        bound,info=cp.completion_upper_bound(plan,part,probabilities,0,weight)
        actual,utility,_=completion_score(plan,part,scores,probabilities,{},weight)
        assert np.isfinite(actual) and actual<=bound
        if value == 1.:
            assert info['computed_all_negative_product'] == bound == actual == 0.


def test_outward_underflow_and_invalid_numeric_inputs_fail_closed():
    tiny = nextafter(0.,1.)
    assert cp._mul_up(tiny,.5) == tiny
    assert Fraction.from_float(cp._up(tiny/4)) >= Fraction.from_float(tiny)/4
    plan=(('a','b'),); part=(('a',),('b',)); probs={plan[0]:.5}
    for weight in (-1.,inf,float('nan')):
        with pytest.raises(ValueError):
            cp.completion_upper_bound(plan,part,probs,0,weight)
    g=nx.path_graph(['a','b'])
    with pytest.raises(ValueError,match='verified'):
        choose(g,scores_for(g),observations={('a','b'):True})


def test_old_semantic_traces_and_logical_accesses_match_preserved_v4_in_separate_interpreters(tmp_path):
    root=Path(__file__).resolve().parents[1]
    before=root/'outputs/session_20260927_v5/before/src'
    if not (before/'cut_audit_er/audit.py').is_file():
        before=root/'historical/v4/src'
    # V6 preserves the complete V5 release one level below historical/v5.
    # Only this portable fixture path changes; assertions and engines do not.
    if not (before/'cut_audit_er/audit.py').is_file():
        before=root/'historical/v5/historical/v4/src'
    if not (before/'cut_audit_er/audit.py').is_file():
        pytest.skip('Preserved V4 source unavailable in workspace or historical/v4/src')
    script = r'''
import json
from itertools import combinations
import networkx as nx
import numpy as np
from cut_audit_er.audit import run_audit
from cut_audit_er.scores import PairScores
def logical(x):
 if isinstance(x,dict): return {k:logical(v) for k,v in x.items() if 'seconds' not in k and k!='batch_timings'}
 if isinstance(x,list): return [logical(v) for v in x]
 return x
out=[]
for case in range(4):
 g=nx.Graph();g.add_nodes_from(['isolate','f','e','d','c','b','a'])
 edges=list(combinations('abcdef',2)) if case==0 else [('a','b'),('b','c'),('c','a'),('c','d'),('d','e'),('e','f'),('f','d')]
 g.add_edges_from(reversed(edges) if case%2 else edges)
 ids=tuple(sorted(g));m=np.full((len(ids),len(ids)),[.1,.5,np.nextafter(.5,1.),.95][case]);np.fill_diagonal(m,1.)
 for u,v in g.edges:g.edges[u,v]['p']=float(m[ids.index(u),ids.index(v)])
 truth={n:'same' if n in 'abc' else n for n in g}
 for method in ('edge_betweenness','cut_plan_fixed','cut_plan_adaptive','cut_plan_fixed_singleton'):
  out.append(logical(run_audit(g,PairScores(ids,m),truth,method,6)))
print(json.dumps(out,sort_keys=True,allow_nan=False))
'''
    outputs=[]
    for source in (before,root/'src'):
        env=os.environ.copy(); env['PYTHONPATH']=str(source);env['PYTHONHASHSEED']='0'
        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):env[key]='1'
        process=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=45)
        assert process.returncode==0,process.stderr
        outputs.append(json.loads(process.stdout))
    assert outputs[0]==outputs[1]
