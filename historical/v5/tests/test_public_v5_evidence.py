"""Portable aggregate checks on constructed tables; no research acquisitions."""
from copy import deepcopy
import csv
import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
schema_path=ROOT/"scripts/validate_evidence.py"
spec=importlib.util.spec_from_file_location("public_v5_validation_fixture",schema_path)
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)


def blank(name,**values):return {**{k:None for k in v.SPECS[name]},**values}


def fixture_tables():
    tables={n:[] for n in v.SPECS}
    for phase,dataset,method,budget in sorted(v._expected()):
        row=blank("acquisitions",run_id=f"{dataset}_{method}_B{budget}",phase=phase,dataset=dataset,method=method,budget=budget,
                  status="not_started_gate" if phase=="external" else "not_started_limit",paid_lower_bound=0,paid_upper_bound=0,
                  reason_code="fixture_never_started")
        if phase=="synthetic":row.update(k=int(dataset[1]),profile=dataset.split("_",1)[1])
        tables["acquisitions"].append(row)
        if phase=="synthetic":
            for ref in ("H0","H9"):
                tables["reference_endpoints"].append(blank("reference_endpoints",**{k:row[k] for k in v.KEY},
                    k=row["k"],profile=row["profile"],reference=ref,status=row["status"],reused_acquisition=True,independent_observation=False))
    groups={(r["phase"],r["dataset"],r["budget"],None) for r in tables["acquisitions"] if r["phase"]!="synthetic"}
    groups|={("synthetic",r["dataset"],r["budget"],r["reference"]) for r in tables["reference_endpoints"]}
    for phase,dataset,budget,ref in sorted(groups):
        for name,terms in v.CONTRAST_TERMS.items():
            tables["contrasts"].append(blank("contrasts",phase=phase,dataset=dataset,budget=budget,reference=ref,contrast=name,
                method=terms[0][0],comparator=terms[1][0],scope="fixture",status="missing_endpoint",sequence_status="unavailable"))
    return tables


