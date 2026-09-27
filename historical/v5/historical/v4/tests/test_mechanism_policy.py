"""Synthetic tests for the single declared action-set ablation and BC cache.

No benchmark gold, sources or observed scientific results are used here.
"""
from copy import deepcopy
from itertools import combinations
import inspect

import networkx as nx
import numpy as np
import pytest

from cut_audit_er import audit, bounded_planner as planner, cli, experiment
from cut_audit_er.calibrated_planner import select_calibrated_plan
from cut_audit_er.completion_calibration import fit_plan_calibrator
from cut_audit_er.graph import edge_key
from cut_audit_er.planner_workspace import PlannerWorkspace
from cut_audit_er.policies import DEFAULT_METHODS, METHODS, select_action
from cut_audit_er.scores import PairScores


def make_scores(graph, value=.2, overrides=None):
    ids = tuple(sorted(graph))
    index = {node: i for i, node in enumerate(ids)}
    matrix = np.full((len(ids), len(ids)), value)
    np.fill_diagonal(matrix, 1.)
    for (u, v), probability in (overrides or {}).items():
        matrix[index[u], index[v]] = matrix[index[v], index[u]] = probability
    for u, v in graph.edges:
        graph.edges[u, v]['p'] = float(matrix[index[u], index[v]])
    return PairScores(ids, matrix)


def choose(graph, scores, method, budget=4, state=None, verified=None, observations=None):
    return select_action(graph, scores, verified or set(), budget, method,
                         np.random.default_rng(7), observations=observations,
                         policy_state=state)


def barrier():
    graph = nx.Graph()
    for prefix in ('a', 'b'):
        graph.add_edges_from(combinations([f'{prefix}{i}' for i in range(4)], 2))
    cross = tuple((f'a{i}', f'b{i}') for i in range(3))
    graph.add_edges_from(cross)
    internal = {edge_key(*edge) for edge in graph.edges} - set(cross)
    overrides = {edge: .95 for edge in internal}
    overrides.update(zip(cross, (.8, .7, .6)))
    return graph, make_scores(graph, .1, overrides), cross


def test_singleton_is_opt_in_for_both_default_entrypoints(monkeypatch, tmp_path):
    assert 'cut_plan_fixed_singleton' in METHODS
    assert 'cut_plan_fixed_singleton' not in DEFAULT_METHODS
    assert len(DEFAULT_METHODS) == 16
    # Parse actual CLI arguments, then stop before input loading or fitting.
    parsed = []
    real_parse = cli.argparse.ArgumentParser.parse_args

    class Parsed(Exception):
        pass

    def intercept(parser):
        parsed.append(real_parse(parser, ['csv', '--input', 'unused.csv',
                                          '--out', 'unused', '--data-kind', 'synthetic']))
        raise Parsed

    monkeypatch.setattr(cli.argparse.ArgumentParser, 'parse_args', intercept)
    with pytest.raises(Parsed):
        cli.main()
    assert tuple(parsed[0].methods) == DEFAULT_METHODS
    called = []
    monkeypatch.setattr(experiment, 'synthetic_graph', lambda *args: (None, None, None))
    def fake_run(g, scores, truth, method, *args):
        called.append(method)
        return {}
    monkeypatch.setattr(experiment, 'run_audit', fake_run)
    monkeypatch.setattr(experiment, 'metadata', lambda *args: {})
    monkeypatch.setattr(experiment, 'save_runs', lambda *args: None)
    experiment.run_experiment(tmp_path, {}, tmp_path / 'unused')
    assert tuple(called) == DEFAULT_METHODS
    called.clear()
    experiment.run_experiment(tmp_path, {'methods': ['cut_plan_fixed_singleton']}, tmp_path / 'unused')
    assert called == ['cut_plan_fixed_singleton']


def test_singleton_filters_identical_validated_pool_and_retains_depth_four_generation(monkeypatch):
    graph, scores, _ = barrier()
    captured = []
    real_build = planner.build_plan_pool

    def observe(*args, **kwargs):
        result = real_build(*args, **kwargs)
        captured.append((kwargs['allow_long'], deepcopy(result[:4])))
        return result

    monkeypatch.setattr(planner, 'build_plan_pool', observe)
    raw, raw_info = choose(graph, scores.copy(), 'cut_plan_fixed')
    singleton, info = choose(graph, scores.copy(), 'cut_plan_fixed_singleton')
    assert captured[0] == captured[1] and captured[0][0] is True
    assert info['depth_cap'] == raw_info['depth_cap'] == 4
    assert info['candidate_cap'] == raw_info['candidate_cap'] == 64
    assert info['candidate_depth_counts'] == raw_info['candidate_depth_counts']
    assert len(raw) == 3 and len(singleton) == 1
    # Higher match probability is queried first in committed multi-edge plans;
    # the singleton fallback instead favors an error-weighted central edge.
    assert raw[0] != singleton[0]
    assert info['scored_candidate_actions'] == 0
    assert info['fallback_trigger'] == 'empty_singleton_pool'
    assert info['selected_candidate_depth_counts'] == {'1': 1, '2': 0, '3': 0, '4': 0}
    assert raw_info['selected_candidate_depth_counts'] == {'1': 0, '2': 0, '3': 1, '4': 0}


