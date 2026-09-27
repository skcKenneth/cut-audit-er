"""Label-blind policies. 'mincut_proxy' is NOT a reproduction of TransClean."""
from __future__ import annotations
from itertools import product
import numpy as np
import networkx as nx
from .graph import Edge, candidate_actions, edge_key, disconnection_gain, removed_copy
from .scores import PairScores, proxy_loss_reduction
from .published_adapters import select_transclean_audit
from .graphcr_adapter import select_graphcr_audit
from .revision_policies import REVISION_METHODS, select_revision
from .planner_workspace import PlannerWorkspace

DEFAULT_METHODS = ("random", "uncertainty", "error_probability", "edge_betweenness",
           "bridge_impact", "mincut_proxy", "cut_gain", "cut_risk", "transclean_audit",
           "cut_risk_observed", "graphcr_audit") + REVISION_METHODS
OPT_IN_METHODS = ("cut_plan_fixed_singleton",)
METHODS = DEFAULT_METHODS + OPT_IN_METHODS

def action_score(g: nx.Graph, q: tuple[Edge, ...], scores: PairScores,
                 fn_weight: float, account_for_fn: bool,
                 observed: dict[Edge, bool] | None = None) -> float:
    """Enumerate all <=4 deletion outcomes under a factorized proxy distribution.

    This is a heuristic: pair labels are dependent under entity equivalence;
    the cross-pair score is not conditioned on the queried outcomes. Do NOT call
    this exact expected utility, a risk guarantee, or an optimal policy.
    """
    ps = [scores.p(*e) for e in q]
    value = 0.0
    for flags in product((False, True), repeat=len(q)):
        deletions = tuple(e for e, delete in zip(q, flags) if delete)
        if not deletions:
            continue
        weight = float(np.prod([1-p if d else p for p, d in zip(ps, flags)]))
        utility = (proxy_loss_reduction(g, deletions, scores, fn_weight) if account_for_fn
                   else disconnection_gain(g, deletions))
        if account_for_fn and observed is not None:
            # Exact endpoint values under the *observed* outcome replace their
            # unconditional marginals. Unqueried pairs still use the heuristic.
            outcome = dict(observed)
            outcome.update({e:not delete for e,delete in zip(q,flags)})
            after = removed_copy(g,deletions)
            for e, answer in outcome.items():
                if (e[0] in g and e[1] in g and nx.has_path(g,*e)
                        and not nx.has_path(after,*e)):
                    utility += (1+fn_weight)*(scores.p(*e)-int(answer))
        value += weight * utility
    return value / len(q)

def select_action(g: nx.Graph, scores: PairScores, verified: set[Edge], remaining: int,
                  method: str, rng: np.random.Generator, fn_weight: float = 1.0,
                  max_width: int = 2, shortlist: int = 24,
                  match_threshold: float = .5,
                  observations: dict[Edge, bool] | None = None,
                  policy_seed: int = 7,
                  policy_state: dict | None = None) -> tuple[tuple[Edge, ...] | None, dict]:
    if method not in METHODS:
        raise ValueError(f"Unknown method {method}")
    eligible = sorted(edge_key(u,v) for u,v in g.edges if edge_key(u,v) not in verified)
    if remaining < 1 or not eligible:
        return None, {"reason":"no_budget_or_candidates"}
    if method in REVISION_METHODS + OPT_IN_METHODS:
        return select_revision(g, scores, verified, remaining, method, rng,
                               fn_weight, max_width, shortlist, observations, policy_seed, policy_state)
    if method == "transclean_audit":
        return select_transclean_audit(g, scores, verified, remaining, match_threshold=match_threshold)
    if method == "graphcr_audit":
        return select_graphcr_audit(g, scores, observations or {}, remaining, seed=policy_seed)
    if method == "random":
        return (eligible[int(rng.integers(len(eligible)))],), {}
    probs = {e:scores.p(*e) for e in eligible}
    if method == "uncertainty":
        return (min(eligible, key=lambda e:(abs(probs[e]-.5),e)),), {}
    if method == "error_probability":
        return (min(eligible, key=lambda e:(probs[e],e)),), {}
    if method == "edge_betweenness":
        state = policy_state if policy_state is not None else {}
        if '_topology_workspace' not in state:
            state['_topology_workspace'] = PlannerWorkspace()
        workspace = state['_topology_workspace']
        cache_before = dict(workspace.counts)
        bc = workspace.original_centrality(g)
        e = min(eligible, key=lambda e:(-bc[e]*(1-probs[e]),e))
        return (e,), {'topology_cache': workspace.delta(cache_before)}
    if method == "bridge_impact":
        # Only bridges can change connectivity; local components give the same
        # exact gain without copying all unrelated components for every edge.
        component_graphs = [g.subgraph(c).copy() for c in nx.connected_components(g)]
        local = {v:h for h in component_graphs for v in h}
        bridges = {edge_key(*e) for e in nx.bridges(g)}
        values = {e:(1-probs[e])*disconnection_gain(local[e[0]],(e,))
                  if e in bridges else 0.0 for e in eligible}
        e = min(eligible, key=lambda e:(-values[e],probs[e],e))
        return (e,), {}
    if method == "mincut_proxy":
        actions = []
        for comp in nx.connected_components(g):
            if len(comp) < 2:
                continue
            h = nx.Graph()
            h.add_nodes_from(comp)
            for u,v in g.subgraph(comp).edges:
                e = edge_key(u,v)
                # Ineligible/observed-positive edges cannot be a requested cut.
                h.add_edge(u,v,weight=1e12 if e in verified else 1.0)
            _, (a,b) = nx.stoer_wagner(h, weight="weight")
            b = set(b)
            q = tuple(sorted(edge_key(u,v) for u in a for v in g.neighbors(u) if v in b))
            if not q or len(q)>remaining or any(e in verified for e in q):
                continue
            disagreement = 0.0
            for component in (comp,):
                ids = sorted(component)
                disagreement += sum(scores.p(u,v)<.5 for i,u in enumerate(ids) for v in ids[i+1:])
            actions.append((disagreement/len(q),q))
        if actions:
            return min(actions,key=lambda x:(-x[0],x[1]))[1], {"proxy_not_published_baseline":True}
        return (min(eligible,key=lambda e:(probs[e],e)),), {"fallback":"error_probability"}
    actions, info = candidate_actions(g,verified,remaining,max_width,shortlist)
    component_graphs = [g.subgraph(c).copy() for c in nx.connected_components(g)]
    local = {v:h for h in component_graphs for v in h}
    bridges = {edge_key(*e) for e in nx.bridges(g)}
    risk_method = method in ("cut_risk", "cut_risk_observed")
    outcome_observations = (observations or {}) if method == "cut_risk_observed" else None
    # A nonbridge singleton never separates any pair, under either answer.
    # Its exact proxy score is zero: avoid repeated graph copying/scoring.
    ranked = [(0.0 if len(q)==1 and q[0] not in bridges else
               action_score(local[q[0][0]],q,scores,fn_weight,risk_method,outcome_observations),q)
              for q in actions]
    value,q = min(ranked,key=lambda z:(-z[0],len(z[1]),z[1]))
    info["selected_proxy_score"] = value
    if value <= 0:
        if risk_method:
            return None, {**info,"reason":"no_positive_proxy_utility"}
        return (min(eligible,key=lambda e:(probs[e],e)),), {**info,"fallback":"error_probability"}
    return q,info
