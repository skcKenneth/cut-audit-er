"""Independent GraphCR-style automatic repair, with explicit CPU adaptations.

JDIQ 2025 Section 4.3 / Algorithm 1 supplies the support-reassignment algorithm.
This is NOT exact author-code or published-experiment reproduction. Query
acquisition uses our separately documented low-budget bootstrap-ext adapter.
Unlike the verification-only policies, this pipeline may separate unqueried
pairs and undo consequences of paid answers through classifier predictions.
"""
from __future__ import annotations

import time
import networkx as nx
import numpy as np
from sklearn.ensemble import RandomForestClassifier

from .graph import Edge, edge_key, validate_graph
from .graphcr_adapter import initial_graph_features, select_graphcr_audit
from .metrics import evaluate
from .oracle import BudgetedOracle
from .scores import PairScores


def support_repair(g: nx.Graph, predicted_matches: dict[Edge, bool]):
    """Return a partition from fixed predicted edge signs, without gold access.

    Cluster membership moves only toward strictly greater signed-edge support.
    In ties the current membership persists; all iteration orders are sorted.
    An all-positive component stays intact (the algorithm's empty-seed case).
    """
    validate_graph(g)
    edges = {edge_key(*e) for e in g.edges}
    if edges != set(predicted_matches):
        raise ValueError("Predictions must cover exactly the input edges")
    if any(not isinstance(y, (bool, np.bool_)) for y in predicted_matches.values()):
        raise ValueError("Predicted matches must be boolean")
    output, total_moves, total_iterations = [], 0, 0
    for comp in sorted(nx.connected_components(g), key=lambda c: tuple(sorted(c))):
        h = g.subgraph(comp)
        negative = [e for e in sorted(edges) if e[0] in comp and not predicted_matches[e]]
        if not negative:
            output.append(tuple(sorted(comp)))
            continue
        seeds = sorted({v for e in negative for v in e})
        groups = {v: {v} for v in seeds}
        assignment = {v: v for v in seeds}

        def support(record, group):
            return sum(1 if predicted_matches[edge_key(record, other)] else -1
                       for other in h.neighbors(record) if other in groups[group])

        changed, iterations = True, 0
        while changed:
            changed = False
            iterations += 1
            # A transfer strictly improves signed within-cluster agreement.
            # Between insertions there are at most 2|E| such improvements.
            # The bound is deliberately conservative and never truncates silently.
            if iterations > (len(comp)+1)*(2*h.number_of_edges()+1):
                raise RuntimeError("Support reassignment did not converge")
            for group in seeds:
                for member in sorted(groups[group]):
                    if assignment.get(member) != group:
                        continue
                    for record in sorted(h.neighbors(member)):
                        if not predicted_matches[edge_key(record, member)]:
                            continue
                        previous = assignment.get(record)
                        if previous is None:
                            groups[group].add(record)
                            assignment[record] = group
                            changed = True
                        elif previous != group and support(record, group) > support(record, previous):
                            groups[previous].remove(record)
                            groups[group].add(record)
                            assignment[record] = group
                            total_moves += 1
                            changed = True
        # Every positive-edge region of a component with a negative edge should
        # touch a seed. Retain any exceptional unassigned node as a singleton.
        output.extend(tuple(sorted(members)) for members in groups.values() if members)
        output.extend((v,) for v in sorted(comp-set(assignment)))
        total_iterations += iterations
    partition = sorted(output)
    flattened = [v for group in partition for v in group]
    if set(flattened) != set(g) or len(flattened) != len(set(flattened)):
        raise AssertionError("Repair must preserve a disjoint complete partition")
    return partition, {"support_moves": total_moves, "support_iterations": total_iterations}


def partition_graph(nodes, partition):
    """Encode an output partition as stars solely for existing metric routines.

    These edges are not new matcher predictions, oracle labels or graph edits.
    """
    result = nx.Graph()
    result.add_nodes_from(nodes)
    for group in partition:
        result.add_edges_from((group[0], v) for v in group[1:])
    return result


