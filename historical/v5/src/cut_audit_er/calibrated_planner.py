"""Fixed depth-4 pilot: replace completion probability only; never read truth."""
from math import prod
import time
from .bounded_planner import build_plan_pool, completion_score, depth_counts
from .planner_workspace import PlannerWorkspace
from .completion_calibration import LogisticCalibrationModel

CALIBRATED_METHODS = {
    'cut_plan_edge_calibrated':'edge_negative',
    'cut_plan_completion_calibrated':'plan_depth',
    'cut_plan_completion_c0':'plan_c0',
}

def paid_relations(nodes, observations, plan):
    """Noiseless paid positive closure; negative relations are not transitive."""
    parent = {node:node for node in nodes}
    def find(node):
        while parent[node]!=node:
            parent[node]=parent[parent[node]]
            node=parent[node]
        return node
    for (u,v),answer in observations.items():
        if type(answer) is not bool:
            raise ValueError('Paid answers must be bool')
        if answer:
            a,b=sorted((find(u),find(v)))
            parent[b]=a
    negatives=set()
    for (u,v),answer in observations.items():
        if not answer:
            a,b=sorted((find(u),find(v)))
            if a==b:
                raise ValueError('Inconsistent noiseless paid history')
            negatives.add((a,b))
    relations=[]
    for u,v in plan:
        a,b=sorted((find(u),find(v)))
        relations.append('known_match' if a==b else 'known_nonmatch' if (a,b) in negatives else 'unresolved')
    forced=0 if 'known_match' in relations else 1 if 'unresolved' not in relations else None
    description={'history_consistent':True, 'logical_assumption':'consistent_noiseless_paid_answers',
                 'logical_all_negative_probability':forced}
    return relations,description

def plan_probability(model, raw_q, plan, probabilities, relations, description):
    if model.kind=='edge_negative':
        return prod(model.predict_edge(1-probabilities[e],paid_relation=relation)
                    for e,relation in zip(plan,relations))
    return model.predict_plan(raw_q,len(plan),paid_constraints=description)

def select_calibrated_plan(g,scores,verified,remaining,method,observations,model,fn_weight=1.,
                           *,workspace=None):
    if method not in CALIBRATED_METHODS or model.kind!=CALIBRATED_METHODS[method]:
        raise ValueError('Method and calibration model kind mismatch')
    if fn_weight!=1.:
        raise ValueError('Pilot fixes FN weight at one')
    if remaining<1:
        return None,{'reason':'no_budget_or_candidates'}
    workspace = workspace if workspace is not None else PlannerWorkspace()
    cache_before = dict(workspace.counts)
    plans,parts,probabilities,weighted,info=build_plan_pool(
        g,scores,verified,remaining,allow_long=True,workspace=workspace)
    ranked=[]
    started=time.perf_counter()
    for plan in plans:
        _,utility,raw_q=completion_score(plan,parts[plan],scores,probabilities,observations,fn_weight)
        relations,description=paid_relations(g,observations,plan)
        calibrated_q=plan_probability(model,raw_q,plan,probabilities,relations,description)
        ranked.append((calibrated_q*utility/len(plan),plan,utility,raw_q,calibrated_q))
    info.update(plan_scoring_seconds=time.perf_counter()-started, calibration_kind=model.kind,
                scored_candidate_actions=len(plans),scored_candidate_depth_counts=depth_counts(plans),
                selected_candidate_depth_counts=depth_counts(()),
                graph_and_candidate_probabilities='original_frozen_matcher',endpoint_aware=True,
                replan_after_each_answer=False)
    if ranked:
        value,plan,utility,raw_q,cal_q=min(ranked,key=lambda row:(-row[0],len(row[1]),row[1]))
        info.update(selected_proxy_score=value,completion_utility_proxy=utility,
                    factorized_all_negative_probability=raw_q,calibrated_completion_probability=cal_q)
        if value>0:
            ordered=tuple(sorted(plan,key=lambda e:(-probabilities[e],e)))
            info.update(planned_edges=[list(e) for e in ordered],planned_depth=len(ordered),
                        selected_candidate_depth_counts=depth_counts((plan,)),
                        score_denominator='full_plan_pair_count_in_both_fixed_and_adaptive')
            return ordered,info
    if not probabilities:
        return None,{**info,'reason':'no_budget_or_candidates'}
    bc=workspace.original_centrality(g)
    edge=min(probabilities,key=lambda e:(-bc[e]*(1-probabilities[e]),e))
    return (edge,),{**info,'fallback':'error_weighted_edge_betweenness',
                   'fallback_trigger':'empty_validated_pool' if not plans else 'nonpositive_proxy',
                   'selected_candidate_depth_counts':depth_counts(((edge,),)),
                   'topology_cache':workspace.delta(cache_before),
                   'reason':'centrality_continuation_after_nonpositive_or_empty_pool',
                   'planned_depth':1,'planned_edges':[list(edge)]}
