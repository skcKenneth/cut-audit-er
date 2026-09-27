"""Label-blind policy-score stress, not matcher recalibration.

The graph topology is an immutable input. The caller copies edge attributes
from the returned scores before policy execution; see the recorded protocol.
"""
from __future__ import annotations

import hashlib
import json
import math
import time

import networkx as nx
import numpy as np

from cut_audit_er.graph import validate_graph
from cut_audit_er.scores import PairScores


def _temperature(values: np.ndarray, temperature: float) -> np.ndarray:
    """Stable sigmoid(logit(p)/T), preserving exactly zero and one."""
    result = np.asarray(values, dtype=float).copy()
    if temperature == 1:
        return result
    interior = (result > 0) & (result < 1)
    p = result[interior]
    logit = (np.log(p) - np.log1p(-p)) / temperature
    exp = np.exp(-np.abs(logit))
    result[interior] = np.where(logit >= 0, 1 / (1 + exp), exp / (1 + exp))
    return result


def transform_policy_scores(g: nx.Graph, scores: PairScores,
                            mode: str = "all_pair", temperature: float = 1.0
                            ) -> tuple[PairScores, dict]:
    """Return new scores and cost metadata without modifying either input.

    all_pair: expose the dense matcher scores, optionally temperature-perturbed.
    edge_only: read original graph-edge scores only, then impute nonedges using
    the maximum product along any initial-graph path. A zero-probability edge
    cannot transmit positive path support; unreachable nonedges receive zero.
    Direct edge scores are preserved even when another path has larger product.

    Temperature applies to visible input scores *before* path imputation. No
    graph thresholding, fitting, gold access or adaptive recomputation occurs.
    Preprocessing reads are counted separately because PairScores.copy() resets
    policy access counters. Dense representation and the same matcher fit remain
    shared costs: edge_only is an information ablation, not a sparse pipeline.
    """
    start = time.perf_counter()
    validate_graph(g)
    if set(g) != set(scores.ids):
        raise ValueError("Graph and score record IDs differ")
    if mode not in ("all_pair", "edge_only"):
        raise ValueError("Unknown policy score mode")
    if isinstance(temperature, bool) or not math.isfinite(float(temperature)) or temperature <= 0:
        raise ValueError("Temperature must be finite and strictly positive")
    temperature = float(temperature)
    n = len(scores.ids)
    edges = sorted(tuple(sorted((u, v))) for u, v in g.edges)
    topology = {"nodes": sorted(g), "edges": edges}
    topology_hash = hashlib.sha256(json.dumps(topology, sort_keys=True).encode()).hexdigest()
    input_calls = scores.calls
    shortest_path_calls = 0
    path_reachable_nonedges = 0
    underflow_nonedges = 0
    if mode == "all_pair":
        # The input matrix is symmetric. Read each distinct undirected pair
        # once; preserve the diagonal because it is not an oracle task.
        upper = np.triu_indices(n, 1)
        matrix = np.diag(np.diag(scores.matrix)).copy()
        values = _temperature(scores.matrix[upper], temperature)
        matrix[upper] = values
        matrix[(upper[1], upper[0])] = values
        read_pairs = len(values)
    else:
        matrix = np.eye(n, dtype=float)
        visible = np.array([scores.matrix[scores.index[u], scores.index[v]] for u, v in edges])
        values = _temperature(visible, temperature)
        read_pairs = len(edges)
        weighted = nx.Graph()
        weighted.add_nodes_from(scores.ids)
        edge_values = dict(zip(edges, map(float, values)))
        for (u, v), value in edge_values.items():
            if value > 0:
                weighted.add_edge(u, v, weight=-math.log(value))
        edge_set = set(edges)
        # Initial-graph paths stay fixed throughout a repair run. In particular,
        # purchased negative answers do not trigger imputation with a new graph.
        for i, u in enumerate(scores.ids):
            lengths = nx.single_source_dijkstra_path_length(weighted, u, weight="weight")
            shortest_path_calls += 1
            for v, distance in lengths.items():
                j = scores.index[v]
                if i >= j or tuple(sorted((u, v))) in edge_set:
                    continue
                value = math.exp(-distance)
                matrix[i, j] = matrix[j, i] = value
                path_reachable_nonedges += 1
                underflow_nonedges += int(value == 0)
        # Never replace a direct edge with a stronger indirect path.
        for (u, v), value in edge_values.items():
            i, j = scores.index[u], scores.index[v]
            matrix[i, j] = matrix[j, i] = value
    transformed = PairScores(scores.ids, matrix)
    if scores.calls != input_calls:
        raise AssertionError("Pure preprocessing changed the input access counter")
    nonedges = n * (n - 1) // 2 - len(edges)
    info = {
        "kind": "heuristic_policy_score_perturbation_stress",
        "mode": mode, "temperature": temperature,
        "is_matcher_recalibration": False, "is_conditional_probability_model": False,
        "uses_gold": False, "changes_graph_topology": False,
        "topology_sha256": topology_hash, "nodes": n, "original_edges": len(edges),
        "preprocessing_pair_score_accesses": read_pairs,
        "preprocessing_access_unit": "distinct unordered visible input pair scores",
        "input_policy_access_counter_unchanged": input_calls,
        "output_policy_access_counter": transformed.calls,
        "shortest_path_source_calls": shortest_path_calls,
        "nonedge_pairs_imputed": nonedges if mode == "edge_only" else 0,
        "nonedges_with_positive_path": path_reachable_nonedges if mode == "edge_only" else None,
        "nonedges_without_positive_path": nonedges - path_reachable_nonedges if mode == "edge_only" else None,
        "path_product_underflow_nonedges": underflow_nonedges,
        "direct_edge_rule": "temperature-transformed direct score overrides every indirect path",
        "nonedge_rule": "maximum product over original positive-score graph paths; otherwise zero" if mode == "edge_only" else "dense matcher pair scores",
        "recomputed_after_queries": False,
        "storage_scope": "dense PairScores retained; no sparse-memory or matcher-saving claim",
        "preprocessing_seconds": time.perf_counter() - start,
    }
    return transformed, info
