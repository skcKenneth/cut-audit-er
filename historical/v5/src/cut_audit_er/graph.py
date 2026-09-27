"""Label-blind graph utilities. Node IDs are strings; gold labels never belong here."""
from __future__ import annotations
from itertools import combinations
from collections.abc import Iterable
import networkx as nx

Edge = tuple[str, str]

def edge_key(u: str, v: str) -> Edge:
    if u == v:
        raise ValueError("Self-pairs are not verification tasks")
    return tuple(sorted((str(u), str(v))))

def validate_graph(g: nx.Graph) -> None:
    if g.is_directed() or g.is_multigraph():
        raise ValueError("Expected a simple undirected graph")
    if nx.number_of_selfloops(g):
        raise ValueError("Self-loops are forbidden")
    if any(not isinstance(n, str) for n in g.nodes):
        raise ValueError("Node IDs must be strings")
    if any(attrs for _, attrs in g.nodes(data=True)):
        raise ValueError("Node attributes are forbidden: keep labels in the oracle/evaluator")
    if any(set(attrs) - {"p"} for _, _, attrs in g.edges(data=True)):
        raise ValueError("Only a visible pair score 'p' may be stored on an edge")
    for _, _, a in g.edges(data=True):
        if not 0 <= float(a.get("p", .5)) <= 1:
            raise ValueError("Pair scores must be in [0,1]")

def closure_size(g: nx.Graph) -> int:
    return sum(len(c) * (len(c) - 1) // 2 for c in nx.connected_components(g))

def removed_copy(g: nx.Graph, edges: Iterable[Edge]) -> nx.Graph:
    h = g.copy()
    h.remove_edges_from(edges)
    return h

def disconnection_gain(g: nx.Graph, edges: Iterable[Edge]) -> int:
    """Number of formerly connected unordered pairs disconnected by deletion."""
    return closure_size(g) - closure_size(removed_copy(g, edges))

def separated_blocks(g: nx.Graph, edges: Iterable[Edge]) -> list[tuple[list[str], list[str]]]:
    h = removed_copy(g, edges)
    after = {v: i for i, c in enumerate(nx.connected_components(h)) for v in c}
    blocks = []
    for c in nx.connected_components(g):
        pieces: dict[int, list[str]] = {}
        for v in sorted(c):
            pieces.setdefault(after[v], []).append(v)
        blocks.extend(combinations(pieces.values(), 2))
    return blocks

def candidate_actions(g: nx.Graph, verified: set[Edge], remaining: int,
                      max_width: int = 2, shortlist: int = 24) -> tuple[list[tuple[Edge, ...]], dict]:
    """All eligible singleton edges plus complementary two-edge cuts.

    For every shortlisted non-bridge e, bridges of G-e identify edges f such
    that {e,f} is a minimal two-edge cut. Shortlisting is score-based, never
    gold-based. No optimality/completeness claim when the shortlist is truncated.
    """
    if max_width not in (1, 2) or shortlist < 2:
        raise ValueError("max_width must be 1 or 2; shortlist must be >=2")
    edges = sorted(edge_key(u, v) for u, v in g.edges if edge_key(u, v) not in verified)
    actions = {(e,) for e in edges} if remaining >= 1 else set()
    truncated = 0
    if max_width == 2 and remaining >= 2:
        original_bridges = {edge_key(u, v) for u, v in nx.bridges(g)}
        for comp in nx.connected_components(g):
            sub = g.subgraph(comp).copy()
            eligible = [edge_key(u, v) for u, v in sub.edges
                        if edge_key(u, v) not in verified and edge_key(u, v) not in original_bridges]
            eligible.sort(key=lambda e: (float(sub.edges[e].get("p", .5)), e))
            truncated += int(len(eligible) > shortlist)
            pool = set(eligible[:shortlist])
            for e in sorted(pool):
                h = removed_copy(sub, (e,))
                for u, v in nx.bridges(h):
                    f = edge_key(u, v)
                    if f in pool and f != e and f not in original_bridges:
                        actions.add(tuple(sorted((e, f))))
    return sorted(actions), {"two_cut_shortlist_truncated_components": truncated,
                             "candidate_actions": len(actions)}
