"""Constructed tests only; exhaustive graphs/partitions on at most four nodes."""
import ast
import itertools
from pathlib import Path

import networkx as nx
import pytest

from cut_audit_er.offline_structure import (
    gold_positive_graph, structural_diagnostics, validate_legal_repair,
)


def graph(nodes, edges=()):
    g = nx.Graph(); g.add_nodes_from(nodes); g.add_edges_from(edges)
    return g


def partitions(n):
    if n == 0:
        yield (); return
    def extend(prefix):
        if len(prefix) == n:
            yield prefix; return
        for y in range(max(prefix)+2):
            yield from extend(prefix+(y,))
    yield from extend((0,))


def brute_fn(g, truth):
    components = {u: i for i, c in enumerate(nx.connected_components(g)) for u in c}
    return sum(truth[u] == truth[v] and components[u] != components[v]
               for u, v in itertools.combinations(g, 2))


@pytest.mark.parametrize('n', range(5))
def test_all_small_graphs_partitions_and_legal_deletion_subsets(n):
    ids = list('abcd'[:n]); pairs = list(itertools.combinations(ids, 2))
    for included in itertools.product((False, True), repeat=len(pairs)):
        g = graph(ids, [e for e, yes in zip(pairs, included) if yes])
        for labels in partitions(n):
            truth = {u: str(y) for u, y in zip(ids, labels)}
            report = structural_diagnostics(g, truth, perfect_oracle=True)
            negatives = [e for e in g.edges if truth[e[0]] != truth[e[1]]]
            positive = gold_positive_graph(g, truth, perfect_oracle=True)
            lo, hi = brute_fn(g, truth), brute_fn(positive, truth)
            assert report['initial']['fn'] == lo
            assert report['gold_positive_endpoint']['fn'] == hi
            assert report['delta_FN_max'] == hi-lo
            observed = []
            for deleted in itertools.product((False, True), repeat=len(negatives)):
                edges = [e for e, yes in zip(negatives, deleted) if yes]
                h = g.copy(); h.remove_edges_from(edges)
                result = validate_legal_repair(g, h, truth, observed_answers={e: False for e in edges},
                                              perfect_oracle=True, requested_budget=len(edges))
                observed.append(brute_fn(h, truth))
                assert result['fn_observed'] == observed[-1]
                assert lo <= observed[-1] <= hi
            assert min(observed) == lo and max(observed) == hi  # both endpoints are sharp
            if hi == lo:
                assert set(observed) == {lo}


def test_sharp_positive_headroom_example():
    g = graph('abc', [('a','b'), ('b','c')]); truth = {'a':'A', 'b':'B', 'c':'A'}
    result = structural_diagnostics(g, truth, perfect_oracle=True)
    assert (result['initial']['fn'], result['gold_positive_endpoint']['fn'], result['delta_FN_max']) == (0,1,1)


def test_zero_headroom_does_not_mean_zero_initial_fn():
    g = graph('abcde', [('a','b'), ('c','d'), ('b','c')])
    truth = {'a':'A', 'b':'A', 'c':'B', 'd':'B', 'e':'A'}
    result = structural_diagnostics(g, truth, perfect_oracle=True)
    assert result['delta_FN_max'] == 0
    assert result['initial']['fn'] == result['gold_positive_endpoint']['fn'] == 2
    assert result['gold_positive_endpoint']['fp'] == 0
    assert result['gold_positive_endpoint']['component_sizes'] == [2,2,1]


def test_endpoint_is_not_a_loss_optimum():
    g = graph('abcde', [('a', u) for u in 'bcde'])
    truth = {u: 'B' if u == 'a' else 'A' for u in g}
    result = structural_diagnostics(g, truth, perfect_oracle=True)
    assert result['initial']['fp']+result['initial']['fn'] == 4
    assert result['gold_positive_endpoint']['fp']+result['gold_positive_endpoint']['fn'] == 6
    assert result['delta_FN_max'] == 6


def test_zero_budget_does_not_attain_positive_unrestricted_headroom():
    g = graph('abc', [('a','b'), ('b','c')]); truth = {'a':'A','b':'B','c':'A'}
    checked = validate_legal_repair(g, g, truth, observed_answers={}, perfect_oracle=True, requested_budget=0)
    assert checked['actual_added_FN'] == 0 < checked['delta_FN_max']


def test_inputs_unchanged_and_visible_score_not_used():
    g = graph('abc', [('a','b'), ('b','c')]); truth = {'a':'A','b':'B','c':'A'}
    g.edges['a','b']['p'] = .01; g.edges['b','c']['p'] = .99
    before = nx.node_link_data(g)
    first = structural_diagnostics(g, truth, perfect_oracle=True)
    assert nx.node_link_data(g) == before
    g.edges['a','b']['p'] = .9; g.edges['b','c']['p'] = .1
    assert structural_diagnostics(g, truth, perfect_oracle=True) == first