def save(folder,tables):
    folder.mkdir(parents=True,exist_ok=True)
    tables["failures"]=[{k:r[k] for k in v.SPECS["failures"]} for r in tables["acquisitions"] if r["status"]!="completed"]
    for name,rows in tables.items():
        with (folder/(name+".csv")).open("w",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=list(v.SPECS[name]));w.writeheader();w.writerows(rows)
    acq=tables["acquisitions"];refs=tables["reference_endpoints"]
    counts={"acquisitions":len(acq),"synthetic_acquisitions":150,"natural_acquisitions":63,"external_slots":21,
        **{p+"_completed":sum(r["status"]=="completed" for r in acq if r["phase"]==p) for p in ("synthetic","natural","external")},
        "reference_endpoints":len(refs),"reference_completed":sum(r["status"]=="completed" for r in refs),
        "paid_lower_bound":sum(r["paid_lower_bound"] for r in acq),"paid_upper_bound":sum(r["paid_upper_bound"] for r in acq),
        "events":len(tables["events"]),"batches":len(tables["batches"])}
    manifest={"schema":"cut-audit-public-evidence-v5","counts":counts,"historical_files_sha256":{},
              "files_sha256":{n+".csv":v.sha(folder/(n+".csv")) for n in v.SPECS}}
    (folder/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")


def repaired_fixture():
    tables=fixture_tables();row=next(r for r in tables["acquisitions"] if r["run_id"]=="wdc_edge_betweenness_B12")
    row.update(status="completed",fp=0,fn=0,loss=0,paid=1,paid_lower_bound=1,paid_upper_bound=1,
               initial_fp=1,initial_fn=0,initial_loss=1,recorded_paid=1,recorded_prefix_loss=0,batches=1,committed_multi_batches=0,
               planned_multi_batches=0,logical_score_accesses=1,selector_seconds=.01,audit_seconds=.02,worker_wall_seconds=.03)
    key={k:row[k] for k in v.KEY}
    tables["states"]=[blank("states",**key,spent=0,fp=1,fn=0,loss=1,endpoint_complete=True),
                      blank("states",**key,spent=1,fp=0,fn=0,loss=0,endpoint_complete=True)]
    tables["events"]=[blank("events",**key,spent=1,batch=1,category="negative_split",endpoint_complete=True,
                      fp_removed=1,fn_added=0,loss_reduction=1,fp_after=0,fn_after=0,loss_after=0)]
    tables["batches"]=[blank("batches",**key,batch=1,spent_before=0,remaining=12,action_size=1,planned_depth=1,recorded_queries=1,
                       batch_fully_recorded=True,endpoint_complete=True,positive_plan_selected=False,certified_positive_plan=False,
                       certified_nonpositive_pool=False,selected_stage_scope="actual_BC_edge_action",selection_seconds=.01)]
    for stage in v.STAGES:
        for depth in (1,2,3,4):tables["candidate_depths"].append(blank("candidate_depths",**key,batch=1,stage=stage,depth=depth,
            count=int(depth==1),stage_denominator=1,endpoint_complete=True))
    return tables


def test_complete_reserved_grid_and_missing_not_imputed(tmp_path):
    save(tmp_path,fixture_tables());r=v.validate(tmp_path,check_historical=False)
    assert r["counts"]["acquisitions"]==234 and r["counts"]["reference_endpoints"]==300
    assert r["counts"]["paid_upper_bound"]==0


def test_independent_event_and_batch_arithmetic(tmp_path):
    data=repaired_fixture();save(tmp_path,data);v.validate(tmp_path,check_historical=False)
    data["events"][0]["fp_removed"]=2;save(tmp_path,data)
    with pytest.raises(ValueError,match="conservation"):v.validate(tmp_path,check_historical=False)


@pytest.mark.parametrize("mutation",["missing_imputed","duplicate_slot","independent_reference","depth_denominator","fallback_certified","unknown_large"])
def test_semantic_errors_rejected_even_with_fresh_hashes(tmp_path,mutation):
    data=repaired_fixture()
    if mutation=="missing_imputed":data["acquisitions"][0]["loss"]=0
    elif mutation=="duplicate_slot":data["acquisitions"][-1]=deepcopy(data["acquisitions"][0])
    elif mutation=="independent_reference":data["reference_endpoints"][0]["independent_observation"]=True
    elif mutation=="depth_denominator":data["candidate_depths"][0]["stage_denominator"]=2
    elif mutation=="fallback_certified":data["batches"][0].update(fallback="BC",certified_positive_plan=True)
    else:
        key={k:data["batches"][0][k] for k in v.KEY}
        data["opportunity_batches"]=[blank("opportunity_batches",**key,reference="natural",batch=1,spent_before=0,remaining=12,
            endpoint_complete=True,exact_components=1,total_components=2,covered_fp=0,total_fp=0,offline_headroom=0,witnesses=0,
            committed_depth=1,planned_depth=1,recorded_queries=1,beneficial_multi_witnesses=0,affordable_beneficial_multi_witnesses=0,
            zero_fp_denominator=True,fallback=False,absence_scope="complete_small_graph",**{s+"_count":0 for s in v.STAGES})]
    save(tmp_path,data)
    with pytest.raises(ValueError):v.validate(tmp_path,check_historical=False)


def test_hash_tamper_rejected(tmp_path):
    save(tmp_path,fixture_tables());path=tmp_path/"events.csv";path.write_text(path.read_text()+"\n")
    with pytest.raises(ValueError,match="hash mismatch"):v.validate(tmp_path,check_historical=False)


def test_private_field_and_path_rejected(tmp_path):
    save(tmp_path,fixture_tables());path=tmp_path/"events.csv";path.write_text(path.read_text().replace("spent,","pair_id,spent,"))
    with pytest.raises(ValueError,match="Unexpected public fields"):v.table(tmp_path,"events")
    with pytest.raises(ValueError,match="Private content"):v.parse("C:/Users/private/file.json","str","reason_code")


def test_zero_is_distinct_from_missing_and_nonfinite_rejected():
    assert v.parse("0","int","fp")==0 and v.parse("","int","fp") is None
    for bad in ("nan","inf","-1"):
        with pytest.raises(ValueError):v.parse(bad,"float","worker_wall_seconds")


def test_full_contrast_grid_cannot_drop_missing_comparison(tmp_path):
    data=fixture_tables();data["contrasts"].pop();save(tmp_path,data)
    with pytest.raises(ValueError,match="contrast grid"):v.validate(tmp_path,check_historical=False)
