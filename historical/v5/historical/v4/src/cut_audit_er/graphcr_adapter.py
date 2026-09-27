"""Paper-derived GraphCR bootstrap-ext selector under a pair-audit contract.

This is an adapter, NOT native GraphCR. It retains committee vote variance,
cluster-size representation, and cosine diversity (Christen et al., JDIQ 2025,
Section 4.2). It omits automatic weak-link pruning, source-specific features,
feature-label propagation, and classifier-driven partition repair. The base
matcher stays frozen; only an auxiliary query committee learns purchased labels.
No author source code was copied. See research/literature/GRAPHCR_ADAPTER_SPEC.md.
"""
from __future__ import annotations

from collections import Counter
import numpy as np
import networkx as nx
from sklearn.ensemble import RandomForestClassifier

from .graph import Edge, edge_key, validate_graph
from .scores import PairScores

WARMUP_LABELS = 4
QUERY_BATCH = 2
COMMITTEE_SIZE = 20
TREES_PER_MODEL = 10


def initial_graph_features(g: nx.Graph, scores: PairScores,
                           observations: dict[Edge, bool]):
    """Reconstruct initial edges from the verified-deletion history, never gold.

    The audit engine only removes purchased negatives. Thus adding those edges
    back recovers the initial graph and keeps feature vectors fixed throughout
    repair, including the vectors used to train on already deleted negatives.
    """
    validate_graph(g)
    if set(g) != set(scores.ids):
        raise ValueError("Graph and score IDs differ")
    initial = g.copy()
    for e, answer in observations.items():
        if len(e) != 2 or edge_key(*e) != e or not set(e) <= set(g):
            raise ValueError("Invalid observed pair")
        if not isinstance(answer, (bool, np.bool_)):
            raise ValueError("Observed answers must be boolean")
        if answer and not initial.has_edge(*e):
            raise ValueError("A purchased positive edge cannot have been removed")
        initial.add_edge(*e, p=scores.p(*e))
    edges = sorted(edge_key(*e) for e in initial.edges)
    features: dict[Edge, np.ndarray] = {}
    sizes: dict[Edge, int] = {}
    component_sizes = []
    for component in sorted(nx.connected_components(initial), key=lambda c: tuple(sorted(c))):
        # NetworkX subgraph views may iterate a hashed node set. Rebuild in
        # canonical order so floating centralities and exact-vector groups do
        # not depend on process hash seeds or graph insertion order.
        h = nx.Graph()
        h.add_nodes_from(sorted(component))
        h.add_edges_from((u, v, dict(initial.edges[u, v]))
                         for u, v in edges if u in component and v in component)
        n = len(h)
        component_sizes.append(n)
        if n < 2:
            continue
        # Unweighted structural metrics: score remains its own visible feature.
        pr = nx.pagerank(h, weight=None)
        close = nx.closeness_centrality(h)
        between = nx.betweenness_centrality(h, weight=None)
        clustering = nx.clustering(h, weight=None)
        eb = {edge_key(*e): value for e, value in
              nx.edge_betweenness_centrality(h, weight=None).items()}
        bridges = {edge_key(*e) for e in nx.bridges(h)}
        density = nx.density(h)
        for u, v in h.edges:
            e = edge_key(u, v)
            features[e] = np.array([
                scores.p(u, v), abs(pr[u] - pr[v]),
                abs(close[u] - close[v]), abs(between[u] - between[v]),
                abs(clustering[u] - clustering[v]), float(e in bridges),
                eb[e], density,
            ], dtype=float)
            sizes[e] = n
    return edges, features, sizes, component_sizes


