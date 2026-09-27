"""Independent structural checks; all fixtures are synthetic, never benchmark gold."""
from itertools import combinations, permutations, product
import json
import os
from pathlib import Path
import subprocess
import sys

import networkx as nx
import numpy as np
import pytest

import cut_audit_er.audit as audit_module
import cut_audit_er.bounded_planner as planner
from cut_audit_er.graph import edge_key
from cut_audit_er.policies import select_action
from cut_audit_er.scores import PairScores


def make_scores(graph, default=.17, overrides=None):
    ids = tuple(sorted(graph))
    matrix = np.full((len(ids), len(ids)), default)
    np.fill_diagonal(matrix, 1.)
    index = {v: i for i, v in enumerate(ids)}
    for (u, v), value in (overrides or {}).items():
        matrix[index[u], index[v]] = matrix[index[v], index[u]] = value
    for u, v in graph.edges:
        graph.edges[u, v]['p'] = float(matrix[index[u], index[v]])
    return PairScores(ids, matrix)


def clique_bridge_fixture():
    graph = nx.Graph()
    sides = tuple(tuple(f'{prefix}{i}' for i in range(4)) for prefix in ('a', 'b'))
    internal = {edge_key(u, v) for side in sides for u, v in combinations(side, 2)}
    cross = tuple((f'a{i}', f'b{i}') for i in range(3))
    graph.add_edges_from(sorted(internal) + list(cross))
    values = {edge: .95 for edge in internal}
    values.update(dict(zip(cross, (.8, .7, .6))))
    return graph, make_scores(graph, .1, values), internal, cross


def independent_outcome_expectation(graph, plan, scores, observations, fn_weight):
    """Enumerate full outcomes and pair connectivity, including proper deletions."""
    def raw_p(edge):
        return float(scores.matrix[scores.index[edge[0]], scores.index[edge[1]]])

    expectation = 0.
    for answers in product((False, True), repeat=len(plan)):
        weight = np.prod([raw_p(e) if answer else 1. - raw_p(e)
                          for e, answer in zip(plan, answers)])
        after = graph.copy()
        after.remove_edges_from(e for e, answer in zip(plan, answers) if not answer)
        evidence = dict(observations)
        evidence.update(zip(plan, answers))
        utility = 0.
        for pair in combinations(sorted(graph), 2):
            if nx.has_path(graph, *pair) and not nx.has_path(after, *pair):
                probability = float(evidence[pair]) if pair in evidence else raw_p(pair)
                utility += 1. - (1. + fn_weight) * probability
        expectation += float(weight) * utility
    return expectation / len(plan)


@pytest.mark.parametrize('graph', [nx.path_graph(4), nx.cycle_graph(4), nx.complete_graph(4)])
def test_bond_validator_matches_exhaustive_proper_subset_connectivity(graph):
    graph = nx.relabel_nodes(graph, {v: str(v) for v in graph})
    edges = tuple(sorted(edge_key(*e) for e in graph.edges))
    for width in range(1, min(4, len(edges)) + 1):
        for plan in combinations(edges, width):
            after = graph.copy()
            after.remove_edges_from(plan)
            minimal = not nx.is_connected(after)
            if minimal:
                for subset_width in range(width):
                    for subset in combinations(plan, subset_width):
                        partial = graph.copy()
                        partial.remove_edges_from(subset)
                        minimal = minimal and nx.is_connected(partial)
            result = planner.bond_partition(graph, plan)
            assert (result is not None) == minimal
            if result is not None:
                assert set(result[0]).isdisjoint(result[1])
                assert set(result[0]) | set(result[1]) == set(graph)


@pytest.mark.parametrize('width', [1, 2, 3, 4])
@pytest.mark.parametrize('fn_weight', [0., 1., 3.5])
def test_terminal_score_equals_full_outcome_enumeration_and_keeps_signed_fn(width, fn_weight):
    # Isolating vertex 0 in K_(width+1) is a bond of the requested width.
    graph = nx.complete_graph([str(v) for v in range(width + 1)])
    graph.add_node('outside')
    component = graph.subgraph(set(graph) - {'outside'}).copy()
    plan = tuple(edge_key('0', str(v)) for v in range(1, width + 1))
    values = {edge_key(*e): .12 + .07 * i for i, e in enumerate(sorted(graph.edges))}
    scores = make_scores(graph, .31, values)
    probabilities = {e: float(scores.matrix[scores.index[e[0]], scores.index[e[1]]]) for e in plan}
    # Disconnected observations must have no effect on this component's score.
    observations = {('0', 'outside'): False}
    partition = planner.bond_partition(component, plan)
    actual, _, _ = planner.completion_score(plan, partition, scores, probabilities,
                                            observations, fn_weight)
    expected = independent_outcome_expectation(graph, plan, scores, observations, fn_weight)
    assert actual == pytest.approx(expected, abs=1e-12)


