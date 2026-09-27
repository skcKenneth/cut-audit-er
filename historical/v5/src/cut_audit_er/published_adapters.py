"""Independent, explicitly adapted selectors derived from primary ER papers.

No author implementation is vendored here. TransClean's native pipeline also
re-trains a matcher, prunes unverified edges, and recovers deleted edges. This
module implements only a frozen, pair-verification adaptation of its selection
idea; it is not a reproduction of the published pipeline.
"""
from __future__ import annotations

from itertools import combinations

import networkx as nx
import numpy as np

from .graph import Edge, edge_key
from .scores import PairScores


def select_transclean_audit(
    g: nx.Graph,
    scores: PairScores,
    verified: set[Edge],
    remaining: int,
    *,
    match_threshold: float = 0.5,
    max_negative_paths: int = 10,
    path_seed: int = 42,
) -> tuple[tuple[Edge, ...] | None, dict]:
    """Select one component's cut/path batch under the audit-only contract.

    Source: de Meer Pardo et al., IEEE Access 13 (2025),
    doi:10.1109/ACCESS.2025.3632400, IV-B2 / Algorithm 1. Components
    are ranked by negatively predicted *nonedges* in their transitive closure.
    A minimum-cardinality cut and shortest paths for at most ten of those
    nonedges supply candidate edges. Purchased labels never enter scores.

    Adaptations fixed before experiments: sorted node/edge insertion and ties;
    seeded sampling over sorted negative nonedges; sorted minimum-cut edges
    followed by sorted path edges; skip already verified edges; cap each batch
    to remaining individual pair labels; recompute after each component batch.
    Native training, automatic pruning, size-based deletion, recovery, and
    exhaustive labeling stages are excluded. A consistent graph may abstain.
    The default decision threshold is 0.5; callers should pass their frozen
    matcher's decision threshold when it differs.
    """
    if not 0 <= match_threshold <= 1:
        raise ValueError("match_threshold must lie in [0,1]")
    if max_negative_paths < 1:
        raise ValueError("max_negative_paths must be positive")
    info = {
        "baseline_status": "paper_derived_frozen_audit_adapter",
        "published_method_reproduction": False,
        "match_threshold": match_threshold,
        "max_negative_paths": max_negative_paths,
        "path_seed": path_seed,
    }
    if remaining < 1:
        return None, {**info, "reason": "no_budget"}
    known = {edge_key(*e) for e in verified}
    eligible = {edge_key(*e) for e in g.edges} - known
    if not eligible:
        return None, {**info, "reason": "no_unverified_edges"}

    ranked = []
    for component in nx.connected_components(g):
        nodes = tuple(sorted(component))
        if len(nodes) < 3:
            continue  # A one-edge component has no implied nonedge.
        negative = [
            (u, v) for u, v in combinations(nodes, 2)
            if not g.has_edge(u, v) and scores.p(u, v) < match_threshold
        ]
        if negative:
            ranked.append((nodes, negative))
    ranked.sort(key=lambda item: (-len(item[1]), item[0]))

    for nodes, negative in ranked:
        # Canonical insertion makes NetworkX's equal-cut/path choices stable
        # for the pinned runtime and independent of input graph insertion.
        h = nx.Graph()
        h.add_nodes_from(nodes)
        h.add_edges_from(sorted(edge_key(*e) for e in g.subgraph(nodes).edges))
        cut = sorted(edge_key(*e) for e in nx.minimum_edge_cut(h))
        if len(negative) > max_negative_paths:
            indices = np.random.RandomState(path_seed).choice(
                len(negative), size=max_negative_paths, replace=False
            )
            selected_negative = [negative[int(i)] for i in sorted(indices)]
        else:
            selected_negative = negative
        path_edges: set[Edge] = set()
        for u, v in selected_negative:
            path = nx.shortest_path(h, source=u, target=v)
            path_edges.update(edge_key(a, b) for a, b in zip(path, path[1:]))
        candidates = list(dict.fromkeys(cut + sorted(path_edges)))
        candidates = [e for e in candidates if e in eligible]
        if not candidates:
            continue
        selected = tuple(candidates[:remaining])
        return selected, {
            **info,
            "ranked_inconsistent_components": len(ranked),
            "selected_component_size": len(nodes),
            "negative_implied_pairs": len(negative),
            "sampled_negative_implied_pairs": len(selected_negative),
            "minimum_cut_size": len(cut),
            "eligible_cut_path_pairs": len(candidates),
            "batch_truncated_by_budget": len(candidates) > remaining,
        }
    return None, {
        **info,
        "ranked_inconsistent_components": len(ranked),
        "reason": "no_unverified_inconsistent_cut_path_pairs",
    }
