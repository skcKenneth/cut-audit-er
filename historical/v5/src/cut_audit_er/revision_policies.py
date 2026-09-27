"""Bounded September 2026 revisions. Selectors never receive evaluation gold."""
from __future__ import annotations


REVISION_METHODS = ("risk_centrality_fallback", "risk_seed_pool",
                    "cut_plan_depth2", "cut_plan_fixed", "cut_plan_adaptive")


def select_revision(g, scores, verified, remaining, method, rng, fn_weight=1.0,
                    max_width=2, shortlist=24, observations=None, policy_seed=7, state=None):
    from .policies import select_action
    if method in ("risk_seed_pool", "cut_plan_depth2", "cut_plan_fixed", "cut_plan_adaptive",
                  "cut_plan_fixed_singleton"):
        from .bounded_planner import select_bounded_plan
        return select_bounded_plan(g, scores, verified, remaining, method, observations,
                                   state if state is not None else {}, fn_weight)
    if method != "risk_centrality_fallback":
        raise ValueError(f"Unknown revision policy {method}")
    action, info = select_action(g, scores, verified, remaining, "cut_risk", rng,
                                fn_weight, max_width, shortlist,
                                observations=observations, policy_seed=policy_seed)
    if action is not None or info.get("reason") != "no_positive_proxy_utility":
        return action, {**info, "revision": "original_risk_then_centrality"}
    fallback, _ = select_action(g, scores, verified, remaining, "edge_betweenness", rng,
                               fn_weight, observations=observations, policy_seed=policy_seed,
                               policy_state=state)
    return fallback, {**info, "fallback": "error_weighted_edge_betweenness",
                      "fallback_trigger": info["reason"],
                      "reason": "centrality_continuation_after_nonpositive_proxy",
                      "revision": "original_risk_then_centrality"}
