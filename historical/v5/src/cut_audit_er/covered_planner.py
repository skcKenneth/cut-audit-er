"""Opt-in observable bond coverage and bounded surrogate search (V5).

Certificates concern the unchanged *computed floating-point* completion score
over this decision's searched pool. They do not certify repair quality, an
unsearched large component, or a conditional probability model. No gold enters.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from math import inf, isfinite, nextafter, prod
import time

import numpy as np

from .bounded_planner import (MAX_DEPTH, MAX_PLANS, bond_partition, build_plan_pool,
                              completion_score, depth_counts, expected_abort_cost)
from .graph import edge_key
from .planner_workspace import PlannerWorkspace

COVER_METHODS = ("cut_plan_cover_bccap", "cut_plan_bound_fixed", "cut_plan_cover_fixed",
                 "cut_plan_cover_singleton")
EXACT_NODE_CAP = 16
EXACT_EDGE_CAP = 16
UNIT_DENOMINATOR = 2 ** 53
CERTIFICATE_SCOPE = "computed_float_score_over_current_searched_pool"


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _up(value):
    """Outward rounding, including a positive operation rounded to zero."""
    _require(not np.isnan(value) and value >= 0, "Invalid nonnegative bound operation")
    return nextafter(value, inf) if isfinite(value) else inf


def _add_up(a, b):
    return 0. if a == b == 0. else _up(a + b)


def _mul_up(a, b):
    return 0. if a == 0. or b == 0. else _up(a * b)


def _fraction_up(value):
    rounded = float(value)
    return nextafter(rounded, inf) if Fraction.from_float(rounded) < value else rounded


def completion_upper_bound(plan, partition, probabilities, observation_count,
                           fn_weight=1., asymmetry_bound=0.):
    """Upper-bound the existing completion_score's binary64 result.

    C cross-pair terms and at most r endpoint corrections give a linear-form
    summation error gamma_K*K, K=C+2r. Near-symmetric PairScores add r*delta.
    q and (1+lambda) use the very same floating operations as completion_score.
    Outward operations then cover its final multiply/subtract/multiply/divide.
    See research/review_v5/NUMERIC_BOUND.md for assumptions and derivation.
    """
    _require(plan and 1 <= len(plan) <= MAX_DEPTH, "Invalid bound plan width")
    _require(type(observation_count) is int and observation_count >= 0, "Invalid observation count")
    _require(isfinite(fn_weight) and fn_weight >= 0, "Finite nonnegative FN weight required")
    _require(isfinite(asymmetry_bound) and asymmetry_bound >= 0, "Invalid asymmetry bound")
    c = len(partition[0]) * len(partition[1])
    r = observation_count + len(plan)
    k = c + 2 * r
    _require(c > 0 and k < UNIT_DENOMINATOR, "Partition outside numerical certificate scope")
    _require(all(isfinite(probabilities[e]) and 0 <= probabilities[e] <= 1 for e in plan),
             "Invalid candidate probabilities")
    # This is the actual rounded product used by completion_score, including
    # subtraction/product underflow; no independent-real-q claim is needed.
    q = prod(1. - probabilities[e] for e in plan)
    roundoff = _fraction_up(Fraction(k * k, UNIT_DENOMINATOR - k))
    asymmetry_error = _mul_up(float(r), asymmetry_bound)
    adjusted_sum_error = _add_up(roundoff, asymmetry_error)
    multiplier = 1. + fn_weight
    utility_upper = _add_up(float(c), _mul_up(multiplier, adjusted_sum_error))
    if q == 0.:
        upper = 0.
    else:
        upper = _up(_mul_up(q, utility_upper) / len(plan))
    return upper, {
        "cross_pairs": c, "endpoint_corrections_upper": r, "roundoff_k": k,
        "gamma_sum_error_upper": roundoff, "asymmetry_error_upper": asymmetry_error,
        "adjusted_sum_error_upper": adjusted_sum_error,
        "computed_all_negative_product": q,
        "upper_bound": upper if isfinite(upper) else None,
        "upper_bound_finite": isfinite(upper), "scope": CERTIFICATE_SCOPE}


def _numeric_preprocessing(scores, state):
    """Charge the one-run visible dense scan, without changing any score."""
    matrix = scores.matrix
    _require(not matrix.flags.writeable, "Numerical certificate requires immutable run scores")
    previous = state.get("_cover_numeric")
    if previous is not None and previous["matrix"] is matrix:
        return previous["delta"], {"numeric_scan_score_entry_reads": 0,
                                   "numeric_preprocessing_seconds": 0., "numeric_scan_cache_hit": True}
    start = time.perf_counter()
    # The two operands each read N^2 score entries. Charge these actual visible
    # score inspections to the same logical access counter, as well as telemetry.
    entries = 2 * int(matrix.size)
    scores.calls += entries
    maximum = float(np.max(np.abs(matrix - matrix.T), initial=0.))
    _require(isfinite(maximum), "Nonfinite score-matrix asymmetry")
    delta = _up(maximum) if maximum else 0.
    state["_cover_numeric"] = {"matrix": matrix, "delta": delta}
    return delta, {"numeric_scan_score_entry_reads": entries,
                   "numeric_preprocessing_seconds": time.perf_counter() - start,
                   "numeric_scan_cache_hit": False}


def enumerate_visible_bonds(component, verified, depth, *, workspace=None):
    """Enumerate eligible edge subsets in a visible, size-qualified component.

    All subsets of width1..min(4,remaining) are tested; no gold-negative shortlist,
    hidden quality score, global enumeration cap, or partial-completion result.
    The supplied workspace is run-private and owns this component, when used.
    """
    _require(0 <= depth <= MAX_DEPTH, "Unsupported enumeration depth")
    eligible = sorted(edge_key(*e) for e in component.edges if edge_key(*e) not in verified)
    qualified = len(component) <= EXACT_NODE_CAP and component.number_of_edges() <= EXACT_EDGE_CAP
    info = {"nodes": len(component), "edges": component.number_of_edges(), "eligible_edges": len(eligible),
            "qualified": qualified, "enumerated_subsets": 0, "bonds": 0,
            "status": "complete" if qualified else "oversized_not_enumerated"}
    parts = {}
    if qualified:
        for width in range(1, min(depth, len(eligible)) + 1):
            for plan in combinations(eligible, width):
                info["enumerated_subsets"] += 1
                partition = (workspace.bond(component, plan, bond_partition) if workspace is not None
                             else bond_partition(component, plan))
                if partition is not None:
                    parts[plan] = partition
    info["bonds"] = len(parts)
    return parts, info


@dataclass
class CoverPool:
    raw: tuple
    partitions: dict
    probabilities: dict
    weighted: dict
    info: dict
    trace: dict


def build_cover_pool(g, scores, verified, remaining, *, include_exact, workspace=None):
    """Retain the old raw generator, adding only visible complete small pools."""
    _require(remaining >= 1, "A positive remaining budget is required")
    workspace = workspace if workspace is not None else PlannerWorkspace()
    started = time.perf_counter()
    _, _, probabilities, weighted, old_info = build_plan_pool(
        g, scores, verified, remaining, allow_long=True, diagnostic_raw=True, workspace=workspace)
    legacy = {tuple(tuple(e) for e in plan) for plan in old_info.pop("raw_plan_edges")}
    components = workspace.components()
    owners = {node: component for component in components for node in component}
    enumerated, component_rows = {}, []
    before_enum = dict(workspace.counts)
    enum_start = time.perf_counter()
    for component in components:
        if include_exact:
            generated, row = enumerate_visible_bonds(component, verified, min(MAX_DEPTH, remaining), workspace=workspace)
            enumerated.update(generated)
        else:
            row = {"nodes": len(component), "edges": component.number_of_edges(),
                   "eligible_edges": sum(edge_key(*e) not in verified for e in component.edges),
                   "qualified": len(component) <= EXACT_NODE_CAP and component.number_of_edges() <= EXACT_EDGE_CAP,
                   "enumerated_subsets": 0, "bonds": 0, "status": "not_requested"}
        component_rows.append({"nodes_order": list(component), **row})
    enumeration_seconds = time.perf_counter() - enum_start
    enumeration_cache = workspace.delta(before_enum)
    raw = tuple(sorted(legacy | set(enumerated)))
    partitions = dict(enumerated)
    validation_start = time.perf_counter()
    for plan in raw:
        if plan not in partitions:
            partition = workspace.bond(owners[plan[0][0]], plan, bond_partition)
            if partition is not None:
                partitions[plan] = partition
    complete = include_exact and all(row["qualified"] for row in component_rows)
    info = {**old_info, "legacy_raw_candidate_plans": len(legacy),
            "raw_candidate_plans": len(raw), "raw_candidate_depth_counts": depth_counts(raw),
            "enumerated_candidate_plans": len(enumerated),
            "added_candidate_plans": len(set(enumerated) - legacy),
            "union_validated_candidates": len(partitions),
            "union_nonbond_rejections": len(raw) - len(partitions),
            "exhaustive_components": sum(row["status"] == "complete" for row in component_rows),
            "oversized_components": sum(not row["qualified"] for row in component_rows),
            "enumerated_subsets": sum(row["enumerated_subsets"] for row in component_rows),
            "component_enumeration_node_cap": EXACT_NODE_CAP, "component_enumeration_edge_cap": EXACT_EDGE_CAP,
            "global_enumeration_cap": None, "full_graph_bond_pool_complete": complete,
            "small_component_bond_pool_complete": include_exact,
            "enumeration_seconds": enumeration_seconds, "enumeration_topology_cache": enumeration_cache,
            "union_validation_seconds": time.perf_counter() - validation_start,
            "cover_pool_seconds": time.perf_counter() - started,
            "pool_scope": "union_of_old_raw_and_complete_qualified_components" if include_exact else "old_raw_generator_before_cap"}
    trace = {"legacy_generated": sorted(legacy), "enumerated": sorted(enumerated), "union_generated": list(raw),
             "validated_order": [plan for plan in raw if plan in partitions], "components": component_rows}
    return CoverPool(raw, partitions, probabilities, weighted, info, trace)


def _validate_observations(observations, verified):
    for pair, answer in observations.items():
        _require(isinstance(pair, tuple) and len(pair) == 2 and pair == edge_key(*pair)
                 and pair[0] != pair[1] and type(answer) is bool,
                 "Canonical distinct-pair boolean observations required")
        _require(pair in verified, "Every paid observation must be verified")


def select_covered_plan(g, scores, verified, remaining, method, observations, state, fn_weight=1.):
    """Use unchanged fixed score/order/batch/fallback, with at most64 scores."""
    _require(method in COVER_METHODS, "Unknown covered planner")
    _require(isfinite(fn_weight) and fn_weight >= 0, "Finite nonnegative FN weight required")
    if remaining < 1:
        return None, {"reason": "no_budget_or_candidates"}
    observations = observations or {}
    state = state if state is not None else {}
    _validate_observations(observations, verified)
    if "_topology_workspace" not in state:
        state["_topology_workspace"] = PlannerWorkspace()
    workspace = state["_topology_workspace"]
    before = dict(workspace.counts)
    bccap = method == "cut_plan_cover_bccap"
    singleton = method == "cut_plan_cover_singleton"
    pool = build_cover_pool(g, scores, verified, remaining,
                           include_exact=method != "cut_plan_bound_fixed", workspace=workspace)
    info, trace = pool.info, pool.trace
    eligible = [plan for plan in pool.raw if plan in pool.partitions and (not singleton or len(plan) == 1)]
    trace["eligible_order"] = list(eligible)
    trace["bound_records"] = []
    info.update(action_set_filter="singleton_after_union_validation_before_ub" if singleton else "none",
                singleton_filtered_candidates=sum(len(p) > 1 for p in pool.partitions) if singleton else 0,
                candidate_cap=MAX_PLANS if bccap else None, cap_applied=bccap, score_evaluation_cap=MAX_PLANS,
                numeric_scan_score_entry_reads=0, numeric_preprocessing_seconds=0., numeric_scan_cache_hit=False,
                asymmetry_bound=None, bound_evaluations=0, selected_candidate_depth_counts=depth_counts(()),
                candidate_depth_counts=depth_counts(eligible), candidate_actions=len(eligible),
                replan_after_each_answer=False, endpoint_aware=True,
                previous_plan_invalidated_by_positive=False, pending_transition="no_previous_plan",
                previous_planned_depth=0, surrogate_argmax_certified=False, certificate_scope=CERTIFICATE_SCOPE,
                max_unscored_upper_bound=None, max_unscored_upper_bound_finite=True)
    bounds = {}
    bound_start = time.perf_counter()
    if bccap:
        # Cap the *raw union* in exactly the original BC order, then validate.
        # No invalid/filtered slot is refilled. Validation work done above does
        # not change this action-set control's cap-before-validation semantics.
        order = sorted(pool.raw, key=lambda q: (-sum(pool.weighted[e] for e in q) / len(q), len(q), q))
        capped = order[:MAX_PLANS]
        to_score = [plan for plan in capped if plan in pool.partitions]
        info["candidate_stage_contract"] = "raw_union_then_bc_cap_then_bond_validation_then_score"
        info["pool_prerank"] = "mean_error_weighted_edge_betweenness"
    else:
        delta, numeric_info = _numeric_preprocessing(scores, state)
        info.update(numeric_info, asymmetry_bound=delta)
        for plan in eligible:
            upper, description = completion_upper_bound(plan, pool.partitions[plan], pool.probabilities,
                                                        len(observations), fn_weight, delta)
            bounds[plan] = upper
            trace["bound_records"].append({"edges": plan, **description})
        order = sorted(eligible, key=lambda q: (-bounds[q], len(q), q))
        capped = order[:MAX_PLANS]
        to_score = capped
        info["bound_evaluations"] = len(bounds)
        info["candidate_stage_contract"] = "raw_union_then_validation_then_optional_singleton_then_ub_order_then_at_most64_scores"
        info["pool_prerank"] = "conservative_computed_float_completion_upper_bound"
    info["bound_and_order_seconds"] = time.perf_counter() - bound_start
    trace["screening_order"] = order
    # Candidate truncation and the finite full-score budget are different
    # interventions. In UB variants the candidate-cap stage is identity.
    trace["capped_order"] = capped if bccap else list(pool.raw)
    trace["evaluation_prefix_order"] = to_score
    trace["scored_order"], trace["score_records"] = [], []
    ranked = []
    best = None
    score_start = time.perf_counter()
    for plan in to_score:
        value, utility, success = completion_score(plan, pool.partitions[plan], scores, pool.probabilities,
                                                   observations, fn_weight)
        _require(all(isfinite(x) for x in (value, utility, success)), "Nonfinite completion score")
        if not bccap:
            _require(value <= bounds[plan], "Computed score exceeds its conservative numerical bound")
        row = (value, plan, utility, success)
        ranked.append(row)
        best = min(ranked, key=lambda item: (-item[0], len(item[1]), item[1]))
        trace["scored_order"].append(plan)
        trace["score_records"].append({"edges": plan, "proxy": value, "utility": utility, "success_product": success})
        count = len(ranked)
        if not bccap and best[0] > 0 and count < len(order) and best[0] > bounds[order[count]]:
            info.update(surrogate_argmax_certified=True, surrogate_certificate_status="strict_upper_bound_separation")
            break
    info["plan_scoring_seconds"] = time.perf_counter() - score_start
    scored = trace["scored_order"]
    scored_set = set(scored)
    unscored = [plan for plan in eligible if plan not in scored_set]
    if not eligible:
        info["surrogate_certificate_status"] = "empty_searched_pool"
    elif not unscored:
        info.update(surrogate_argmax_certified=True, surrogate_certificate_status="all_searched_candidates_scored")
    elif not info["surrogate_argmax_certified"]:
        info["surrogate_certificate_status"] = "bc_cap_uncertified" if bccap else "score_limit_uncertified"
    if not bccap and unscored:
        upper = max(bounds[p] for p in unscored)
        info.update(max_unscored_upper_bound=upper if isfinite(upper) else None,
                    max_unscored_upper_bound_finite=isfinite(upper))
    info.update(scored_candidate_actions=len(scored), scored_candidate_depth_counts=depth_counts(scored),
                capped_candidate_depth_counts=depth_counts(trace["capped_order"]),
                candidate_truncated=max(0, len(order) - len(capped)) if bccap else 0,
                score_limit_unscored=len(unscored),
                nonbond_candidates_rejected=sum(p not in pool.partitions for p in trace["capped_order"]),
                unscored_candidate_actions=len(unscored),
                scored_positive_candidates=sum(row[0] > 0 for row in ranked),
                candidate_trace=trace)
    trace["selected_plan"] = []
    if best is not None:
        value, plan, utility, success = best
        info.update(selected_proxy_score=value, completion_utility_proxy=utility,
                    factorized_all_negative_probability=success)
        if value > 0:
            ordered = tuple(sorted(plan, key=lambda e: (-pool.probabilities[e], e)))
            trace["selected_plan"] = plan
            info.update(planned_edges=[list(e) for e in ordered], planned_depth=len(ordered),
                        selected_candidate_depth_counts=depth_counts((plan,)),
                        expected_fixed_plan_abort_cost=expected_abort_cost(ordered, pool.probabilities),
                        score_denominator="full_plan_pair_count_in_both_fixed_and_adaptive",
                        topology_cache=workspace.delta(before))
            # Lack of a certificate never discards a positive incumbent.
            return ordered, info
    if not pool.probabilities:
        return None, {**info, "reason": "no_budget_or_candidates", "topology_cache": workspace.delta(before)}
    bc = workspace.original_centrality(g)
    edge = min(pool.probabilities, key=lambda e: (-bc[e] * (1. - pool.probabilities[e]), e))
    return (edge,), {**info, "fallback": "error_weighted_edge_betweenness",
                     "fallback_trigger": "empty_singleton_pool" if singleton and pool.partitions and not eligible else
                                         "empty_validated_pool" if not ranked else "nonpositive_proxy",
                     "reason": "centrality_continuation_after_nonpositive_or_empty_pool",
                     "planned_edges": [list(edge)], "planned_depth": 1,
                     "selected_candidate_depth_counts": depth_counts(((edge,),)),
                     "topology_cache": workspace.delta(before)}