def run_graphcr_native_cpu(g: nx.Graph, scores: PairScores, truth: dict[str, str],
                          budget: int, seed: int = 7, noise: float = 0.0,
                          fn_weight: float = 1.0) -> dict:
    """Offline oracle experiment with separately identified automatic repair.

    Gold enters only BudgetedOracle and evaluate. There are no free initial
    repair labels. The same frozen matcher inputs are shared with audit methods.
    """
    validate_graph(g)
    if set(g) != set(scores.ids):
        raise ValueError("Graph and score IDs differ")
    start = time.perf_counter()
    original, query_graph = g.copy(), g.copy()
    local_scores = scores.copy()
    oracle = BudgetedOracle(truth, budget, noise, seed)
    edges, features, _, _ = initial_graph_features(original, local_scores, {})
    initial = {"spent": 0, **evaluate(original, truth, fn_weight)}
    trace, decisions, partition_trace = [initial], [], []
    counterfactual_trace = [dict(initial)]
    counterfactual_seconds = 0.0
    selector_seconds = model_seconds = repair_seconds = 0.0
    stop_reason, batch = "budget_exhausted", 0
    latest_partition = sorted(tuple(sorted(c)) for c in nx.connected_components(original))
    all_features = np.vstack([features[e] for e in edges]) if edges else np.empty((0, 8))
    while oracle.remaining:
        t = time.perf_counter()
        q, selection_info = select_graphcr_audit(
            query_graph, local_scores, oracle.observed, oracle.remaining, seed)
        elapsed = time.perf_counter()-t
        selector_seconds += elapsed
        if q is None:
            stop_reason = selection_info.get("reason", "no_action")
            break
        if len(q) > oracle.remaining or len(q) != len(set(q)):
            raise AssertionError("Invalid paid query batch")
        batch += 1
        for edge in q:
            if edge in oracle.observed or not query_graph.has_edge(*edge):
                raise AssertionError("Repeated or missing pair query")
            answer = oracle.query(*edge)
            if not answer:
                query_graph.remove_edge(*edge)
            # Evaluate the deletion-only response to this same paid answer.
            # This adds no oracle access and cannot affect query acquisition.
            counterfactual_start = time.perf_counter()
            counterfactual_trace.append({"spent": oracle.spent,
                                         **evaluate(query_graph, truth, fn_weight)})
            counterfactual_seconds += time.perf_counter()-counterfactual_start
            decisions.append({"batch": batch, "pair": list(edge), "observed_match": answer,
                              "spent": oracle.spent, "selection_seconds": elapsed,
                              "selection_info": selection_info})
            observed_edges = sorted(oracle.observed)
            t = time.perf_counter()
            model = RandomForestClassifier(n_estimators=100, random_state=seed+oracle.spent, n_jobs=1)
            model.fit(np.vstack([features[e] for e in observed_edges]),
                      [int(oracle.observed[e]) for e in observed_edges])
            predictions = {e: bool(y) for e, y in zip(edges, model.predict(all_features))}
            model_seconds += time.perf_counter()-t
            t = time.perf_counter()
            latest_partition, repair_info = support_repair(original, predictions)
            repaired = partition_graph(original.nodes, latest_partition)
            repair_seconds += time.perf_counter()-t
            member_of = {v: i for i, c in enumerate(latest_partition) for v in c}
            unqueried_separated = sum(e not in oracle.observed and member_of[e[0]] != member_of[e[1]]
                                     for e in edges)
            partition_trace.append({"spent": oracle.spent,
                                    "partition": [list(c) for c in latest_partition],
                                    "predicted_negative_edges": sum(not y for y in predictions.values()),
                                    "unqueried_initial_edges_separated": unqueried_separated,
                                    "observed_classes": sorted({int(y) for y in oracle.observed.values()}),
                                    **repair_info})
            trace.append({"spent": oracle.spent, **evaluate(repaired, truth, fn_weight)})
    return {"method": "graphcr_native_cpu_reimplementation",
            "contract": "native_style_automatic_partition_repair",
            "implementation_version": "canonical_graph_order_v1",
            "counterfactual_contract": "verification_only_same_paid_stream",
            "counterfactual_additional_oracle_labels": 0,
            "counterfactual_evaluation_seconds": counterfactual_seconds,
            "verification_only_counterfactual_trace": counterfactual_trace,
            "verification_only_counterfactual_final": counterfactual_trace[-1],
            "verification_only_counterfactual_loss_reduction": initial["loss"]-counterfactual_trace[-1]["loss"],
            "native_minus_counterfactual_final_loss": trace[-1]["loss"]-counterfactual_trace[-1]["loss"],
            "native_minus_counterfactual_final_fp": trace[-1]["fp"]-counterfactual_trace[-1]["fp"],
            "native_minus_counterfactual_final_fn": trace[-1]["fn"]-counterfactual_trace[-1]["fn"],
            "exact_published_reproduction": False, "verified_only": False,
            "query_acquisition": "graphcr_bootstrap_audit_low_budget_adapter",
            "requested_budget": budget, "spent": oracle.spent,
            "noise": noise, "seed": seed, "fn_weight": fn_weight,
            "stop_reason": stop_reason, "complete": True,
            "seconds": time.perf_counter()-start,
            "selection_seconds": selector_seconds, "model_fit_seconds": model_seconds,
            "automatic_repair_seconds": repair_seconds, "score_accesses": local_scores.calls,
            "trace": trace, "decisions": decisions, "native_partition_trace": partition_trace,
            "partition": [list(c) for c in latest_partition],
            "initial": initial, "final": trace[-1],
            "loss_reduction": initial["loss"]-trace[-1]["loss"],
            "deviations": ["four_label_warmup_two_label_batches", "twenty_forests_ten_trees_committee",
                           "source_link_features_and_weighted_degree_omitted",
                           "no_source_specific_weak_link_prepruning", "no_free_feature_duplicate_labels",
                           "all_positive_components_preserved", "deterministic_support_ties",
                           "no_author_code_reproduction", "canonical_nodes_edges_v1"]}
