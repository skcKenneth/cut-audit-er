from __future__ import annotations
import time
from copy import deepcopy
from collections.abc import Callable
import numpy as np
import networkx as nx
from .graph import validate_graph, edge_key
from .oracle import BudgetedOracle
from .scores import PairScores
from .metrics import evaluate
from .policies import select_action

def run_audit(g: nx.Graph, scores: PairScores, truth: dict[str,str], method: str,
              budget: int, seed: int=7, noise: float=0.0, fn_weight: float=1.0,
              max_width: int=2, shortlist: int=24,
              max_seconds: float|None=None, match_threshold: float=.5,
              checkpoint_callback: Callable[[dict], None]|None=None,
              completion_model: dict|None=None) -> dict:
    validate_graph(g)
    if set(g.nodes)!=set(scores.ids):
        raise ValueError("Score matrix IDs differ from graph IDs")
    calibrated_model=None
    planner_workspace=None
    if completion_model is not None:
        from .calibrated_planner import CALIBRATED_METHODS
        from .completion_calibration import LogisticCalibrationModel
        calibrated_model=LogisticCalibrationModel.from_dict(completion_model)
        if method not in CALIBRATED_METHODS or calibrated_model.kind!=CALIBRATED_METHODS[method]:
            raise ValueError('Method and completion model mismatch')
        if noise!=0 or fn_weight!=1:
            raise ValueError('Calibration pilot requires noiseless answers and lambda=1')
        from .planner_workspace import PlannerWorkspace
        planner_workspace=PlannerWorkspace()
    g=g.copy();scores=scores.copy()
    oracle=BudgetedOracle(truth,budget,noise,seed)
    rng=np.random.default_rng(seed)
    verified=set(); trace=[]; decisions=[]; policy_state={}
    start=time.perf_counter()
    telemetry_seconds=0.0
    def emit(event):
        nonlocal telemetry_seconds
        if checkpoint_callback is not None:
            t=time.perf_counter()
            # The output observer never receives mutable selector/run state.
            checkpoint_callback(deepcopy(event))
            telemetry_seconds+=time.perf_counter()-t
    trace.append({"spent":0,**evaluate(g,truth,fn_weight)})
    emit({"kind":"initial","checkpoint":trace[-1]})
    stop_reason="budget_exhausted"
    batch=0; selection_total=0.0; batch_timings=[]
    while oracle.remaining:
        if max_seconds is not None and time.perf_counter()-start >= max_seconds:
            stop_reason="time_limit_incomplete";break
        t=time.perf_counter()
        if calibrated_model is None:
            q,info=select_action(g,scores,verified,oracle.remaining,method,rng,fn_weight,max_width,shortlist,
                                match_threshold,oracle.observed,seed,policy_state)
        else:
            from .calibrated_planner import select_calibrated_plan
            q,info=select_calibrated_plan(g,scores,verified,oracle.remaining,method,oracle.observed,
                                         calibrated_model,fn_weight,workspace=planner_workspace)
        select_seconds=time.perf_counter()-t
        selection_total+=select_seconds
        batch_timings.append({"batch":batch+1,"seconds":select_seconds,"action_size":len(q) if q else 0})
        if q is None:
            stop_reason=info.get("reason","no_action");break
        if len(q)>oracle.remaining or len(set(q))!=len(q):
            raise AssertionError("Invalid or over-budget action")
        batch+=1
        for e in q:
            if e in verified or not g.has_edge(*e):
                raise AssertionError("Policy requested a repeated or missing edge")
            answer=oracle.query(*e)
            decision={"batch":batch,"pair":list(e),"observed_match":answer,
                      "spent":oracle.spent,"selection_seconds":select_seconds,
                      "selection_info":info}
            # Persist paid cost before potentially expensive offline evaluation.
            # Exceptions abort the worker; it must not keep querying unlogged.
            emit({"kind":"answer","decision":decision})
            verified.add(e)
            if not answer:
                g.remove_edge(*e)
            decisions.append(decision)
            trace.append({"spent":oracle.spent,**evaluate(g,truth,fn_weight)})
            emit({"kind":"checkpoint","checkpoint":trace[-1]})
    result={"method":method,"requested_budget":budget,"spent":oracle.spent,
            "noise":noise,"seed":seed,"fn_weight":fn_weight,"stop_reason":stop_reason,
            "seconds":time.perf_counter()-start,"score_accesses":scores.calls,
            "selection_seconds":selection_total,"batch_timings":batch_timings,
            "complete":stop_reason!="time_limit_incomplete",
            "trace":trace,"decisions":decisions,
            "initial":trace[0],"final":trace[-1],
            "loss_reduction":trace[0]["loss"]-trace[-1]["loss"]}
    if checkpoint_callback is not None:
        emit({"kind":"terminal","spent":oracle.spent,"complete":result["complete"],
              "stop_reason":stop_reason})
        result["telemetry_seconds"]=telemetry_seconds
        result["seconds"]=time.perf_counter()-start
    return result
