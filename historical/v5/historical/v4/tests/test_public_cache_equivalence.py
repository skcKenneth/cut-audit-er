"""Cache equivalence on constructed graphs, not a new benchmark experiment."""
from itertools import combinations
import networkx as nx
import numpy as np
import pytest
from cut_audit_er import audit
from cut_audit_er.graph import edge_key
from cut_audit_er.planner_workspace import PlannerWorkspace
from tests.test_mechanism_policy import make_scores, logical


@pytest.mark.parametrize('probability', [0., .5, np.nextafter(.5, 1.), 1.])
def test_cached_and_direct_bc_keep_complete_fixture_decisions(monkeypatch, probability):
    graph = nx.Graph()
    graph.add_nodes_from(['isolate', 'f', 'e', 'd', 'c', 'b', 'a'])
    graph.add_edges_from(reversed(list(combinations('abcdef', 2))))
    scores = make_scores(graph, probability)
    truth = {n: 'one' if n in 'abc' else n for n in graph}
    cached = audit.run_audit(graph, scores, truth, 'edge_betweenness', 9)
    def direct(self, g):
        return {edge_key(*edge): value for edge, value in nx.edge_betweenness_centrality(g).items()}
    monkeypatch.setattr(PlannerWorkspace, 'original_centrality', direct)
    uncached = audit.run_audit(graph, scores, truth, 'edge_betweenness', 9)
    assert logical(cached) == logical(uncached)