@pytest.mark.parametrize('declaration', [False, None, 0, 1, 'true'])
def test_noisy_or_nonboolean_assumption_rejected(declaration):
    with pytest.raises(ValueError, match='perfect_oracle'):
        structural_diagnostics(graph('ab'), {'a':'A','b':'A'}, perfect_oracle=declaration)


def test_explicit_assumption_is_required():
    with pytest.raises(TypeError):
        structural_diagnostics(graph('ab'), {'a':'A','b':'A'})


@pytest.mark.parametrize('bad', ['directed','multigraph','loop','node_label','graph_label','edge_label','bad_p','numeric_id'])
def test_graph_contract_violations(bad):
    g = graph('ab', [('a','b')]); truth = {'a':'A','b':'B'}
    if bad == 'directed': g = nx.DiGraph(g)
    if bad == 'multigraph': g = nx.MultiGraph(g)
    if bad == 'loop': g.add_edge('a','a')
    if bad == 'node_label': g.nodes['a']['gold'] = 'A'
    if bad == 'graph_label': g.graph['gold'] = truth
    if bad == 'edge_label': g.edges['a','b']['gold'] = False
    if bad == 'bad_p': g.edges['a','b']['p'] = float('nan')
    if bad == 'numeric_id': g.add_node(1); truth[1] = 'C'
    with pytest.raises(ValueError): structural_diagnostics(g, truth, perfect_oracle=True)


@pytest.mark.parametrize('truth', [{'a':'A'}, {'a':'A','b':'B','c':'C'}, {'a':'A','b':None}, {'a':'A','b':True}])
def test_incomplete_or_invalid_gold_rejected(truth):
    with pytest.raises(ValueError): structural_diagnostics(graph('ab'), truth, perfect_oracle=True)


@pytest.mark.parametrize('bad', ['remove_node','add_node','add_edge','delete_positive','unpaid_deletion',
                                'noisy_answer','numeric_answer','reversed_duplicate','nonoriginal_receipt',
                                'changed_score','over_budget','bool_budget','malformed_pair'])
def test_illegal_repair_or_receipts_rejected(bad):
    g = graph('abcd', [('a','b'), ('b','c')]); truth = {'a':'A','b':'A','c':'B','d':'C'}
    g.edges['a','b']['p'] = .8
    h = g.copy(); answers = {}; budget = 4
    if bad == 'remove_node': h.remove_node('d')
    if bad == 'add_node': h.add_node('e')
    if bad == 'add_edge': h.add_edge('a','c')
    if bad == 'delete_positive': h.remove_edge('a','b')
    if bad == 'unpaid_deletion': h.remove_edge('b','c')
    if bad == 'noisy_answer': answers = {('b','c'): True}
    if bad == 'numeric_answer': answers = {('b','c'): 0}
    if bad == 'reversed_duplicate': answers = {('b','c'):False, ('c','b'):False}
    if bad == 'nonoriginal_receipt': answers = {('a','c'): False}
    if bad == 'changed_score': h.edges['a','b']['p'] = .9
    if bad == 'over_budget': answers = {('a','b'):True}; budget = 0
    if bad == 'bool_budget': budget = True
    if bad == 'malformed_pair': answers = {'ab': True}
    with pytest.raises(ValueError):
        validate_legal_repair(g, h, truth, observed_answers=answers, perfect_oracle=True, requested_budget=budget)


def test_paid_positive_and_retained_negative_are_still_counted():
    g = graph('abc', [('a','b'), ('b','c')]); truth = {'a':'A','b':'A','c':'B'}
    result = validate_legal_repair(g, g, truth, observed_answers={('b','a'):True, ('c','b'):False},
                                  perfect_oracle=True, requested_budget=2)
    assert result['paid_answers'] == 2
    assert result['paid_positive_answers'] == result['paid_negative_answers'] == 1
    assert result['deleted_edges'] == 0


def test_offline_module_does_not_import_selectors_and_selectors_do_not_import_it():
    import cut_audit_er.offline_structure as module
    path = Path(module.__file__)
    imports = [n for n in ast.walk(ast.parse(path.read_text(encoding='utf-8'))) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert all(not isinstance(n, ast.ImportFrom) or n.level == 0 for n in imports)
    for source in path.parent.glob('*.py'):
        if source != path:
            assert 'offline_structure' not in source.read_text(encoding='utf-8'), source