def select_graphcr_audit(g: nx.Graph, scores: PairScores,
                        observations: dict[Edge, bool], remaining: int,
                        seed: int = 7) -> tuple[tuple[Edge, ...] | None, dict]:
    """Query at most two edges; every answer including warmup is charged.

    Inputs contain purchased answers only. Do not pass any unpurchased label.
    A single-class history uses matcher uncertainty until both classes exist.
    """
    eligible = sorted(edge_key(*e) for e in g.edges if edge_key(*e) not in observations)
    info = {"adapter": "graphcr_bootstrap_audit", "native_reproduction": False,
            "warmup_labels": WARMUP_LABELS, "query_batch": QUERY_BATCH,
            "committee_size": COMMITTEE_SIZE, "trees_per_model": TREES_PER_MODEL,
            "purchased_training_labels": len(observations), "features_frozen": True,
            "graph_feature_order": "canonical_nodes_edges_v1"}
    if remaining < 1 or not eligible:
        return None, {**info, "reason": "no_budget_or_candidates"}
    _, features, sizes, component_sizes = initial_graph_features(g, scores, observations)
    rng = np.random.default_rng(np.random.SeedSequence([seed, len(observations)]))
    batch_size = min(QUERY_BATCH, remaining, len(eligible))
    # Representatives are preferred, but equivalent feature vectors never
    # receive free labels: duplicate pairs remain separately eligible and paid.
    groups: dict[tuple[float, ...], list[Edge]] = {}
    for edge in eligible:
        groups.setdefault(tuple(features[edge]), []).append(edge)
    representatives = [members[0] for members in groups.values()]
    if len(observations) < WARMUP_LABELS:
        shuffled = list(representatives)
        rng.shuffle(shuffled)
        remainder = [e for e in eligible if e not in set(shuffled)]
        rng.shuffle(remainder)
        q = tuple((shuffled + remainder)[:min(batch_size, WARMUP_LABELS-len(observations))])
        return q, {**info, "stage": "paid_warmup", "unique_candidate_vectors": len(groups)}
    observed_edges = sorted(observations)
    x_train = np.vstack([features[e] for e in observed_edges])
    y_train = np.asarray([int(observations[e]) for e in observed_edges])
    if len(np.unique(y_train)) < 2:
        q = tuple(sorted(eligible, key=lambda e: (abs(features[e][0]-.5), e))[:batch_size])
        return q, {**info, "stage": "class_degenerate_uncertainty",
                   "observed_classes": np.unique(y_train).tolist()}
    x = np.vstack([features[e] for e in eligible])
    votes = []
    for _ in range(COMMITTEE_SIZE):
        indices = rng.integers(0, len(x_train), size=len(x_train))
        model = RandomForestClassifier(
            n_estimators=TREES_PER_MODEL, random_state=int(rng.integers(0, 2**31-1)),
            n_jobs=1,
        )
        model.fit(x_train[indices], y_train[indices])
        votes.append(model.predict(x))
    fraction = np.mean(votes, axis=0)
    uncertainty = fraction * (1-fraction)
    population = Counter(component_sizes)
    training = Counter(sizes[e] for e in observed_edges)
    representation = np.asarray([
        population[sizes[e]]/len(component_sizes)-training[sizes[e]]/len(observed_edges)
        for e in eligible
    ])
    denom = np.linalg.norm(x, axis=1)[:, None]*np.linalg.norm(x_train, axis=1)[None, :]
    cosine = np.divide(x @ x_train.T, denom, out=np.zeros((len(x), len(x_train))), where=denom > 0)
    diversity = (1-np.clip(cosine, -1, 1)).mean(axis=1)
    informativeness = (uncertainty + representation + diversity)/3
    order = sorted(range(len(eligible)), key=lambda i: (-informativeness[i], eligible[i]))
    chosen, seen_vectors = [], set()
    for i in order:
        vector = tuple(features[eligible[i]])
        if vector not in seen_vectors:
            chosen.append(i)
            seen_vectors.add(vector)
        if len(chosen) == batch_size:
            break
    if len(chosen) < batch_size:
        chosen.extend(i for i in order if i not in chosen)
        chosen = chosen[:batch_size]
    q = tuple(eligible[i] for i in chosen)
    return q, {**info, "stage": "bootstrap_ext", "observed_classes": [0, 1],
               "unique_candidate_vectors": len(groups),
               "selected_terms": [{"pair": list(eligible[i]),
                                   "vote_variance": float(uncertainty[i]),
                                   "size_representation": float(representation[i]),
                                   "cosine_diversity": float(diversity[i]),
                                   "informativeness": float(informativeness[i])} for i in chosen]}
