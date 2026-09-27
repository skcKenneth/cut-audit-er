"""Independent V6 saved-state diagnostics; no selector imports or acquisitions.

``audit_visible_state`` never accepts evaluator labels. ``evaluate_visible_state``
is called by a different CLI process only after the visible outputs are frozen.
Complete scoring means the saved searched pool, not all graph-wide actions.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import hashlib
import json
import math
import time

import networkx as nx
import numpy as np

from cut_audit_er.bounded_planner import canonical_graph, completion_score
from cut_audit_er.covered_planner import completion_upper_bound
from scripts.review_v5.opportunities import canonical, independent_partition, node_bipartition_bonds


def require(value, message):
    if not value:
        raise ValueError(message)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def partition(graph):
    return sorted(sorted(c) for c in nx.connected_components(graph))


def metric(parts, reference):
    """All unordered pairs, including unavoidable cross-component FN."""
    choose = lambda n: n * (n - 1) // 2
    predicted = sum(choose(len(c)) for c in parts)
    true_positive = sum(sum(choose(n) for n in Counter(reference[u] for u in c).values()) for c in parts)
    gold = sum(choose(n) for n in Counter(reference.values()).values())
    return {"fp": predicted - true_positive, "fn": gold - true_positive,
            "loss": predicted + gold - 2 * true_positive}


def plans(value, name):
    result = [canonical(q) for q in value]
    require(len(set(result)) == len(result), "Duplicate candidate in " + name)
    return result


def audit_visible_state(graph, scores, batch, ordered_observations, *, source_identity):
    """Fully score saved Full pool and independently check legal small bonds.

    Ordered observations MUST be reconstructed from the paid-event sequence, not
    from the sorted convenience list in a saved batch. Floating endpoint updates
    depend on that insertion order. The graph keeps original node/adjacency order.
    """
    started = time.perf_counter()
    require(isinstance(source_identity, str) and len(source_identity) == 64,
            "A visible source identity hash is required")
    require(set(graph) == set(scores.ids), "Visible score membership mismatch")
    remaining = batch["remaining"]
    require(type(remaining) is int and remaining > 0, "Invalid remaining budget")
    observations = {}
    for row in ordered_observations:
        edge = tuple(row["pair"])
        require(edge == tuple(sorted(edge)) and len(edge) == 2 and edge[0] != edge[1]
                and type(row["answer"]) is bool and edge not in observations,
                "Invalid/repeated ordered observation")
        require(all(u in graph for u in edge), "Observed membership mismatch")
        require(graph.has_edge(*edge) == row["answer"], "Paid answer/topology mismatch")
        observations[edge] = row["answer"]
    require(len(observations) == batch["spent_before"], "Missing paid observations")
    require([{ "pair": list(e), "answer": a} for e, a in sorted(observations.items())]
            == batch["observed_answers_before"], "Saved ordered history differs")
    require(partition(graph) == batch["partition_before"], "Saved partition differs")
    require([list(sorted(e)) for e in graph.edges] == batch["edges_before"], "Saved ordered edges differ")
    trace, info = batch["candidate_trace"], batch["selection_info"]
    require(trace == info["candidate_trace"], "Saved candidate trace copies differ")
    require(info["cap_applied"] is False and info["action_set_filter"] == "none",
            "V6 audit requires the frozen Full action set")
    raw = plans(trace["union_generated"], "union")
    require(raw == sorted(raw), "Union lexical order differs")
    require(plans(trace["capped_order"], "capped") == raw, "Full candidate cap must be identity")
    legacy = plans(trace["legacy_generated"], "legacy")
    enumerated = plans(trace["enumerated"], "enumerated")
    require(set(raw) == set(legacy) | set(enumerated), "Union construction mismatch")

    # This ordering duplicates the mathematical canonical graph construction,
    # not candidate generation or selector ranking. Bond legality uses a separate
    # delete-and-connected-components implementation.
    g = canonical_graph(graph)
    components = [g.subgraph(nodes).copy() for nodes in sorted(tuple(sorted(c)) for c in nx.connected_components(g))]
    owner = {n: index for index, component in enumerate(components) for n in component}
    legal, parts = [], {}
    for q in raw:
        require(1 <= len(q) <= min(4, remaining), "Candidate violates width/budget")
        require(not set(q).intersection(observations), "Candidate queries a paid edge")
        require(all(g.has_edge(*e) for e in q), "Candidate contains missing edge")
        require(all(owner[u] == owner[q[0][0]] for e in q for u in e), "Candidate crosses initial components")
        cut = independent_partition(components[owner[q[0][0]]], q)
        if cut is not None:
            legal.append(q)
            parts[q] = tuple(tuple(side) for side in cut)
    require(legal == plans(trace["validated_order"], "validated"), "Legal candidate order differs")
    require(legal == plans(trace["eligible_order"], "eligible"), "Full eligibility differs")
    component_rows, exact_set = [], set()
    for index, component in enumerate(components):
        small = len(component) <= 16 and component.number_of_edges() <= 16
        independent = node_bipartition_bonds(component, observations, min(4, remaining)) if small else []
        if small:
            exact_set.update(independent)
        component_rows.append({"component": index, "nodes": list(component), "node_count": len(component),
                               "edge_count": component.number_of_edges(), "complete_small": small,
                               "status": "complete_small" if small else "large_coverage_unknown",
                               "independent_bonds": len(independent) if small else None,
                               "searched_bonds": sum(owner[q[0][0]] == index for q in legal)})
    require(exact_set == set(enumerated), "Small-component enumeration mismatch")

    ds = scores.copy()
    ds.calls += 2 * int(ds.matrix.size)
    maximum = float(np.max(np.abs(ds.matrix - ds.matrix.T), initial=0.))
    asymmetry = math.nextafter(maximum, math.inf) if maximum else 0.
    require(asymmetry == info["asymmetry_bound"], "Saved asymmetry bound differs")
    probabilities = {e: ds.p(*e) for e in sorted({e for q in legal for e in q})}
    bound_records = {canonical(row["edges"]): row for row in trace["bound_records"]}
    require(len(bound_records) == len(trace["bound_records"]) == len(legal), "Missing/duplicate bounds")
    scored = plans(trace["scored_order"], "scored")
    score_records = {canonical(row["edges"]): row for row in trace["score_records"]}
    require(len(score_records) == len(trace["score_records"]) == len(scored), "Missing/duplicate saved scores")
    records, values, bounds = [], {}, {}
    for q in legal:
        upper, description = completion_upper_bound(q, parts[q], probabilities, len(observations), 1., asymmetry)
        require({k: v for k, v in bound_records[q].items() if k != "edges"} == description, "Saved upper bound differs")
        value, utility, success = completion_score(q, parts[q], ds, probabilities, observations, 1.)
        require(all(math.isfinite(x) for x in (value, utility, success)), "Nonfinite full score")
        require(value <= upper, "Certificate counterexample: score exceeds upper bound")
        values[q], bounds[q] = value, upper
        row = {"edges": [list(e) for e in q], "partition": [list(side) for side in parts[q]],
               "component": owner[q[0][0]], "depth": len(q), "proxy": value, "utility": utility,
               "success_product": success, "upper_bound": upper if math.isfinite(upper) else None,
               "upper_bound_finite": math.isfinite(upper), "was_scored": q in score_records}
        if q in score_records:
            require(all(score_records[q][k] == row[k] for k in ("proxy", "utility", "success_product")),
                    "Saved completion score differs (including floating order)")
        records.append(row)
    order = sorted(legal, key=lambda q: (-bounds[q], len(q), q))
    require(order == plans(trace["screening_order"], "screening"), "UB screening order differs")
    require(order[:64] == plans(trace["evaluation_prefix_order"], "evaluation prefix"), "Score allocation prefix differs")
    expected_scored = []
    for q in order[:64]:
        expected_scored.append(q)
        incumbent = min(expected_scored, key=lambda p: (-values[p], len(p), p))
        count = len(expected_scored)
        if values[incumbent] > 0 and count < len(order) and values[incumbent] > bounds[order[count]]:
            break
    require(scored == expected_scored, "Recorded scoring/pruning trace differs")
    incumbent = min(scored, key=lambda q: (-values[q], len(q), q)) if scored else None
    winner = min(legal, key=lambda q: (-values[q], len(q), q)) if legal else None
    unscored = [q for q in legal if q not in set(scored)]
    next_upper = max((bounds[q] for q in unscored), default=None)
    strict = bool(incumbent and values[incumbent] > 0 and next_upper is not None and values[incumbent] > next_upper)
    certificate = "empty_searched_pool" if not legal else "all_searched_candidates_scored" if not unscored else "strict_upper_bound_separation" if strict else "score_limit_uncertified"
    require(info["surrogate_certificate_status"] == certificate, "Recorded certificate status differs")
    require(info["surrogate_argmax_certified"] == (bool(legal) and (not unscored or strict)), "Certificate Boolean differs")
    require(info["scored_candidate_actions"] == len(scored) and info["unscored_candidate_actions"] == len(unscored)
            and info["candidate_actions"] == len(legal), "Saved pool/scoring counts differ")
    require(info["max_unscored_upper_bound"] == (next_upper if next_upper is None or math.isfinite(next_upper) else None)
            and info["max_unscored_upper_bound_finite"] == (next_upper is None or math.isfinite(next_upper)),
            "Saved maximum unscored bound differs")
    if incumbent is not None:
        saved = score_records[incumbent]
        require(info["selected_proxy_score"] == saved["proxy"]
                and info["completion_utility_proxy"] == saved["utility"]
                and info["factorized_all_negative_probability"] == saved["success_product"],
                "Saved incumbent score metadata differs")
    if info["surrogate_argmax_certified"]:
        require(incumbent == winner, "Certified incumbent differs from full-score argmax")
    positive = incumbent is not None and values[incumbent] > 0
    selected = canonical(batch["action"])
    if positive:
        require(not info.get("fallback") and canonical(trace["selected_plan"]) == incumbent == selected,
                "Selected plan differs from scored incumbent")
        ordered = [list(e) for e in sorted(incumbent, key=lambda e: (-probabilities[e], e))]
        require(batch["action"] == batch["planned_action"] == ordered, "Fixed-batch paid query order differs")
    else:
        require(bool(info.get("fallback")) and trace["selected_plan"] == [] and len(selected) == 1,
                "Nonpositive pool fallback metadata differs")
        eligible = sorted(tuple(sorted(e)) for e in graph.edges if tuple(sorted(e)) not in observations)
        bc = {tuple(sorted(e)): v for e, v in nx.edge_betweenness_centrality(graph).items()}
        expected = min(eligible, key=lambda e: (-bc[e] * (1. - ds.p(*e)), e))
        require(selected == (expected,), "BC fallback choice differs")
    require(batch["batch_fully_recorded"] and batch["recorded_queries"] == len(selected), "Incomplete paid batch")
    for row in records:
        q = canonical(row["edges"])
        row["selected"] = q == selected
        row["unscored_reason"] = "scored" if q in score_records else "strict_upper_bound_pruned" if strict else "score_limit_unscored"
    identity = {"source_identity": source_identity, "nodes": list(graph),
                "adjacency": [[n, list(graph.adj[n])] for n in graph], "observations": ordered_observations,
                "remaining": remaining, "union": raw, "legal": legal, "fn_weight": 1,
                "method": "cut_plan_cover_fixed", "max_depth": 4, "score_cap": 64}
    return {"schema": "cut-audit-v6-visible-state-v1", "status": "passed",
            "state_sha256": fingerprint(identity), "source_identity": source_identity,
            "nodes": list(graph), "edges": [list(e) for e in graph.edges],
            "ordered_observations": ordered_observations, "remaining": remaining,
            "partition_before": partition(graph), "components": component_rows, "candidates": records,
            "selected_action": batch["action"], "fallback": bool(info.get("fallback")),
            "certificate_status": certificate, "certificate_for_selected_positive": positive and info["surrogate_argmax_certified"],
            "pool_argmax_certified": info["surrogate_argmax_certified"], "searched_pool_complete_audit": True,
            "small_component_bonds_complete": True, "graph_wide_bonds_complete": all(r["complete_small"] for r in component_rows),
            "pool_argmax": [list(e) for e in winner] if winner else None,
            "pool_max_proxy": values[winner] if winner else None,
            "selected_proxy": values[incumbent] if positive else None,
            "max_unscored_upper_bound": next_upper if next_upper is None or math.isfinite(next_upper) else None,
            "max_unscored_upper_bound_finite": next_upper is None or math.isfinite(next_upper),
            "strict_margin": values[incumbent] - next_upper if strict else None,
            "scored_count": len(scored), "pool_count": len(legal),
            "diagnostic_score_accesses": ds.calls, "selector_score_accesses": 0,
            "new_oracle_answers": 0, "diagnostic_seconds": time.perf_counter() - started}


def realized_action(graph, reference, action, before=None):
    """Independent direct partition recomputation; every committed edge is paid."""
    q = canonical(action)
    require(all(graph.has_edge(*e) for e in q), "Evaluator action has missing edge")
    before = before or metric(partition(graph), reference)
    after_graph = graph.copy()
    negatives = [e for e in q if reference[e[0]] != reference[e[1]]]
    after_graph.remove_edges_from(negatives)
    after = metric(partition(after_graph), reference)
    fp, fn = before["fp"] - after["fp"], after["fn"] - before["fn"]
    require(fp >= 0 and fn >= 0 and fp - fn == before["loss"] - after["loss"], "FP/FN conservation failed")
    gain = fp - fn
    return {"fp_removed": fp, "fn_added": fn, "loss_gain": gain, "query_cost": len(q),
            "negative_answers": len(negatives), "positive_answers": len(q) - len(negatives),
            "gain_per_query": gain / len(q), "after": after}


def evaluate_visible_state(visible, reference):
    """Offline all-knowing single-batch oracle comparison, never expected regret."""
    started = time.perf_counter()
    require(visible.get("schema") == "cut-audit-v6-visible-state-v1" and visible.get("status") in ("passed", "partial"),
            "Only frozen passed/explicit partial visible audit can be evaluated")
    require(set(reference) == set(visible["nodes"]), "Evaluator reference membership mismatch")
    graph = nx.Graph()
    graph.add_nodes_from(visible["nodes"]); graph.add_edges_from(visible["edges"])
    require(partition(graph) == visible["partition_before"], "Evaluator partition differs")
    for row in visible["ordered_observations"]:
        u, v = row["pair"]
        require(row["answer"] == (reference[u] == reference[v]), "Reference disagrees with paid answer")
    before = metric(partition(graph), reference)
    selected = realized_action(graph, reference, visible["selected_action"], before)
    rows = []
    # A legal bond leaves its component connected whenever any committed edge
    # answers positive. For all-negative bonds use the stored independently
    # checked sides; independently recompute local partition counts as well.
    for record in visible["candidates"]:
        q = canonical(record["edges"])
        component = visible["components"][record["component"]]
        local = graph.subgraph(component["nodes"]).copy()
        cut = independent_partition(local, q)
        require(cut is not None and [list(side) for side in cut] == record["partition"], "Frozen bond partition differs")
        local_reference = {n: reference[n] for n in local}
        outcome = realized_action(local, local_reference, q)
        left, right = (Counter(reference[n] for n in side) for side in cut)
        same_cross = sum(n * right.get(label, 0) for label, n in left.items())
        split = outcome["positive_answers"] == 0
        analytic_fp = len(cut[0]) * len(cut[1]) - same_cross if split else 0
        analytic_fn = same_cross if split else 0
        require(outcome["fp_removed"] == analytic_fp and outcome["fn_added"] == analytic_fn,
                "Direct partition/analytic bond outcome disagreement")
        rows.append({k: record[k] for k in ("edges", "component", "depth", "proxy", "was_scored", "selected", "unscored_reason")}
                    | {k: v for k, v in outcome.items() if k != "after"})
    # Include selected fallback and noop explicitly, even outside the searched
    # bond pool. Exact rationals avoid accidental floating rank/tie artefacts.
    selected_value = Fraction(selected["loss_gain"], selected["query_cost"])
    choices = [(Fraction(0), "noop", []), (selected_value, "actual_action", visible["selected_action"])]
    choices += [(Fraction(r["loss_gain"], r["query_cost"]), "searched_candidate", r["edges"]) for r in rows]
    best = max(v for v, _, _ in choices)
    gap = best - selected_value
    complete = visible["searched_pool_complete_audit"] is True
    component_rows = []
    for row in visible["components"]:
        labels = Counter(reference[n] for n in row["nodes"])
        n = len(row["nodes"])
        fp = n * (n - 1) // 2 - sum(v * (v - 1) // 2 for v in labels.values())
        component_rows.append({k: v for k, v in row.items() if k != "nodes"} | {"current_fp": fp})
    covered_fp = sum(r["current_fp"] for r in component_rows if r["complete_small"])
    return {"schema": "cut-audit-v6-offline-gain-v1", "status": "passed" if complete else "partial_lower_bound",
            "state_sha256": visible["state_sha256"], "before": before, "selected": selected,
            "fallback": visible["fallback"], "candidates": rows, "components": component_rows,
            "selected_positive_certificate": visible["certificate_for_selected_positive"],
            "best_known_gain_per_query": float(best), "best_known_value_fraction": [best.numerator, best.denominator],
            "single_batch_oracle_gap": float(gap), "gap_fraction": [gap.numerator, gap.denominator],
            "gap_scope": "exact_over_searched_pool_plus_actual_plus_noop" if complete else "lower_bound_over_known_candidates_plus_actual_plus_noop",
            "best_witnesses": [{"kind": kind, "edges": edges} for value, kind, edges in choices if value == best],
            "noop_gain": 0, "noop_query_cost": 0, "noop_value_convention": 0,
            "covered_fp": covered_fp, "total_fp": before["fp"],
            "fp_coverage": covered_fp / before["fp"] if before["fp"] else None,
            "zero_fp_denominator": before["fp"] == 0,
            "candidate_occurrences": len(rows), "new_oracle_answers": 0, "selector_score_accesses": 0,
            "offline_seconds": time.perf_counter() - started,
            "interpretation": "All-knowing realized single-batch comparison on reached states; not expected regret, calibration error, policy regret or causal loss decomposition"}