def test_history_endpoint_correction_and_access_cost_include_only_newly_separated_pairs():
    graph = nx.Graph()
    graph.add_edges_from([('a0', 'a1'), ('a1', 'a2'), ('a0', 'a2'),
                          ('b0', 'b1'), ('b1', 'b2'), ('b0', 'b2'),
                          ('a0', 'b0'), ('a1', 'b1')])
    graph.add_node('outside')
    plan = (('a0', 'b0'), ('a1', 'b1'))
    values = {e: .99 for e in combinations(tuple(sorted(graph)), 2)}
    values.update({plan[0]: .2, plan[1]: .4})
    scores = make_scores(graph, overrides=values)
    matrix_before = scores.matrix.copy()
    observations = {('a2', 'b2'): False, ('a0', 'a1'): True, ('a0', 'outside'): False}
    component = graph.subgraph(set(graph) - {'outside'}).copy()
    partition = planner.bond_partition(component, plan)
    value, utility, success = planner.completion_score(plan, partition, scores,
                                                      {plan[0]: .2, plan[1]: .4},
                                                      observations, 2.)
    # Nine cross pairs: two planned negatives + one purchased negative leave six .99 terms.
    assert utility == pytest.approx(9. - 3. * 6. * .99)
    assert utility < 0 and value < 0  # FN damage must not be clipped away.
    assert success == pytest.approx(.8 * .6)
    assert value == pytest.approx(independent_outcome_expectation(graph, plan, scores, observations, 2.))
    assert scores.calls == 9 + 3  # cross_sum plus three crossing endpoint replacements.
    np.testing.assert_array_equal(scores.matrix, matrix_before)
    assert not scores.matrix.flags.writeable


def test_descending_positive_probability_minimizes_exact_stop_cost_over_all_orders():
    edges = (('a', 'b'), ('a', 'c'), ('a', 'd'), ('a', 'e'))
    probabilities = dict(zip(edges, (.0, .23, .78, .94)))
    costs = {}
    for order in permutations(edges):
        exact = 0.
        for answers in product((False, True), repeat=4):
            weight = np.prod([probabilities[e] if answer else 1. - probabilities[e]
                              for e, answer in zip(order, answers)])
            charged = next((i + 1 for i, answer in enumerate(answers) if answer), 4)
            exact += float(weight) * charged
        costs[order] = exact
        assert planner.expected_abort_cost(order, probabilities) == pytest.approx(exact)
    descending = tuple(sorted(edges, key=lambda e: (-probabilities[e], e)))
    assert costs[descending] == pytest.approx(min(costs.values()))


def test_purchased_positive_paths_block_every_cut_that_would_separate_them(monkeypatch):
    graph, scores, internal, cross = clique_bridge_fixture()
    call_capacities = []
    original_cut = nx.minimum_cut

    def inspect_cut(component, source, target, **kwargs):
        call_capacities.append({edge_key(*e): component.edges[e]['capacity'] for e in component.edges})
        return original_cut(component, source, target, **kwargs)

    monkeypatch.setattr(planner.nx, 'minimum_cut', inspect_cut)
    before_edges = dict((edge_key(*e), dict(graph.edges[e])) for e in graph.edges)
    plans, _, _, _, info = planner.build_plan_pool(graph, scores, internal, 4)
    assert tuple(sorted(cross)) in plans
    assert len(call_capacities) == info['flow_calls'] <= 16
    for capacities in call_capacities:
        assert all(capacities[e] == (5 if e in internal else 1) for e in capacities)
    protected = internal | {cross[0]}
    plans, _, _, _, info = planner.build_plan_pool(graph, scores, protected, 4)
    assert plans == []  # Purchased-positive paths already connect the entire component.
    assert info['flow_calls'] <= 16
    assert dict((edge_key(*e), dict(graph.edges[e])) for e in graph.edges) == before_edges