def test_no_refill_when_common_cap_discards_the_only_singleton(monkeypatch):
    graph = nx.Graph()
    for i in range(22):
        graph.add_edges_from(combinations([f'{i}-{j}' for j in range(3)], 2))
    graph.add_edge('x', 'y')
    scores = make_scores(graph, .1, {('x', 'y'): .9999})
    plans, _, _, _, pool = planner.build_plan_pool(graph, scores.copy(), set(), 4)
    assert pool['raw_candidate_depth_counts']['1'] == 1
    assert pool['raw_candidate_plans'] == 67
    assert pool['candidate_cap'] == len(plans) == 64
    assert pool['candidate_depth_counts']['1'] == 0
    scored = []
    real_score = planner.completion_score

    def record(*args, **kwargs):
        scored.append(args[0])
        return real_score(*args, **kwargs)

    monkeypatch.setattr(planner, 'completion_score', record)
    action, info = choose(graph, scores.copy(), 'cut_plan_fixed_singleton')
    assert len(action) == 1 and action != (('x', 'y'),)
    assert scored == []
    assert info['candidate_actions'] == info['singleton_filtered_candidates'] == 64
    assert info['fallback_trigger'] == 'empty_singleton_pool'


@pytest.mark.parametrize('kind, expected', [
    ('empty', 'empty_validated_pool'),
    ('nonpositive', 'nonpositive_proxy'),
])
def test_fallback_reasons_distinguish_empty_and_nonpositive(kind, expected):
    if kind == 'empty':
        graph = nx.complete_graph(list('abcdef'))  # Minimum cut exceeds depth 4.
        scores = make_scores(graph, .9)
    else:
        graph = nx.path_graph(list('abcd'))
        scores = make_scores(graph, 1.)
    action, info = choose(graph, scores, 'cut_plan_fixed_singleton')
    assert len(action) == 1
    assert info['fallback_trigger'] == expected
    assert info['reason'] == 'centrality_continuation_after_nonpositive_or_empty_pool'


@pytest.mark.parametrize('budget', [0, 1, 2, 3, 4, 7])
def test_new_policy_budget_cost_and_negative_only_mutations(budget):
    graph, scores, _ = barrier()
    run = audit.run_audit(graph, scores, {node: node[0] for node in graph},
                          'cut_plan_fixed_singleton', budget)
    assert run['spent'] == budget
    assert len(run['decisions']) == len({tuple(row['pair']) for row in run['decisions']}) == budget
    assert all(timing['action_size'] == 1 for timing in run['batch_timings'])
    for before, after, decision in zip(run['trace'], run['trace'][1:], run['decisions']):
        assert before['n_edges'] - after['n_edges'] == int(not decision['observed_match'])


def test_committed_raw_batch_still_charges_after_a_positive_answer():
    graph, scores, _ = barrier()
    run = audit.run_audit(graph, scores, {node: 'one' for node in graph}, 'cut_plan_fixed', 3)
    assert run['spent'] == 3 and all(row['observed_match'] for row in run['decisions'])
    assert [row['batch'] for row in run['decisions']] == [1, 1, 1]
    # The same batch-level counts are copied to each paid decision; aggregate
    # by unique batch, not once per physical pair.
    batches = {row['batch']: row['selection_info'] for row in run['decisions']}
    assert sum(info['selected_candidate_depth_counts']['3'] for info in batches.values()) == 1


def test_original_cache_key_keeps_adjacency_order_and_isolates(monkeypatch):
    graph = nx.Graph()
    graph.add_nodes_from('dcba')
    graph.add_edges_from([('d', 'b'), ('d', 'a'), ('b', 'a'), ('a', 'c')])
    workspace = PlannerWorkspace()
    calls = []
    real = nx.edge_betweenness_centrality

    def record(g):
        calls.append((tuple(g), tuple((node, tuple(g.adj[node])) for node in g)))
        return real(g)

    monkeypatch.setattr(nx, 'edge_betweenness_centrality', record)
    first = dict(workspace.original_centrality(graph))
    assert workspace.original_centrality(graph) == first
    assert len(calls) == 1
    # Same topology and node order, but changed adjacency iteration order.
    graph.remove_edge('d', 'b'); graph.add_edge('d', 'b')
    reordered = workspace.original_centrality(graph)
    assert len(calls) == 2
    assert reordered == {edge_key(*edge): value for edge, value in real(graph).items()}
    graph.add_node('isolate')
    isolated = workspace.original_centrality(graph)
    assert len(calls) == 3 and isolated != reordered
    graph.remove_edge('a', 'b')  # A non-splitting deletion still invalidates BC.
    workspace.original_centrality(graph)
    assert len(calls) == 4
    graph.remove_edge('a', 'c')  # A split also invalidates BC.
    workspace.original_centrality(graph)
    assert len(calls) == 5


