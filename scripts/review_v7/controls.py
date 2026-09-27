"""Visible-only construction and unchanged initial selector decision.

The declared probability law supplies exact *marginal* scores, never a sampled
reference. Realized worlds are created only by the separate evaluator module.
"""
from __future__ import annotations
from fractions import Fraction
from itertools import combinations
import math
import time

import networkx as nx
import numpy as np

from cut_audit_er.bounded_planner import completion_score
from cut_audit_er.covered_planner import select_covered_plan
from cut_audit_er.scores import PairScores
from .common import require, fingerprint, validate_spec


def visible_case(spec):
    """Return only visible graph/order and exact marginal matrix; no world input."""
    probabilities = validate_spec(spec)
    if spec['kind'] == 'matching':
        nodes = tuple(f'P{i:03}{side}' for i in range(spec['pair_count']) for side in 'ab')
        edges = [(nodes[2*i], nodes[2*i+1]) for i in range(spec['pair_count'])]
        marginals = {edge: 1 - (probabilities[0] if i == 0 else probabilities[1]) for i, edge in enumerate(edges)}
    elif spec['kind'] == 'path':
        nodes = tuple(f'v{i}' for i in range(4))
        edges = list(zip(nodes[:-1], nodes[1:]))
        marginals = {(nodes[i], nodes[j]): math.prod(1-p for p in probabilities[i:j])
                     for i in range(4) for j in range(i+1, 4)}
    else:
        nodes = tuple([f'A{i}' for i in range(3)] + [f'B{i}' for i in range(3)] + ['R0', 'R1'])
        edges = sorted([*combinations(nodes[:3], 2), *combinations(nodes[3:6], 2),
                        ('A0', 'B0'), ('A1', 'B1'), ('R0', 'R1')])
        marginals = {}
        for u, v in combinations(nodes, 2):
            if u[0] == v[0] and u[0] in 'AB':
                value = Fraction(1)
            elif {u[0], v[0]} == {'A', 'B'}:
                value = 1-probabilities[0]
            elif u[0] == v[0] == 'R':
                value = 1-probabilities[1]
            else:
                value = Fraction(0)
            marginals[u, v] = value
    matrix = [[str(Fraction(1) if u == v else marginals.get(tuple(sorted((u, v))), Fraction(0)))
               for v in nodes] for u in nodes]
    return {'schema': 'cut-audit-v7-visible-case', 'case': spec['id'], 'kind': spec['kind'],
            'budget': spec['budget'], 'nodes': list(nodes), 'edges': [list(e) for e in sorted(edges)],
            'exact_marginals': matrix, 'spec_sha256': fingerprint(spec)}


def materialize(visible):
    nodes = visible['nodes']
    require(len(nodes) == len(set(nodes)) and nodes == sorted(nodes), 'Node ordering/membership invalid')
    matrix = [[float(Fraction(p)) for p in row] for row in visible['exact_marginals']]
    scores = PairScores(tuple(nodes), np.asarray(matrix))
    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    edges = visible['edges']
    require(edges == sorted(edges) and len({tuple(e) for e in edges}) == len(edges), 'Edge order/duplicate')
    graph.add_edges_from((u, v, {'p': float(matrix[nodes.index(u)][nodes.index(v)])}) for u, v in edges)
    return graph, scores


def independent_bonds(graph, budget):
    """Vertex bipartitions, independent of the engine's edge-subset generator."""
    result = {}
    for component in sorted(tuple(sorted(c)) for c in nx.connected_components(graph)):
        require(len(component) <= 16, 'Independent enumeration exceeds declared visible cap')
        for mask in range(1 << (len(component)-1)):
            left = (component[0],) + tuple(component[i+1] for i in range(len(component)-1) if mask & (1 << i))
            right = tuple(u for u in component if u not in left)
            if not right or not nx.is_connected(graph.subgraph(left)) or not nx.is_connected(graph.subgraph(right)):
                continue
            q = tuple(sorted(tuple(sorted((u, v))) for u, v in graph.subgraph(component).edges
                             if (u in left) != (v in left)))
            if 0 < len(q) <= min(4, budget):
                result[q] = (left, right)
    return result


def semantic(value):
    """Retain all decision evidence/accesses, dropping observational timers only."""
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if not k.endswith('_seconds')}
    if isinstance(value, (tuple, list)):
        return [semantic(v) for v in value]
    return value


def audit_initial_decision(visible):
    """One unchanged selector invocation; no oracle answer is acquired."""
    started = time.perf_counter()
    graph, scores = materialize(visible)
    action, info = select_covered_plan(graph, scores, set(), visible['budget'],
                                     'cut_plan_cover_fixed', {}, {}, 1.)
    selector_calls = scores.calls
    trace = info['candidate_trace']
    parts = independent_bonds(graph, visible['budget'])
    canonical = lambda q: tuple(sorted(tuple(e) for e in q))
    eligible = [canonical(q) for q in trace['eligible_order']]
    require(eligible == sorted(parts), 'Independent legal pool disagrees with frozen selector')
    scored = {canonical(q) for q in trace['scored_order']}
    bounds = {canonical(r['edges']): r['upper_bound'] for r in trace['bound_records']}
    fresh_scores = scores.copy()
    probabilities = {e: fresh_scores.p(*e) for e in sorted(graph.edges)}
    rows = []
    for q in eligible:
        value, utility, success = completion_score(q, parts[q], fresh_scores, probabilities, {}, 1.)
        require(math.isfinite(value) and value <= bounds[q], 'Invalid full score/numerical certificate')
        rows.append({'action': [list(e) for e in q], 'partition': [list(x) for x in parts[q]],
                     'proxy_float': value, 'utility_float': utility, 'success_product_float': success,
                     'upper_bound': bounds[q], 'was_scored': q in scored})
    winner = min(rows, key=lambda r: (-r['proxy_float'], len(r['action']), r['action'])) if rows else None
    chosen = canonical(action or ())
    positive = bool(winner and winner['proxy_float'] > 0)
    if positive:
        require(chosen == canonical(winner['action']) and not info.get('fallback'), 'Selector differs from exhaustive winner')
        require(info['surrogate_argmax_certified'], 'Positive control selection lacks pool certificate')
    else:
        require(bool(info.get('fallback')) or action is None, 'Nonpositive fallback not identified')
    return {'schema': 'cut-audit-v7-visible-decision', 'case': visible['case'],
            'visible_sha256': fingerprint(visible), 'visible': visible,
            'selected_action': [list(e) for e in action or ()], 'candidates': rows,
            'pool_count': len(rows), 'scored_count': len(scored),
            'certificate_status': info['surrogate_certificate_status'],
            'positive_pool_certificate': positive, 'fallback': info.get('fallback'),
            'selector_logical_accesses': selector_calls,
            'independent_score_accesses': fresh_scores.calls,
            'selection_info': info, 'decision_seconds': time.perf_counter()-started,
            'new_oracle_answers': 0, 'initial_decision_only': True}
