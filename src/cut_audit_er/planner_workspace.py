"""Bounded, run-local caches of observable topology; no scores or labels.

Canonical insertion order is identical to the original planner. Whole-graph
betweenness is still computed by the same NetworkX routine. Component-local
bridge and bond results are reused only for identical node/edge/visible-p
keys; eligible/protected edges, mincuts and plan ranks are never cached here.
"""
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

import networkx as nx

from .graph import edge_key, removed_copy


def _make_graph(nodes, edges):
    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_edges_from((u, v, {'p': p}) for u, v, p in edges)
    return graph


@dataclass
class _Component:
    graph: nx.Graph
    seed_bridges: OrderedDict = field(default_factory=OrderedDict)
    bonds: OrderedDict = field(default_factory=OrderedDict)


class PlannerWorkspace:
    """Keep only current components and capped local memo tables per run.

    This cache does not substitute local-normalized centrality for the original
    global calculation. Graph mutations, including p changes, invalidate keys.
    Returning internal graphs is private to the planner, which only copies them
    before deletion/capacity mutation. No state is shared across audit runs.
    """
    SEED_CACHE_CAP = 64
    BOND_CACHE_CAP = 128

    def __init__(self):
        self.counts = Counter()
        self._key = None
        self._graph = None
        self._edges = ()
        self._centrality = None
        self._bridges = None
        self._components = None
        self._entries = {}
        self._by_graph_id = {}
        self._original_key = None
        self._original_centrality = None

    def original_centrality(self, graph):
        """Memoize unweighted BC on the actual graph, preserving float order.

        NetworkX iterates both nodes and their adjacency dictionaries. A sorted
        edge set is therefore not a sufficient key for bit-identical results.
        Isolated nodes also matter to global normalization. Scores, eligibility
        and paid answers are deliberately absent: those are recomputed by each
        selector even after a positive answer leaves this topology unchanged.
        """
        key = tuple((node, tuple(graph.adj[node])) for node in graph)
        if key != self._original_key:
            self.counts['original_centrality_misses'] += 1
            self._original_key = key
            self._original_centrality = {
                edge_key(*edge): value for edge, value in
                nx.edge_betweenness_centrality(graph).items()}
        else:
            self.counts['original_centrality_hits'] += 1
        return self._original_centrality

    def canonical(self, graph):
        nodes = tuple(sorted(graph))
        edges = tuple((u, v, float(graph.edges[u, v].get('p', .5)))
                      for u, v in sorted(edge_key(*e) for e in graph.edges))
        key = (nodes, tuple((u, v, p.hex()) for u, v, p in edges))
        if key == self._key:
            self.counts['canonical_hits'] += 1
            return self._graph
        self.counts['canonical_misses'] += 1
        self._key = key
        self._edges = edges
        self._graph = _make_graph(nodes, edges)
        self._centrality = self._bridges = self._components = None
        return self._graph

    def centrality(self):
        if self._centrality is None:
            self.counts['centrality_misses'] += 1
            self._centrality = {edge_key(*e): value for e, value in
                                nx.edge_betweenness_centrality(self._graph).items()}
        else:
            self.counts['centrality_hits'] += 1
        return self._centrality

    def components(self):
        if self._components is not None:
            self.counts['component_partition_hits'] += 1
            return self._components
        self.counts['component_partition_misses'] += 1
        nodes = sorted(tuple(sorted(c)) for c in nx.connected_components(self._graph))
        owners = {node: i for i, component in enumerate(nodes) for node in component}
        buckets = [[] for _ in nodes]
        # One global edge pass, retaining exactly the old per-component order.
        for edge in self._edges:
            buckets[owners[edge[0]]].append(edge)
        entries, components = {}, []
        for component_nodes, edges in zip(nodes, buckets):
            key = (component_nodes, tuple((u, v, p.hex()) for u, v, p in edges))
            if key in self._entries:
                self.counts['component_graph_hits'] += 1
                entry = self._entries[key]
            else:
                self.counts['component_graph_misses'] += 1
                entry = _Component(_make_graph(component_nodes, edges))
            entries[key] = entry
            components.append(entry.graph)
        # Drop superseded components instead of accumulating past graph states.
        self._entries = entries
        self._by_graph_id = {id(entry.graph): entry for entry in entries.values()}
        self._components = components
        return components

    def bridges(self):
        if self._bridges is None:
            self.counts['bridges_misses'] += 1
            self._bridges = {edge_key(*e) for e in nx.bridges(self._graph)}
        else:
            self.counts['bridges_hits'] += 1
        return self._bridges

    def _memo(self, component, name, key, compute, cap):
        cache = getattr(self._by_graph_id[id(component)], name)
        if key in cache:
            self.counts[name + '_hits'] += 1
            cache.move_to_end(key)
            return cache[key]
        self.counts[name + '_misses'] += 1
        value = compute()
        cache[key] = value
        if len(cache) > cap:
            cache.popitem(last=False)
            self.counts[name + '_evictions'] += 1
        return value

    def bridges_without(self, component, edge):
        return self._memo(component, 'seed_bridges', edge,
                          lambda: tuple(nx.bridges(removed_copy(component, (edge,)))),
                          self.SEED_CACHE_CAP)

    def bond(self, component, plan, compute):
        return self._memo(component, 'bonds', tuple(plan),
                          lambda: compute(component, plan), self.BOND_CACHE_CAP)

    def delta(self, before):
        return {key: self.counts[key] - before.get(key, 0)
                for key in sorted(self.counts) if self.counts[key] != before.get(key, 0)}