def test_pending_remainder_reserves_one_slot_even_when_it_loses_prerank():
    graph = nx.path_graph(['a', 'b', 'c', 'd'])
    scores = make_scores(graph, .4)
    pending = (('a', 'b'),)
    baseline, _, _, _, info0 = planner.build_plan_pool(graph, scores, set(), 2,
                                                       allow_long=False, max_plans=1)
    retained, _, _, _, info = planner.build_plan_pool(graph, scores, set(), 2,
                                                     allow_long=False, max_plans=1,
                                                     pending_plan=pending)
    assert baseline == [(('b', 'c'),)]
    assert retained == [pending]
    assert info['pending_remainder_retained'] is True
    assert info['candidate_actions'] == 1
    assert info['candidate_truncated'] == info0['candidate_truncated'] == 2


def test_negative_answer_retains_valid_remainder_and_positive_invalidates_it():
    graph, scores, internal, cross = clique_bridge_fixture()
    state = {}
    observations = {e: True for e in internal}
    first, info = planner.select_bounded_plan(graph, scores, internal, 3,
                                              'cut_plan_adaptive', observations, state)
    assert first == (cross[0],)
    assert tuple(map(tuple, info['planned_edges'])) == cross
    negative_graph = graph.copy()
    negative_graph.remove_edge(*first[0])
    negative_state = dict(state)
    q, negative_info = planner.select_bounded_plan(
        negative_graph, scores, internal | set(first), 2, 'cut_plan_adaptive',
        {**observations, first[0]: False}, negative_state)
    assert q == (cross[1],)
    assert negative_info['pending_remainder_retained'] is True
    assert negative_info['pending_transition'] == 'continued'
    assert tuple(map(tuple, negative_info['planned_edges'])) == cross[1:]
    q, positive_info = planner.select_bounded_plan(
        graph, scores, internal | set(first), 2, 'cut_plan_adaptive',
        {**observations, first[0]: True}, state)
    assert positive_info['previous_plan_invalidated_by_positive'] is True
    assert positive_info['pending_remainder_retained'] is False
    assert positive_info['pending_transition'] == 'invalidated_positive'
    assert first[0] not in q
    assert 'pending_plan' not in state


def test_fixed_and_adaptive_share_initial_plan_score_order_and_differ_only_in_returned_commitment():
    graph, scores, internal, cross = clique_bridge_fixture()
    observations = {e: True for e in internal}
    fixed, fi = planner.select_bounded_plan(graph, scores.copy(), internal, 3,
                                            'cut_plan_fixed', observations, {})
    adaptive, ai = planner.select_bounded_plan(graph, scores.copy(), internal, 3,
                                               'cut_plan_adaptive', observations, {})
    assert fixed == cross
    assert adaptive == fixed[:1]
    for field in ('selected_proxy_score', 'planned_edges', 'planned_depth',
                  'expected_fixed_plan_abort_cost', 'score_denominator'):
        assert fi[field] == ai[field]
    assert fi['replan_after_each_answer'] is False
    assert ai['replan_after_each_answer'] is True


@pytest.mark.parametrize('method', ['cut_plan_fixed', 'cut_plan_adaptive'])
def test_positive_answers_are_charged_and_leave_all_original_edges_present(method):
    graph, scores, _, cross = clique_bridge_fixture()
    original_edges = set(graph.edges)
    run = audit_module.run_audit(graph, scores, {v: 'one-entity' for v in graph}, method, 3)
    assert run['spent'] == 3 and len(run['decisions']) == 3
    assert all(d['observed_match'] is True for d in run['decisions'])
    assert all(row['loss'] == 0 for row in run['trace'])
    assert set(graph.edges) == original_edges
    if method == 'cut_plan_fixed':
        assert tuple(tuple(d['pair']) for d in run['decisions']) == cross
        assert {d['batch'] for d in run['decisions']} == {1}
    else:
        assert [d['batch'] for d in run['decisions']] == [1, 2, 3]
        assert run['decisions'][1]['selection_info']['previous_plan_invalidated_by_positive'] is True


