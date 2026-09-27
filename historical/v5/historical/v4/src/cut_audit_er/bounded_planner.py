"""Small observable cut pools and bounded completion surrogates; no gold access.

Only minimal cuts (bonds) are scored. A strict subset of a bond cannot change
component connectivity, so a terminal all-negative numerator does not omit
intermediate split loss for that fixed plan. This is still a factorized proxy,
not a conditional posterior or an optimal adaptive policy.
"""
from __future__ import annotations
from math import prod
import time
import networkx as nx
from .graph import edge_key, removed_copy
from .planner_workspace import PlannerWorkspace

MAX_DEPTH = 4
MAX_PLANS = 64
LOW_SEEDS_PER_COMPONENT = 24
CENTRALITY_SEEDS_PER_COMPONENT = 8
FLOW_SEEDS_PER_RANKING = 8


def depth_counts(plans):
    """Observable batch-level counts; never sum once per copied paid row."""
    return {str(k): sum(len(plan) == k for plan in plans)
            for k in range(1, MAX_DEPTH + 1)}


def canonical_graph(g, nodes=None):
    nodes = sorted(g if nodes is None else nodes)
    selected = set(nodes)
    h = nx.Graph()
    h.add_nodes_from(nodes)
    h.add_edges_from((u, v, {'p': float(g.edges[u, v].get('p', .5))})
                     for u, v in sorted(edge_key(*e) for e in g.edges)
                     if u in selected and v in selected)
    return h


def bond_partition(component, plan):
    """Return the two sides only if plan is a minimal cut of this component."""
    if not plan or len(set(plan)) != len(plan) or not nx.is_connected(component):
        return None
    if any(not component.has_edge(*edge) for edge in plan):
        return None
    after = removed_copy(component, plan)
    parts = sorted((tuple(sorted(c)) for c in nx.connected_components(after)))
    if len(parts) != 2:
        return None
    side = set(parts[0])
    # Every removed edge crosses the two resulting components. Restoring any
    # one reconnects them, hence no proper deletion subset changes connectivity.
    if any((u in side) == (v in side) for u, v in plan):
        return None
    return parts[0], parts[1]


def expected_abort_cost(ordered_plan, probabilities):
    reach, cost = 1., 0.
    for edge in ordered_plan:
        cost += reach
        reach *= 1. - probabilities[edge]
    return cost


