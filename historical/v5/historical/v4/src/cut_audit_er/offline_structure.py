"""Gold-aware structural evaluation; never import into a selector.

The FN sandwich is the elementary connectivity observation in the supplied
2026-09-19 Calibration Review, not a new theorem or a finite-budget optimum.
No scoring, querying, fitting, or policy selection occurs in this module.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
import math
import networkx as nx


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _graph(g: nx.Graph) -> None:
    _require(isinstance(g, nx.Graph) and not g.is_directed() and not g.is_multigraph(),
             'Expected a simple undirected graph')
    _require(nx.number_of_selfloops(g) == 0, 'Self-loops are not original pair tasks')
    _require(not g.graph and all(isinstance(v, str) and v and not a for v, a in g.nodes(data=True)),
             'Use nonempty string record IDs without graph/node attributes')
    for _, _, attributes in g.edges(data=True):
        _require(set(attributes) <= {'p'}, 'Only original visible p edge attributes are allowed')
        if 'p' in attributes:
            value = attributes['p']
            _require(not isinstance(value, bool) and isinstance(value, (int, float)) and
                     math.isfinite(value) and 0 <= value <= 1, 'Invalid visible edge probability')


def _inputs(g: nx.Graph, truth: Mapping[str, str], perfect_oracle: bool) -> None:
    _require(type(perfect_oracle) is bool and perfect_oracle,
             'An explicit Boolean perfect_oracle=True declaration is required; noisy cases are outside scope')
    _graph(g)
    _require(isinstance(truth, Mapping) and set(truth) == set(g),
             'Gold must cover exactly every original record, including isolates')
    _require(all(isinstance(y, str) and y for y in truth.values()),
             'Gold entity IDs must be nonempty strings')


def _edge(u: str, v: str) -> tuple[str, str]:
    return (u, v) if u < v else (v, u)


def _choose2(n: int) -> int:
    return n*(n-1)//2


def _counts(g: nx.Graph, truth: Mapping[str, str]) -> dict:
    sizes = Counter(truth.values())
    true_pairs = sum(_choose2(n) for n in sizes.values())
    components = list(nx.connected_components(g))
    tp = sum(sum(_choose2(n) for n in Counter(truth[u] for u in c).values()) for c in components)
    predicted = sum(_choose2(len(c)) for c in components)
    return {'tp': tp, 'fp': predicted-tp, 'fn': true_pairs-tp,
            'n_records': len(g), 'n_edges': g.number_of_edges(), 'n_components': len(components),
            'component_sizes': sorted((len(c) for c in components), reverse=True)}


def gold_positive_graph(g: nx.Graph, truth: Mapping[str, str], *, perfect_oracle: bool) -> nx.Graph:
    """Copy G and remove all gold-negative edges for OFFLINE evaluation only.

    This endpoint assumes unlimited individually verified-negative deletions;
    constructing it here spends no labels and must not supply a policy action.
    """
    _inputs(g, truth, perfect_oracle)
    plus = g.copy()
    plus.remove_edges_from([(u, v) for u, v in g.edges if truth[u] != truth[v]])
    return plus


def structural_diagnostics(g: nx.Graph, truth: Mapping[str, str], *, perfect_oracle: bool) -> dict:
    """Return graph statistics and the sharp, budget-unrestricted FN interval.

    A zero delta_FN_max means legal deletions cannot add FN; initial FN can
    still be positive. This is neither a probability nor a bound on optimal
    loss at a particular budget. Empty/single-record graphs have zero pairs.
    """
    plus = gold_positive_graph(g, truth, perfect_oracle=perfect_oracle)
    initial, endpoint = _counts(g, truth), _counts(plus, truth)
    initial_components = sorted(nx.connected_components(g), key=lambda c: (-len(c), tuple(sorted(c))))
    # Attribute the possible additional FN to fixed INITIAL components.
    component_rows = []
    for i, component in enumerate(initial_components):
        local_truth = {u: truth[u] for u in component}
        before = _counts(g.subgraph(component), local_truth)
        after = _counts(plus.subgraph(component), local_truth)
        component_rows.append({'component_index': i, 'n_records': len(component),
            'n_edges': before['n_edges'], 'gold_entities': len(set(local_truth.values())),
            'initial_fp': before['fp'], 'initial_tp': before['tp'],
            'positive_subgraph_component_sizes': after['component_sizes'],
            'delta_FN_max': after['fn']-before['fn']})
    delta = endpoint['fn']-initial['fn']
    _require(delta >= 0 and endpoint['fp'] == 0 and
             sum(r['delta_FN_max'] for r in component_rows) == delta, 'Internal connectivity/count inconsistency')
    return {'scope': 'offline_gold_only; unlimited_negative_edge_deletions; not a finite-budget or loss optimum',
            'assumptions': {'perfect_oracle': True, 'original_edges_only': True,
                            'individually_paid_negative_deletions_only': True, 'node_preserving': True},
            'initial': initial, 'gold_positive_endpoint': endpoint,
            'delta_FN_max': delta, 'zero_additional_FN_possible': delta == 0,
            'gold_entities': len(set(truth.values())),
            'gold_entity_sizes': sorted(Counter(truth.values()).values(), reverse=True),
            'gold_pair_count': sum(_choose2(n) for n in Counter(truth.values()).values()),
            'original_positive_edges': plus.number_of_edges(),
            'original_negative_edges': g.number_of_edges()-plus.number_of_edges(),
            'initial_components': component_rows}


def validate_legal_repair(g: nx.Graph, h: nx.Graph, truth: Mapping[str, str], *,
                          observed_answers: Mapping[tuple[str, str], bool],
                          perfect_oracle: bool, requested_budget: int | None = None) -> dict:
    """Validate an archived repair against supplied paid receipts, then its FN bound.

    Receipts must refer to distinct original edges and contain actual Boolean
    answers agreeing with gold. Every removed edge needs its own negative
    receipt. A paid negative may remain; every paid positive still costs one.
    This validates the supplied receipt mapping, not external human payments.
    """
    _inputs(g, truth, perfect_oracle)
    _graph(h)
    _require(set(h) == set(g), 'Repair must preserve all original nodes, including isolates')
    original = {_edge(u, v) for u, v in g.edges}
    retained = {_edge(u, v) for u, v in h.edges}
    _require(retained <= original, 'Repair cannot add nonoriginal edges')
    _require(all(dict(h.edges[e]) == dict(g.edges[e]) for e in retained), 'Surviving edge attributes changed')
    _require(isinstance(observed_answers, Mapping), 'Paid answers must be a mapping')
    paid = {}
    for pair, answer in observed_answers.items():
        _require(isinstance(pair, tuple) and len(pair) == 2 and all(isinstance(u, str) for u in pair),
                 'Paid pair must be a two-record tuple')
        e = _edge(*pair)
        _require(e in original and e not in paid, 'Paid pair is nonoriginal or duplicated in reverse orientation')
        _require(type(answer) is bool, 'Paid answers must be Boolean, not numeric or truthy values')
        _require(answer == (truth[e[0]] == truth[e[1]]), 'Noisy or incorrect answer violates perfect-oracle assumption')
        paid[e] = answer
    if requested_budget is not None:
        _require(type(requested_budget) is int and requested_budget >= 0, 'Budget must be a nonnegative integer')
        _require(len(paid) <= requested_budget, 'Paid answers exceed requested budget')
    removed = original-retained
    _require(all(truth[u] != truth[v] for u, v in removed), 'Cannot remove a gold-positive original edge')
    _require(all(e in paid and paid[e] is False for e in removed), 'Every deletion needs its own paid negative receipt')
    diagnosis = structural_diagnostics(g, truth, perfect_oracle=True)
    observed = _counts(h, truth)
    lo, hi = diagnosis['initial']['fn'], diagnosis['gold_positive_endpoint']['fn']
    _require(lo <= observed['fn'] <= hi, 'FN sandwich violated despite validated assumptions')
    return {'legal_repair': True, 'fn_lower': lo, 'fn_observed': observed['fn'], 'fn_upper': hi,
            'delta_FN_max': hi-lo, 'actual_added_FN': observed['fn']-lo,
            'paid_answers': len(paid), 'paid_positive_answers': sum(paid.values()),
            'paid_negative_answers': len(paid)-sum(paid.values()), 'deleted_edges': len(removed),
            'requested_budget': requested_budget,
            'scope': 'offline receipt validation; not a policy recommendation or finite-budget optimum'}
