"""Strict dependency-free checks of V5 aggregate tables, without hidden assets.

This validates arithmetic and provenance, not removed pair identities or the
completeness of large-component opportunity sets. It acquires no answers.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re

METHODS=("edge_betweenness","cut_plan_fixed","cut_plan_adaptive","cut_plan_cover_bccap",
         "cut_plan_bound_fixed","cut_plan_cover_fixed","cut_plan_cover_singleton")
NEW=METHODS[3:]; SYNTHETIC=METHODS[2:]
DATASETS=("wdc","dblp_acm","dblp_unused")
STAGES=("generated","capped","validated","filtered","scored","selected")
STATUS=("completed","timeout","failed","incomplete","interrupted","cleanup_failed","not_started",
        "not_started_limit","not_started_gate","not_qualified","not_started_qualification","not_started_resource")
EXCLUSIONS=("budget_insufficient","baseline_edge_policy","generation_missing","cap_excluded","legality_rejected",
            "method_filtered","execution_or_scoring_limit","scored_not_selected","selected")
CONTRAST_TERMS={
 "full_vs_edge_betweenness":(("cut_plan_cover_fixed",1),("edge_betweenness",-1)),
 "full_vs_cut_plan_fixed":(("cut_plan_cover_fixed",1),("cut_plan_fixed",-1)),
 "full_vs_cut_plan_adaptive":(("cut_plan_cover_fixed",1),("cut_plan_adaptive",-1)),
 "full_vs_cut_plan_cover_singleton":(("cut_plan_cover_fixed",1),("cut_plan_cover_singleton",-1)),
 "coverage_with_bc_cap":(("cut_plan_cover_bccap",1),("cut_plan_fixed",-1)),
 "coverage_with_bound_screening":(("cut_plan_cover_fixed",1),("cut_plan_bound_fixed",-1)),
 "screening_old_pool":(("cut_plan_bound_fixed",1),("cut_plan_fixed",-1)),
 "screening_union_pool":(("cut_plan_cover_fixed",1),("cut_plan_cover_bccap",-1)),
 "coverage_by_screening_factorial_interaction":(("cut_plan_cover_fixed",1),("cut_plan_cover_bccap",-1),("cut_plan_bound_fixed",-1),("cut_plan_fixed",1)),
}

def fields(*groups):
    return {k:t for group in groups for k,t in group.items()}
KEY={"run_id":"str","phase":"str","dataset":"str","method":"str","budget":"int"}
SPECS={
 "acquisitions":fields(KEY,{k:"int" for k in ("k","fp","fn","loss","paid","paid_lower_bound","paid_upper_bound",
      "initial_fp","initial_fn","initial_loss","recorded_paid","recorded_prefix_loss","batches","committed_multi_batches",
      "planned_multi_batches","logical_score_accesses")},{k:"str" for k in ("profile","status","reason_code","stop_reason")},
      {k:"float" for k in ("selector_seconds","audit_seconds","worker_wall_seconds","process_start_seconds","result_wait_seconds",
      "payload_receive_seconds","cleanup_seconds")}),
 "reference_endpoints":fields(KEY,{"k":"int","profile":"str","reference":"str","status":"str"},
      {k:"int" for k in ("fp","fn","loss","initial_fp","initial_fn","recorded_prefix_loss")},
      {"reused_acquisition":"bool","independent_observation":"bool"}),
 "events":fields(KEY,{"spent":"int","batch":"int","category":"str","endpoint_complete":"bool"},
      {k:"int" for k in ("fp_removed","fn_added","loss_reduction","fp_after","fn_after","loss_after")}),
 "states":fields(KEY,{"spent":"int","fp":"int","fn":"int","loss":"int","endpoint_complete":"bool"}),
 "batches":fields(KEY,{k:"int" for k in ("batch","spent_before","remaining","action_size","planned_depth","recorded_queries",
      "numeric_scan_score_entry_reads","bound_evaluations","enumerated_subsets","score_limit_unscored","scored_candidate_actions",
      "exhaustive_components","oversized_components","candidate_cap","score_evaluation_cap")},
      {k:"bool" for k in ("batch_fully_recorded","argmax_certified","positive_plan_selected","certified_positive_plan",
      "certified_nonpositive_pool","endpoint_complete","numeric_scan_cache_hit","full_graph_bond_pool_complete",
      "small_component_bond_pool_complete","max_unscored_upper_bound_finite","cap_applied")},
      {k:"str" for k in ("fallback","certificate_status","selected_stage_scope")},
      {k:"float" for k in ("max_unscored_upper_bound","selection_seconds","numeric_preprocessing_seconds","bound_and_order_seconds",
      "enumeration_seconds","union_validation_seconds","cover_pool_seconds","plan_scoring_seconds")}),
 "candidate_depths":fields(KEY,{"batch":"int","stage":"str","depth":"int","count":"int","stage_denominator":"int","endpoint_complete":"bool"}),
 "cache_counts":fields(KEY,{"batch":"int","counter":"str","count":"int","endpoint_complete":"bool"}),
 "contrasts":{"phase":"str","dataset":"str","budget":"int","reference":"str","contrast":"str","method":"str","comparator":"str",
      "scope":"str","status":"str","delta_fp":"int","delta_fn":"int","delta_loss":"int","first_paid_difference":"int","sequence_status":"str"},
 "opportunity_batches":fields(KEY,{"reference":"str","batch":"int","spent_before":"int","remaining":"int","endpoint_complete":"bool"},
      {k:"int" for k in ("exact_components","total_components","covered_fp","total_fp","offline_headroom","witnesses","committed_depth",
      "planned_depth","recorded_queries","beneficial_multi_witnesses","affordable_beneficial_multi_witnesses")},
      {"fp_coverage":"float","zero_fp_denominator":"bool","fallback":"bool","absence_scope":"str"},
      {stage+"_count":"int" for stage in STAGES}),
 "opportunity_exclusions":fields(KEY,{"reference":"str","batch":"int","spent_before":"int","endpoint_complete":"bool",
      "depth":"int","beneficial":"bool","affordable":"bool","first_exclusion":"str","enumeration_scope":"str",
      "witness_count":"int","min_loss_gain":"int","max_loss_gain":"int","max_fp_removed":"int","max_fn_added":"int"}),
 "coverage":{"phase":"str","dataset":"str","reference":"str","nodes":"int","edges":"int","components":"int",
      "exact_components":"int","skipped_components":"int","initial_fp":"int","initial_fn":"int","covered_fp":"int",
      "headroom":"int","status":"str"},
 "failures":fields(KEY,{"status":"str","reason_code":"str","paid_lower_bound":"int","paid_upper_bound":"int"}),
}
SIGNED={"delta_fp","delta_fn","delta_loss","loss_reduction","recorded_prefix_loss","min_loss_gain","max_loss_gain"}
PRIVATE=re.compile(r"[A-Za-z]:[\\/]|\\\\|/Users/|/home/|dblp_acm:|record_id|partition_sha|gold_mapping|evaluator_reference")

def require(ok,message):
    if not ok:raise ValueError(message)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe(root,name):
    require(isinstance(name,str) and name and ":" not in name and "\\" not in name
            and all(p not in ("",".","..") for p in name.split("/")),"Unsafe manifest path")
    value=(Path(root)/name).resolve();require(value.is_relative_to(Path(root).resolve()),"Manifest escapes root");return value

def parse(value,kind,key):
    if value in (None,""):return None
    if kind=="str":
        require(not PRIVATE.search(value),"Private content in public table");return value
    if kind=="bool":
        require(value in ("True","False","true","false"),"Invalid Boolean field");return value.lower()=="true"
    if kind=="int":
        d=Decimal(value);require(d.is_finite() and d==d.to_integral_value(),"Invalid integer field");number=int(d)
    else:number=float(value);require(math.isfinite(number),"Nonfinite numerical field")
    require(key in SIGNED or number>=0,"Negative count/cost field");return number

def table(folder,name):
    require(name in SPECS,"Unknown public table")
    with (Path(folder)/(name+".csv")).open(encoding="utf-8",newline="") as f:
        reader=csv.DictReader(f);require(reader.fieldnames==list(SPECS[name]),"Unexpected public fields: "+name)
        result=[]
        for row in reader:
            require(None not in row and set(row)==set(SPECS[name]),"Malformed CSV row")
            result.append({k:parse(v,SPECS[name][k],k) for k,v in row.items()})
    return result

def _expected():
    values={("synthetic",f"k{k}_{p}",m,b) for k in (1,2,3) for p in ("uniform","ranked") for m in SYNTHETIC for b in (1,2,3,4,6)}
    values|={("natural",d,m,b) for d in DATASETS for m in METHODS for b in (12,24,48)}
    values|={("external","alaska_camera",m,b) for m in METHODS for b in (12,24,48)}
    return values

def validate(folder,*,check_historical=True):
    folder=Path(folder).resolve();manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("schema")=="cut-audit-public-evidence-v5","Wrong evidence schema")
    actual={p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    require(actual==set(manifest["files_sha256"])|{"manifest.json"},"Unlisted/missing evidence files")
    for name,pin in manifest["files_sha256"].items():require(sha(safe(folder,name))==pin,"Evidence hash mismatch: "+name)
    require(set(manifest["files_sha256"])=={n+".csv" for n in SPECS},"Unexpected evidence member")
    if check_historical:
        for name,pin in manifest["historical_files_sha256"].items():
            require(name.startswith("historical/v4/"),"Unapproved historical member")
            require(sha(safe(folder.parent,name))==pin,"Historical public source changed")
    data={name:table(folder,name) for name in SPECS};acq=data["acquisitions"]
    actual_keys=[tuple(r[k] for k in ("phase","dataset","method","budget")) for r in acq]
    require(len(actual_keys)==234 and set(actual_keys)==_expected(),"Prespecified234 acquisition slots differ")
    require(len({r["run_id"] for r in acq})==234,"Duplicate acquisition identity")
    ids={r["run_id"]:r for r in acq}
    for name in ("reference_endpoints","events","states","batches","candidate_depths","cache_counts","opportunity_batches","opportunity_exclusions","failures"):
        for row in data[name]:
            require(row["run_id"] in ids,"Orphan public row")
            require(all(row[k]==ids[row["run_id"]][k] for k in KEY),"Run identity mismatch")
    grouped={name:defaultdict(list) for name in ("events","states","batches","candidate_depths")}
    for name in grouped:
        for row in data[name]:grouped[name][row["run_id"]].append(row)
    for row in acq:
        require(row["run_id"]==f'{row["dataset"]}_{row["method"]}_B{row["budget"]}',"Noncanonical public run identity")
        require(row["status"] in STATUS,"Unknown acquisition status")
        require(type(row["paid_lower_bound"]) is int and row["paid_lower_bound"]<=row["paid_upper_bound"]<=row["budget"],"Paid bounds invalid")
        complete=row["status"]=="completed"
        require(all(row[k] is not None for k in ("fp","fn","loss","paid")) if complete else
                all(row[k] is None for k in ("fp","fn","loss","paid")),"Missing endpoint imputed or completed endpoint incomplete")
        if complete:require(row["fp"]+row["fn"]==row["loss"] and row["paid"]==row["paid_lower_bound"]==row["paid_upper_bound"],"Endpoint accounting mismatch")
        es=sorted(grouped["events"][row["run_id"]],key=lambda e:e["spent"])
        ss=sorted(grouped["states"][row["run_id"]],key=lambda e:e["spent"])
        bs=sorted(grouped["batches"][row["run_id"]],key=lambda e:e["batch"])
        require([e["spent"] for e in es]==list(range(1,len(es)+1)),"Paid event gap")
        if es or ss:
            require([x["spent"] for x in ss]==list(range(len(es)+1)),"Metric states differ from paid events")
            require(all(e["endpoint_complete"]==complete for e in es+ss+bs),"Prefix mislabelled complete")
            require(all(r["fp"]+r["fn"]==r["loss"] for r in ss),"Metric state arithmetic mismatch")
        if complete:
            require(len(es)==row["paid"] and ss,"Complete endpoint lacks event/state evidence")
            require(all(ss[-1][k]==row[k] for k in ("fp","fn","loss")),"Final metric differs")
        if ss and row["initial_fp"] is not None:
            require(all(ss[0][k]==row["initial_"+k] for k in ("fp","fn","loss")),"Initial metric differs")
        if row["recorded_paid"] is not None:require(row["recorded_paid"]==len(es),"Recorded prefix count differs")
        require(len(es)<=row["paid_lower_bound"],"Recorded answers exceed confirmed cost")
        for previous,current,event in zip(ss,ss[1:],es):
            require(current["fp"]+current["fn"]==current["loss"],"State FP+FN mismatch")
            require(event["fp_removed"]==previous["fp"]-current["fp"] and event["fn_added"]==current["fn"]-previous["fn"],"Event conservation mismatch")
            require(event["loss_reduction"]==event["fp_removed"]-event["fn_added"],"Event reduction mismatch")
            require(all(event[k+"_after"]==current[k] for k in ("fp","fn","loss")),"Event endpoint mismatch")
            require(event["category"] in ("paid_positive","negative_no_split","negative_split"),"Invalid event class")
            if event["category"]!="negative_split":require(event["fp_removed"]==event["fn_added"]==0,"Nonsplit changes metric")
        require([b["batch"] for b in bs]==list(range(1,len(bs)+1)),"Batch gap")
        if row["batches"] is not None:
            require(row["batches"]==len(bs) and row["committed_multi_batches"]==sum(b["action_size"]>1 for b in bs)
                    and row["planned_multi_batches"]==sum(b["planned_depth"]>1 for b in bs),"Batch-use endpoint totals differ")
        for b in bs:
            ee=[e for e in es if e["batch"]==b["batch"]]
            require(len(ee)==b["recorded_queries"]<=b["action_size"]<=b["remaining"],"Batch paid cost mismatch")
            require(b["spent_before"]==ee[0]["spent"]-1 and b["remaining"]==row["budget"]-b["spent_before"],"Batch boundary mismatch")
            require(b["batch_fully_recorded"]==(b["recorded_queries"]==b["action_size"]),"Partial batch flag mismatch")
            require(not b["certified_positive_plan"] or (b["positive_plan_selected"] and b["argmax_certified"] and not b["fallback"]),"Fallback incorrectly certified")
            require(not b["certified_nonpositive_pool"] or (b["argmax_certified"] and not b["positive_plan_selected"]),"Nonpositive certificate mismatch")
            if b["scored_candidate_actions"] is not None:require(b["scored_candidate_actions"]<=64,"Score cap exceeded")
            denominators=[]
            for stage in STAGES:
                dd=[r for r in grouped["candidate_depths"][row["run_id"]] if r["batch"]==b["batch"] and r["stage"]==stage]
                require(len(dd)==4 and {r["depth"] for r in dd}=={1,2,3,4},"Stage depth grid incomplete")
                require(len({r["stage_denominator"] for r in dd})==1 and sum(r["count"] for r in dd)==dd[0]["stage_denominator"],"Stage denominator inconsistent")
                denominators.append(dd[0]["stage_denominator"])
            require(all(x>=y for x,y in zip(denominators,denominators[1:])) and denominators[-1]<=1,"Candidate stage counts contradict subset semantics")
    refs=data["reference_endpoints"]
    require(len(refs)==300 and {(r["run_id"],r["reference"]) for r in refs}=={(r["run_id"],h) for r in acq if r["phase"]=="synthetic" for h in ("H0","H9")},"Paired reference grid differs")
    for row in refs:
        require(row["status"]==ids[row["run_id"]]["status"] and row["reused_acquisition"] and row["independent_observation"] is False,"Paired evaluation treated as independent")
        require(row["fp"]+row["fn"]==row["loss"] if row["status"]=="completed" else all(row[k] is None for k in ("fp","fn","loss")),"Reference missing/metric mismatch")
        if row["reference"]=="H0" and row["status"]=="completed":
            require(all(row[k]==ids[row["run_id"]][k] for k in ("fp","fn","loss")),"H0 differs from acquired reference")
    contrast_keys=[(r["phase"],r["dataset"],r["budget"],r["reference"],r["contrast"]) for r in data["contrasts"]]
    expected_contrasts={("synthetic",f"k{k}_{p}",b,h,c) for k in (1,2,3) for p in ("uniform","ranked") for b in (1,2,3,4,6)
        for h in ("H0","H9") for c in CONTRAST_TERMS}
    expected_contrasts|={(phase,d,b,None,c) for phase,ds in (("natural",DATASETS),("external",("alaska_camera",))) for d in ds for b in (12,24,48) for c in CONTRAST_TERMS}
    require(len(contrast_keys)==len(expected_contrasts) and set(contrast_keys)==expected_contrasts,"Prespecified contrast grid incomplete")
    metric_index={(r["phase"],r["dataset"],r["budget"],None,r["method"]):r for r in acq if r["phase"]!="synthetic"}
    metric_index.update({("synthetic",r["dataset"],r["budget"],r["reference"],r["method"]):r for r in refs})
    if check_historical:
        with (folder.parent/"historical/v4/evidence/synthetic_endpoints.csv").open(encoding="utf-8",newline="") as f:
            for r in csv.DictReader(f):
                metric_index["synthetic",f'k{r["k"]}_{r["profile"]}',int(r["budget"]),r["reference"],r["method"]]={
                    "status":r["status"],**{k:int(r[k]) if r[k] else None for k in ("fp","fn","loss")}}
    for row in data["contrasts"]:
        require(row["delta_fp"]+row["delta_fn"]==row["delta_loss"] if row["status"]=="complete" else all(row[k] is None for k in ("delta_fp","delta_fn","delta_loss")),"Contrast missing/metric mismatch")
        if check_historical or row["phase"]!="synthetic":
            terms=[(metric_index[(row["phase"],row["dataset"],row["budget"],row["reference"],m)],coef) for m,coef in CONTRAST_TERMS[row["contrast"]]]
            valid=all(r["status"]=="completed" for r,c in terms)
            require((row["status"]=="complete")==valid,"Contrast availability differs from endpoints")
            if valid:require(all(row["delta_"+k]==sum(c*r[k] for r,c in terms) for k in ("fp","fn","loss")),"Contrast value differs from its endpoints")
    oppkeys=set();exclusion_totals=defaultdict(lambda:[0,0,0])
    for row in data["opportunity_exclusions"]:
        key=(row["run_id"],row["reference"],row["batch"]);exclusion_totals[key][0]+=row["witness_count"]
        if row["beneficial"] and row["depth"]>1:
            exclusion_totals[key][1]+=row["witness_count"]
            if row["affordable"]:exclusion_totals[key][2]+=row["witness_count"]
    for row in data["opportunity_batches"]:
        key=(row["run_id"],row["reference"],row["batch"]);require(key not in oppkeys,"Duplicate opportunity batch");oppkeys.add(key)
        require(any(b["batch"]==row["batch"] for b in grouped["batches"][row["run_id"]]),"Opportunity lacks recorded batch")
        require(exclusion_totals[key]==[row["witnesses"],row["beneficial_multi_witnesses"],row["affordable_beneficial_multi_witnesses"]],"Opportunity witness totals differ")
        require(row["exact_components"]<=row["total_components"] and row["covered_fp"]<=row["total_fp"],"Invalid offline coverage")
        require(row["zero_fp_denominator"]==(row["total_fp"]==0),"Zero-denominator flag differs")
        require(row["fp_coverage"] is None if row["total_fp"]==0 else math.isclose(row["fp_coverage"],row["covered_fp"]/row["total_fp"],abs_tol=1e-12),"Zero-denominator/coverage error")
        require(row["absence_scope"]==("complete_small_graph" if row["exact_components"]==row["total_components"] else "large_component_absence_unknown"),"Large absence overstated")
        dd=grouped["candidate_depths"][row["run_id"]]
        for stage in STAGES:
            count=sum(r["count"] for r in dd if r["batch"]==row["batch"] and r["stage"]==stage)
            require(count==row[stage+"_count"],"Offline/visible stage count differs")
    for row in data["opportunity_exclusions"]:
        require(row["first_exclusion"] in EXCLUSIONS and row["enumeration_scope"] in ("complete_small","explicit_large_witness") and row["witness_count"]>0,"Invalid witness aggregation")
    require(set(exclusion_totals)<=oppkeys,"Orphan witness aggregation")
    for row in data["cache_counts"]:require(re.fullmatch(r"[a-z_]+",row["counter"] or "") is not None,"Invalid physical counter name")
    for row in data["coverage"]:
        if row["components"] is not None:
            require(row["exact_components"]+row["skipped_components"]==row["components"] and row["covered_fp"]<=row["initial_fp"],"Structure coverage inconsistent")
    require({r["run_id"] for r in data["failures"]}=={r["run_id"] for r in acq if r["status"]!="completed"},"Missing slot list differs")
    counts={"acquisitions":len(acq),"synthetic_acquisitions":150,"natural_acquisitions":63,"external_slots":21,
            "synthetic_completed":sum(r["status"]=="completed" for r in acq if r["phase"]=="synthetic"),
            "natural_completed":sum(r["status"]=="completed" for r in acq if r["phase"]=="natural"),
            "external_completed":sum(r["status"]=="completed" for r in acq if r["phase"]=="external"),
            "reference_endpoints":300,"reference_completed":sum(r["status"]=="completed" for r in refs),
            "paid_lower_bound":sum(r["paid_lower_bound"] for r in acq),"paid_upper_bound":sum(r["paid_upper_bound"] for r in acq),
            "events":len(data["events"]),"batches":len(data["batches"])}
    require(manifest["counts"]==counts,"Manifest counts differ from tables")
    return {"status":"PASS","counts":counts,"manifest_sha256":sha(folder/"manifest.json"),
            "scope":"Aggregate hashes/arithmetic/grid; cannot reidentify removed pairs or prove large-component absence"}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--evidence",type=Path,default=Path(__file__).resolve().parents[1]/"evidence")
    print(json.dumps(validate(p.parse_args().evidence),indent=2))
