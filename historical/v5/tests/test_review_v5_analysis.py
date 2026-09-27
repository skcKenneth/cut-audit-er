"""Saved synthetic fixtures validate accounting, replay and missing boundaries."""
from copy import deepcopy
import pytest
from cut_audit_er.audit import run_audit
from scripts.review_v4.synthetic import visible_recipe, load_visible, reference_recipe
from scripts.review_v5 import analysis as a, study as s


@pytest.mark.parametrize("method", s.NATURAL_METHODS)
@pytest.mark.parametrize("k,budget", [(1,3), (2,4), (3,6)])
def test_complete_fixed_answer_replay_and_paired_evaluation(method,k,budget):
    g,scores=load_visible(visible_recipe(k,"uniform"))
    run=run_audit(g,scores,reference_recipe("H0"),method,budget,match_threshold=.6)
    replay=a.visible_replay(g,scores,run,complete=True)
    result=a.evaluate_replay(replay,reference_recipe("H0"),run["trace"])
    paired=a.evaluate_replay(replay,reference_recipe("H9"))
    assert result["final"]["loss"]==run["final"]["loss"]
    assert len(result["events"])==len(paired["events"])==run["spent"]
    assert replay["new_oracle_answers"]==0
    for batch in replay["batches"]:
        assert set(a.stages(batch|{"method":method}))=={"generated","capped","validated","filtered","scored","selected"}
        assert all(set(e)=={"pair","answer"} for e in batch["observed_answers_before"])


def test_partial_batch_retained_as_prefix_only():
    g,scores=load_visible(visible_recipe(2,"uniform"))
    run=run_audit(g,scores,reference_recipe("H0"),"cut_plan_cover_fixed",4,match_threshold=.6)
    run["decisions"]=run["decisions"][:1]; run["trace"]=run["trace"][:2]
    replay=a.visible_replay(g,scores,run,complete=False)
    assert not replay["complete"] and replay["stop_reason"]=="recorded_prefix_only"
    assert a.evaluate_replay(replay,reference_recipe("H0"),run["trace"])["final"]["spent"]==1


def test_metric_and_paid_answer_mismatch_rejected():
    g,scores=load_visible(visible_recipe(1,"uniform"))
    run=run_audit(g,scores,reference_recipe("H0"),"cut_plan_fixed",1,match_threshold=.6)
    replay=a.visible_replay(g,scores,run,complete=True)
    bad=deepcopy(run["trace"]); bad[-1]["fp"]+=1
    with pytest.raises(ValueError,match="metric replay"):a.evaluate_replay(replay,reference_recipe("H0"),bad)
    wrong={u:"one" for u in g}
    with pytest.raises(ValueError,match="fixed paid answer"):a.evaluate_replay(replay,wrong)


def test_isolates_terminal_is_not_paid_batch():
    g,scores=load_visible(visible_recipe(1,"uniform"));g.remove_edges_from(list(g.edges))
    run=run_audit(g,scores,reference_recipe("H0"),"cut_plan_cover_fixed",1,match_threshold=.6)
    replay=a.visible_replay(g,scores,run,complete=True)
    assert replay["batches"]==[] and replay["events"]==[]
    assert replay["terminal_decision"]["is_paid_batch"] is False


def endpoint(method,loss,*,status="completed",phase="natural",dataset="wdc"):
    return {"run_id":method,"phase":phase,"dataset":dataset,"method":method,"budget":12,
            "status":status,"fp":loss,"fn":0,"loss":loss}


def test_gate_rejects_synthetic_ties_partial_and_allows_only_complete_new_natural():
    full=endpoint("cut_plan_cover_fixed",9);raw=endpoint("cut_plan_fixed",10)
    assert a.external_gate([full,raw])["eligible"]
    assert not a.external_gate([{**full,"loss":10},raw])["eligible"]
    assert not a.external_gate([{**full,"status":"timeout"},raw])["eligible"]
    assert not a.external_gate([{**full,"phase":"synthetic"},{**raw,"phase":"synthetic"}])["eligible"]
    with pytest.raises(ValueError):a.external_gate([full,full,raw])
    with pytest.raises(ValueError):a.external_gate([{**full,"loss":float("nan")},raw])