def test_positive_answer_refreshes_scores_and_eligibility_but_reuses_bc():
    graph = nx.cycle_graph(list('abcde'))
    scores = make_scores(graph, .3)
    state = {}
    first, info = choose(graph, scores, 'edge_betweenness', state=state)
    assert info['topology_cache'] == {'original_centrality_misses': 1}
    initial_calls = scores.calls
    second, info = choose(graph, scores, 'edge_betweenness', state=state,
                          verified=set(first), observations={first[0]: True})
    assert first[0] not in second
    assert scores.calls - initial_calls == graph.number_of_edges() - 1
    assert info['topology_cache'] == {'original_centrality_hits': 1}
    # Scores themselves are not cached, even with unchanged topology.
    alternate = make_scores(graph, .99, {second[0]: 0.})
    chosen, info = choose(graph, alternate, 'edge_betweenness', state=state,
                          verified=set(first), observations={first[0]: True})
    assert chosen == second and alternate.calls == graph.number_of_edges() - 1
    assert info['topology_cache'] == {'original_centrality_hits': 1}




def test_bc_bounded_and_calibrated_fallback_share_original_cache():
    graph = nx.complete_graph(list('fedcba'))
    scores = make_scores(graph, 1.)
    workspace = PlannerWorkspace()
    state = {'_topology_workspace': workspace}
    first, _ = choose(graph, scores.copy(), 'edge_betweenness', state=state)
    bounded, bounded_info = choose(graph, scores.copy(), 'cut_plan_fixed', state=state)
    calibrated, info = select_calibrated_plan(
        graph, scores.copy(), set(), 4, 'cut_plan_completion_calibrated', {},
        fit_plan_calibrator([], [], []), workspace=workspace)
    assert first == bounded == calibrated
    assert workspace.counts['original_centrality_misses'] == 1
    assert workspace.counts['original_centrality_hits'] == 2
    assert bounded_info['topology_cache']['original_centrality_hits'] == 1
    assert info['topology_cache']['original_centrality_hits'] == 1


@pytest.mark.parametrize('method', ['edge_betweenness', 'cut_plan_fixed_singleton'])
def test_evaluation_gold_cannot_change_queries_given_fixed_paid_answers(monkeypatch, method):
    graph, scores, cross = barrier()
    answers = {edge_key(*edge): edge_key(*edge) not in cross for edge in graph.edges}

    class FixedPaidOracle:
        def __init__(self, ignored_gold, budget, noise, seed):
            self.budget, self.spent, self.observed = budget, 0, {}

        @property
        def remaining(self):
            return self.budget - self.spent

        def query(self, u, v):
            edge = edge_key(u, v)
            assert edge not in self.observed and self.remaining > 0
            self.spent += 1
            self.observed[edge] = answers[edge]
            return self.observed[edge]

    monkeypatch.setattr(audit, 'BudgetedOracle', FixedPaidOracle)
    one = audit.run_audit(graph, scores, {node: 'one' for node in graph}, method, 7)
    many = audit.run_audit(graph, scores, {node: node for node in graph}, method, 7)
    assert logical(one['decisions']) == logical(many['decisions'])
    assert one['score_accesses'] == many['score_accesses']
    assert one['initial']['loss'] != many['initial']['loss']
    assert not {'truth', 'gold', 'observations', 'scores'} & set(inspect.signature(PlannerWorkspace.original_centrality).parameters)


def test_new_telemetry_allowlist_does_not_hide_legacy_candidate_or_score_changes():
    original = {'candidate_actions': 3, 'selected_proxy_score': .2, 'planned_edges': [['a', 'b']],
                'reason': 'centrality_continuation_after_nonpositive_or_empty_pool'}
    addition = {**original, 'scored_candidate_actions': 3,
                'raw_candidate_depth_counts': {'1': 3}, 'fallback_trigger': 'nonpositive_proxy'}
    assert logical(original) == logical(addition)
    for key, value in [('candidate_actions', 4), ('selected_proxy_score', .3),
                       ('planned_edges', [['a', 'c']])]:
        assert logical(original) != logical({**addition, key: value})
    # The old risk_centrality_fallback method already had fallback_trigger;
    # retain it because it is legacy decision metadata, not new telemetry.
    legacy = {'reason': 'centrality_continuation_after_nonpositive_proxy',
              'fallback_trigger': 'no_positive_proxy_utility'}
    assert logical(legacy) != logical({**legacy, 'fallback_trigger': 'wrong'})

def logical(value):
    """Strip times/cache counts and the explicit additive telemetry allowlist.

    Legacy decision semantics (candidate counts/order, scores, reasons and
    planned edges) remain compared. New telemetry itself is tested separately.
    """
    added_telemetry = {'raw_candidate_depth_counts', 'capped_candidate_depth_counts',
                       'scored_candidate_depth_counts', 'scored_candidate_actions',
                       'selected_candidate_depth_counts'}
    if isinstance(value, dict):
        if value.get('reason') == 'centrality_continuation_after_nonpositive_or_empty_pool':
            added_telemetry.add('fallback_trigger')
        return {k: logical(v) for k, v in value.items()
                if not k.endswith('_seconds')
                and k not in {'topology_cache', 'seconds', 'batch_timings'} | added_telemetry}
    if isinstance(value, (list, tuple)):
        return [logical(v) for v in value]
    return value