def build_plan_pool(g, scores, verified, remaining, *, allow_long=True,
                    pending_plan=(), max_plans=MAX_PLANS, diagnostic_raw=False,
                    workspace=None):
    """Deterministic bounded pool; no score/final-outcome gold enters truncation.

    Two-cuts: at least one low-score or centrality seed, any eligible partner.
    Long bonds: <=16 protected-edge s-t mincut calls, <=4 requested edges.
    Pre-rank by mean error-weighted centrality; validate/score <=64 plans.
    A valid pending remainder reserves one slot, but need not be selected.
    """
    if not 1 <= max_plans <= MAX_PLANS:
        raise ValueError('plan cap must be between one and the fixed maximum')
    start = time.perf_counter()
    workspace = workspace if workspace is not None else PlannerWorkspace()
    cache_before = dict(workspace.counts)
    depth = min(MAX_DEPTH if allow_long else 2, remaining)
    h = workspace.canonical(g)
    eligible = sorted(edge_key(*e) for e in h.edges if edge_key(*e) not in verified)
    probabilities = {edge: scores.p(*edge) for edge in eligible}
    bc = workspace.centrality()
    weighted = {edge: bc[edge] * (1. - probabilities[edge]) for edge in eligible}
    centrality_finished = time.perf_counter()
    components = workspace.components()
    local = {node: component for component in components for node in component}
    bridges = workspace.bridges()
    eligible_by_component = {id(component): [] for component in components}
    for edge in eligible:
        if edge not in bridges:
            eligible_by_component[id(local[edge[0]])].append(edge)
    raw = {(edge,) for edge in eligible if edge in bridges} if depth >= 1 else set()
    seeded_components = 0
    for component in components:
        pool = eligible_by_component[id(component)]
        if depth < 2 or not pool:
            continue
        low = sorted(pool, key=lambda e: (probabilities[e], e))[:LOW_SEEDS_PER_COMPONENT]
        central = sorted(pool, key=lambda e: (-weighted[e], e))[:CENTRALITY_SEEDS_PER_COMPONENT]
        seeds = sorted(set(low) | set(central))
        seeded_components += 1
        allowed = set(pool)
        for edge in seeds:
            for candidate in workspace.bridges_without(component, edge):
                partner = edge_key(*candidate)
                if partner in allowed and partner != edge:
                    raw.add(tuple(sorted((edge, partner))))
    small_raw_count = len(raw)
    small_finished = time.perf_counter()
    flow_calls = 0
    if allow_long and depth >= 3:
        top = sorted(eligible, key=lambda e: (-weighted[e], e))[:FLOW_SEEDS_PER_RANKING]
        low = sorted(eligible, key=lambda e: (probabilities[e], e))[:FLOW_SEEDS_PER_RANKING]
        for edge in sorted(set(top) | set(low)):
            component = local[edge[0]].copy()
            for u, v in component.edges:
                component.edges[u, v]['capacity'] = depth + 1 if edge_key(u, v) in verified else 1
            value, (left, right) = nx.minimum_cut(component, *edge, capacity='capacity',
                                                 flow_func=nx.algorithms.flow.edmonds_karp)
            flow_calls += 1
            if value > depth:
                continue
            right = set(right)
            plan = tuple(sorted(edge_key(u, v) for u in left for v in component.neighbors(u) if v in right))
            if plan and len(plan) <= depth and not any(e in verified for e in plan):
                raw.add(plan)
    flow_finished = time.perf_counter()
    pending = tuple(sorted(pending_plan))
    pending_valid = (bool(pending) and len(pending) <= depth
                     and all(edge in probabilities for edge in pending)
                     and workspace.bond(local[pending[0][0]], pending, bond_partition) is not None)
    if pending_valid:
        raw.add(pending)
    ranked = sorted(raw, key=lambda q: (-sum(weighted[e] for e in q) / len(q), len(q), q))
    chosen = ranked[:max_plans]
    if pending_valid and pending not in chosen:
        chosen = [pending] + chosen[:max_plans - 1]
    plans, partitions = [], {}
    for plan in chosen:
        partition = workspace.bond(local[plan[0][0]], plan, bond_partition)
        if partition is not None:
            plans.append(plan)
            partitions[plan] = partition
    info = {'candidate_actions': len(plans), 'raw_candidate_plans': len(raw),
            'raw_small_plans': small_raw_count, 'candidate_cap': max_plans,
            'candidate_truncated': max(0, len(raw) - len(chosen)),
            'nonbond_candidates_rejected': len(chosen) - len(plans),
            'flow_calls': flow_calls, 'flow_call_cap': 2 * FLOW_SEEDS_PER_RANKING,
            'depth_cap': depth, 'seeded_components': seeded_components,
            'pending_remainder_retained': bool(pending_valid),
            'centrality_seconds': centrality_finished - start,
            'small_pool_seconds': small_finished - centrality_finished,
            'flow_seconds': flow_finished - small_finished,
            'validation_and_cap_seconds': time.perf_counter() - flow_finished,
            'pool_prerank': 'mean_error_weighted_edge_betweenness',
            'topology_cache': workspace.delta(cache_before),
            'raw_candidate_depth_counts': depth_counts(raw),
            'capped_candidate_depth_counts': depth_counts(chosen),
            'candidate_depth_counts': depth_counts(plans)}
    if diagnostic_raw:
        # Observable plans only, requested by separate offline diagnostics.
        # Main selectors never request or consume this explanatory export.
        info['raw_plan_edges'] = [list(plan) for plan in sorted(raw)]
    return plans, partitions, probabilities, weighted, info


def completion_score(plan, partition, scores, probabilities, observations, fn_weight,
                     *, endpoint_aware=True):
    left, right = partition
    left_set, right_set = set(left), set(right)
    predicted_pairs = scores.cross_sum(left, right)
    if endpoint_aware:
        conditioned = dict(observations)
        conditioned.update({edge: False for edge in plan})
        for edge, answer in conditioned.items():
            u, v = edge
            if ((u in left_set and v in right_set) or (v in left_set and u in right_set)):
                predicted_pairs += int(answer) - scores.p(u, v)
    utility = len(left) * len(right) - (1. + fn_weight) * predicted_pairs
    success = prod(1. - probabilities[edge] for edge in plan)
    return success * utility / len(plan), utility, success