def test_contrasts_full_factorial_missing_and_sequences():
    rows=[endpoint(method,n) for method,n in zip(s.NATURAL_METHODS,(20,15,12,13,11,8,14))]
    values=a.build_contrasts(rows,{})
    assert len(values)==9
    interaction=next(r for r in values if r["contrast"]=="coverage_by_screening_factorial_interaction")
    assert interaction["delta_loss"]==8-13-11+15
    raw=next(r for r in values if r["contrast"]=="full_vs_cut_plan_fixed")
    assert raw["delta_loss"]==-7 and raw["sequence_status"]=="unavailable"
    rows[1]["status"]="timeout";rows[1]["loss"]=None
    values=a.build_contrasts(rows,{})
    assert next(r for r in values if r["contrast"]=="coverage_by_screening_factorial_interaction")["delta_loss"] is None


def test_same_endpoint_different_pair_sequence_not_equated():
    first={"complete":True,"events":[{"pair":["a","b"],"answer":False}]}
    second={"complete":True,"events":[{"pair":["a","c"],"answer":False}]}
    assert a.first_paid_difference(first,second)["first_paid_difference"]==1
    assert a.first_paid_difference(first,first)["sequence_status"]=="identical_complete_sequences"
    assert a.first_paid_difference({**first,"complete":False},first)["sequence_status"]=="identical_recorded_prefix_only"


def test_bc_cap_validation_differs_from_ub_identity():
    x=[["a","b"]];y=[["b","c"]]
    batch={"planned_action":x,"selection_info":{"cap_applied":True},"candidate_trace":{
        "union_generated":[x,y],"capped_order":[x],"validated_order":[x,y],"eligible_order":[x,y],"scored_order":[x]}}
    assert a.stages(batch)["filtered"]==[x]
    batch["selection_info"]["cap_applied"]=False;batch["candidate_trace"]["capped_order"]=[x,y]
    assert a.stages(batch)["filtered"]==[x,y]


def test_saved_journal_analysis_and_offline_opportunity_driver(tmp_path,monkeypatch):
    import csv
    from cut_audit_er.telemetry import AuditJournal,recover_journal
    from scripts.review_v5 import opportunities
    g,scores=load_visible(visible_recipe(2,"uniform"));truth=reference_recipe("H0")
    declared=[{"id":f"wdc_{method}_B4","dataset":"wdc","method":method,"budget":4,"status":"not_started"}
              for method in ("cut_plan_fixed","cut_plan_cover_fixed","cut_plan_cover_singleton")]
    root=tmp_path;folder=root/s.SESSION;snapshot=root/"snapshot"
    s.write(folder/"freeze.json",{"test_fixture":True})
    s.write(snapshot/"inputs/natural/wdc/evaluator_reference.json",{"reference":truth})
    def audit(arguments,seconds,journal,identity):
        if arguments["method"]=="cut_plan_cover_singleton":return {"status":"timeout"}
        with AuditJournal(journal,identity) as writer:run=run_audit(**arguments,checkpoint_callback=writer)
        return {"status":"completed","run":run,"checkpoint_telemetry":recover_journal(journal,identity),
                "worker_timing":{"process_start_seconds":0.,"cleanup_seconds":0.}}
    s.execute_grid(folder/"natural/study","natural",declared,{"wdc":(g,scores,truth)},s.digest(folder/"freeze.json"),audit_fn=audit)
    monkeypatch.setattr(s,"checked_freeze",lambda _: ({},snapshot))
    monkeypatch.setattr(s,"slots",lambda _:declared)
    monkeypatch.setattr(s,"load_phase_assets",lambda *args,**kwargs:{"wdc":(g,scores,None)})
    out=folder/"natural/analysis"
    result=a.analyze_phase("natural",out,root=root)
    assert result["counts"]["acquisitions_completed"]==2
    s.check_hashes(out,result["files_sha256"])
    with (out/"endpoints.csv").open() as f:rows=list(csv.DictReader(f))
    assert rows[-1]["loss"]=="" and rows[-1]["paid_upper_bound"]=="4"
    diagnosis=opportunities.analyze_saved("natural",out,s.digest(out/"manifest.json"),folder/"natural/opportunities",root)
    assert diagnosis["status"]=="passed" and diagnosis["new_oracle_answers"]==0
    assert diagnosis["batch_reference_states"]>0


def test_fallback_is_not_a_certified_selected_candidate():
    batch={"planned_action":[["a","b"]],"selection_info":{"fallback":"BC","surrogate_argmax_certified":True},
           "candidate_trace":{"union_generated":[],"capped_order":[],"validated_order":[],"eligible_order":[],"scored_order":[]}}
    assert a.stages(batch)["selected"]==[]