def test_global_cap_bounds_scored_plans_and_tiny_budget_blocks_large_plans(monkeypatch):
    graph = nx.path_graph([f'v{i:03d}' for i in range(90)])
    scores = make_scores(graph, .4)
    calls = []
    score = planner.completion_score

    def count_score(*args, **kwargs):
        calls.append(args[0])
        return score(*args, **kwargs)

    monkeypatch.setattr(planner, 'completion_score', count_score)
    action, info = planner.select_bounded_plan(graph, scores, set(), 1,
                                               'cut_plan_fixed', {}, {})
    assert len(action) == 1
    assert len(calls) == info['candidate_actions'] == 64
    assert info['candidate_truncated'] == 89 - 64
    assert info['depth_cap'] == 1 and info['flow_calls'] == 0
    assert all(len(q) == 1 for q in calls)
    assert select_action(graph, scores, set(), 0, 'cut_plan_adaptive',
                         np.random.default_rng(7))[0] is None


def test_pool_is_reproducible_across_fresh_hash_seeds_and_input_set_orders():
    code = r'''
import json
import networkx as nx
import numpy as np
from cut_audit_er.bounded_planner import build_plan_pool
from cut_audit_er.scores import PairScores
nodes = {f'{s}{i}' for s in 'ab' for i in range(5)}
edges = {(u,v) for u in nodes for v in nodes if u<v and u[0]==v[0]}
edges |= {(f'a{i}',f'b{i}') for i in range(4)}
g = nx.Graph()
g.add_nodes_from(nodes)
g.add_edges_from(edges)
ids = tuple(sorted(nodes))
mat = np.array([[1. if u==v else .8 if u[0]==v[0] else .2 for v in ids] for u in ids])
scores = PairScores(ids,mat)
for u,v in g.edges: g.edges[u,v]['p'] = float(mat[ids.index(u),ids.index(v)])
plans,parts,probs,weighted,info = build_plan_pool(g,scores,set(),4)
info = {key:value for key,value in info.items() if not key.endswith('_seconds')}
print(json.dumps({'plans':plans,'partitions':[parts[q] for q in plans],'info':info},sort_keys=True))
'''
    results = []
    for seed in ('1', '913'):
        env = {**os.environ, 'PYTHONHASHSEED': seed, 'OMP_NUM_THREADS': '1',
               'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
        run = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True,
                             text=True, check=True, timeout=30,
                             cwd=Path(__file__).resolve().parents[1])
        results.append(json.loads(run.stdout))
    assert results[0] == results[1]
    assert 0 < results[0]['info']['flow_calls'] <= 16


@pytest.mark.parametrize('method', ['risk_seed_pool', 'cut_plan_depth2',
                                    'cut_plan_fixed', 'cut_plan_adaptive'])
def test_evaluation_gold_cannot_change_queries_when_paid_answer_stream_is_fixed(monkeypatch, method):
    graph, scores, _, cross = clique_bridge_fixture()
    answers = {edge_key(*e): edge_key(*e) not in set(cross) for e in graph.edges}

    class FixedPaidOracle:
        def __init__(self, evaluation_truth, budget, noise, seed):
            self.budget = budget
            self.spent = 0
            self.observed = {}

        @property
        def remaining(self):
            return self.budget - self.spent

        def query(self, u, v):
            edge = edge_key(u, v)
            assert self.remaining > 0 and edge not in self.observed
            self.spent += 1
            self.observed[edge] = answers[edge]
            return self.observed[edge]

    monkeypatch.setattr(audit_module, 'BudgetedOracle', FixedPaidOracle)
    results = [audit_module.run_audit(graph, scores, truth, method, 3)
               for truth in ({v: 'all-one-entity' for v in graph}, {v: v for v in graph})]
    comparable = lambda run: [(d['pair'], d['observed_match'], d['batch'],
                               {k: v for k, v in d['selection_info'].items() if not k.endswith('_seconds')})
                               for d in run['decisions']]
    assert comparable(results[0]) == comparable(results[1])
    assert results[0]['initial']['loss'] != results[1]['initial']['loss']
    assert results[0]['score_accesses'] == results[1]['score_accesses']
    for run in results:
        assert run['spent'] == 3
        assert len(run['decisions']) == len({tuple(d['pair']) for d in run['decisions']}) == 3
        assert len(run['trace']) == 4
        assert [d['spent'] for d in run['decisions']] == [1, 2, 3]
        if method == 'cut_plan_adaptive':
            assert [d['batch'] for d in run['decisions']] == [1, 2, 3]