def select_bounded_plan(g, scores, verified, remaining, method, observations, state,
                        fn_weight=1.0):
    if fn_weight < 0:
        raise ValueError('FN weight must be nonnegative')
    if remaining < 1:
        return None, {'reason': 'no_budget_or_candidates'}
    observations = observations or {}
    if '_topology_workspace' not in state:
        state['_topology_workspace'] = PlannerWorkspace()
    workspace = state['_topology_workspace']
    cache_before = dict(workspace.counts)
    adaptive = method == 'cut_plan_adaptive'
    pool_only = method == 'risk_seed_pool'
    singleton_only = method == 'cut_plan_fixed_singleton'
    previous = tuple(tuple(edge) for edge in state.get('pending_plan', ())) if adaptive else ()
    invalidated = any(observations.get(edge) is True for edge in previous)
    remainder = () if invalidated else tuple(edge for edge in previous if edge not in verified)
    plans, partitions, probabilities, weighted, info = build_plan_pool(
        g, scores, verified, remaining,
        allow_long=method in ('cut_plan_fixed', 'cut_plan_adaptive', 'cut_plan_fixed_singleton'),
        pending_plan=remainder, workspace=workspace)
    common_pool_empty = not plans
    if singleton_only:
        # This is an action-set intervention on the shared capped, validated
        # pool, not a depth-one generator. Never refill discarded candidates.
        common_count = len(plans)
        plans = [plan for plan in plans if len(plan) == 1]
        info.update(action_set_filter='singleton_after_shared_cap_and_bond_validation',
                    singleton_filtered_candidates=common_count - len(plans))
    info.update(scored_candidate_actions=len(plans),
                scored_candidate_depth_counts=depth_counts(plans),
                selected_candidate_depth_counts=depth_counts(()))
    info['previous_plan_invalidated_by_positive'] = invalidated
    transition = ('invalidated_positive' if invalidated else
                  'completed' if previous and not remainder else
                  'retained_for_reconsideration' if info['pending_remainder_retained'] else
                  'discarded_nonbond_budget_or_ineligible' if remainder else 'no_previous_plan')
    info.update(pending_transition=transition, previous_planned_depth=len(previous))
    ranked = []
    scoring_start = time.perf_counter()
    for plan in plans:
        value, utility, success = completion_score(plan, partitions[plan], scores, probabilities,
                                                   observations, fn_weight, endpoint_aware=not pool_only)
        ranked.append((value, plan, utility, success))
    info['plan_scoring_seconds'] = time.perf_counter() - scoring_start
    if ranked:
        value, plan, utility, success = min(ranked, key=lambda row: (-row[0], len(row[1]), row[1]))
        info.update(selected_proxy_score=value, completion_utility_proxy=utility,
                    factorized_all_negative_probability=success)
        if value > 0:
            ordered = tuple(sorted(plan, key=lambda edge: (-probabilities[edge], edge)))
            info.update(planned_edges=[list(edge) for edge in ordered], planned_depth=len(ordered),
                        selected_candidate_depth_counts=depth_counts((plan,)),
                        expected_fixed_plan_abort_cost=expected_abort_cost(ordered, probabilities),
                        score_denominator='full_plan_pair_count_in_both_fixed_and_adaptive',
                        endpoint_aware=not pool_only, replan_after_each_answer=adaptive)
            if adaptive:
                if info['pending_remainder_retained']:
                    info['pending_transition'] = ('continued' if set(plan) == set(remainder) else 'replaced_by_higher_ranked_plan')
                state['pending_plan'] = ordered
                return ordered[:1], info
            # Pool-only holds the original canonical within-batch edge order.
            return (plan if pool_only else ordered), info
    state.pop('pending_plan', None)
    if info['pending_remainder_retained']:
        info['pending_transition'] = 'discarded_nonpositive_proxy'
    if not probabilities:
        return None, {**info, 'reason': 'no_budget_or_candidates'}
    # Exactly reuse the strong baseline's computation on the actual current
    # graph, including its deterministic tie rule; pool construction uses a
    # canonical graph and could differ by last-bit centrality rounding.
    baseline_bc = workspace.original_centrality(g)
    edge = min(probabilities, key=lambda e: (-baseline_bc[e] * (1. - probabilities[e]), e))
    return (edge,), {**info, 'fallback': 'error_weighted_edge_betweenness',
                     'fallback_trigger': ('empty_validated_pool' if common_pool_empty else
                                          'empty_singleton_pool' if not plans else 'nonpositive_proxy'),
                     'selected_candidate_depth_counts': depth_counts(((edge,),)),
                     'topology_cache': workspace.delta(cache_before),
                     'reason': 'centrality_continuation_after_nonpositive_or_empty_pool',
                     'planned_depth': 1, 'planned_edges': [list(edge)]}
