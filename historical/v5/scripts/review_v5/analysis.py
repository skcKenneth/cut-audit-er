"""V5 saved-answer replay, paired offline accounting and strict external gate.

Never acquires an answer, changes a selector, or substitutes a saved prefix for
an independent requested-budget endpoint. Opportunity diagnosis is separate.
"""
from __future__ import annotations
from collections import Counter
import argparse
import csv
import itertools
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from scripts.review_v5 import study as s


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if not k.endswith("_seconds")
                and k not in ("seconds", "topology_cache", "batch_timings")}
    if isinstance(value, (list, tuple)): return [semantic(v) for v in value]
    return value


def partition(graph):
    import networkx as nx
    return sorted(sorted(c) for c in nx.connected_components(graph))


def pair_metrics(parts, truth):
    """Direct independent closure counts, including cross-component true pairs."""
    choose = lambda n: n * (n - 1) // 2
    predicted = sum(choose(len(c)) for c in parts)
    tp = sum(sum(choose(n) for n in Counter(truth[u] for u in c).values()) for c in parts)
    gold = sum(choose(n) for n in Counter(truth.values()).values())
    return {"fp": predicted - tp, "fn": gold - tp, "loss": predicted + gold - 2 * tp}


def old_candidate_trace(graph, scores, observed, remaining, method, policy_state):
    """Visible-only supplementary trace with isolated calls/cache, including adaptive remainder."""
    import networkx as nx
    from cut_audit_er.bounded_planner import build_plan_pool, completion_score
    ds = scores.copy()
    if method == "edge_betweenness":
        values = [(tuple(sorted(e)), bc * (1 - ds.p(*e))) for e, bc in nx.edge_betweenness_centrality(graph).items()
                  if tuple(sorted(e)) not in observed]
        return {"pool_scope": "actual_BC_ranking", "bc_ranked": [{"pair": e, "value": v} for e, v in sorted(values, key=lambda r: (-r[1], r[0]))],
                "diagnostic_score_accesses": ds.calls}
    previous = tuple(tuple(e) for e in policy_state.get("pending_plan", ())) if method == "cut_plan_adaptive" else ()
    invalidated = any(observed.get(e) is True for e in previous)
    pending = () if invalidated else tuple(e for e in previous if e not in observed)
    plans, parts, probs, weights, info = build_plan_pool(graph, ds, set(observed), remaining,
        pending_plan=pending, diagnostic_raw=True)
    raw = [tuple(tuple(e) for e in q) for q in info["raw_plan_edges"]]
    ranked = sorted(raw, key=lambda q: (-sum(weights[e] for e in q) / len(q), len(q), q))
    capped = ranked[:64]
    if info["pending_remainder_retained"] and tuple(sorted(pending)) not in capped:
        capped = [tuple(sorted(pending))] + capped[:63]
    values = []
    for plan in plans:
        value, utility, success = completion_score(plan, parts[plan], ds, probs, observed, 1.)
        values.append({"plan": plan, "proxy": value, "utility": utility, "success_product": success})
    values.sort(key=lambda r: (-r["proxy"], len(r["plan"]), r["plan"]))
    return semantic({"legacy_generated": raw, "union_generated": raw, "prerank_order": ranked,
                     "capped_order": capped, "validated_order": plans, "eligible_order": plans,
                     "scored_order": plans, "score_records": values, "pending_plan": pending,
                     "pending_remainder_retained": info["pending_remainder_retained"],
                     "pool_scope": "reconstructed_actual_legacy_pool", "diagnostic_score_accesses": ds.calls})


def visible_replay(graph, scores, run, *, complete):
    """Fixed-answer replay: no truth argument, including the old adaptive state."""
    import numpy as np
    from cut_audit_er.policies import select_action
    g = graph.copy(); reads = scores.copy(); observed = {}; state = {}; rng = np.random.default_rng(7)
    budget, method = run["requested_budget"], run["method"]
    states = [{"spent": 0, "partition": partition(g)}]; events = []; batches = []; diagnostic_calls = 0
    decisions = run.get("decisions", [])
    groups = [(b, list(v)) for b, v in itertools.groupby(decisions, key=lambda d: d["batch"])]
    for index, (batch, records) in enumerate(groups, 1):
        s.require(batch == index and records, "Saved batch sequence gap")
        remaining = budget - len(observed)
        before = {"partition_before": partition(g), "edges_before": [list(sorted(e)) for e in g.edges],
                  "observed_answers_before": [{"pair": list(e), "answer": a} for e, a in sorted(observed.items())]}
        candidate = None
        if method not in s.NEW_METHODS:
            candidate = old_candidate_trace(g, scores, observed, remaining, method, state)
            diagnostic_calls += candidate.get("diagnostic_score_accesses", 0)
        action, info = select_action(g, reads, set(observed), remaining, method, rng, 1., 2, 24, .6, observed, 7, state)
        recorded = tuple(tuple(d["pair"]) for d in records)
        s.require(action is not None and (recorded == action if complete else recorded == action[:len(recorded)]), "Paid action differs from frozen replay")
        s.require(len(recorded) == len(action) or index == len(groups), "A partial batch cannot precede another batch")
        s.require(all(semantic(d["selection_info"]) == semantic(info) for d in records), "Batch semantic metadata differs")
        if method in s.NEW_METHODS:
            s.require(isinstance(info.get("candidate_trace"), dict), "New method lacks full visible candidate trace")
            candidate = semantic(info["candidate_trace"])
        batches.append({"batch": batch, "spent_before": len(observed), "remaining": remaining,
                        "action": semantic(action), "planned_action": semantic(info.get("planned_edges", action)),
                        "selection_info": semantic(info), "candidate_trace": candidate,
                        "recorded_queries": len(records), "batch_fully_recorded": len(records) == len(action),
                        "logical_accesses_after_selection": reads.calls, **before})
        for decision in records:
            edge = tuple(decision["pair"]); answer = decision["observed_match"]
            s.require(type(answer) is bool and edge not in observed and g.has_edge(*edge)
                      and decision["spent"] == len(observed) + 1, "Invalid saved paid event")
            count_before = len(states[-1]["partition"])
            observed[edge] = answer
            if not answer: g.remove_edge(*edge)
            parts = partition(g)
            category = "paid_positive" if answer else "negative_split" if len(parts) > count_before else "negative_no_split"
            events.append({"spent": len(observed), "batch": batch, "pair": list(edge), "answer": answer, "category": category})
            states.append({"spent": len(observed), "partition": parts})
    stop = "recorded_prefix_only"; terminal = None
    if complete:
        stop = "budget_exhausted"
        if len(observed) < budget:
            candidate = old_candidate_trace(g, scores, observed, budget - len(observed), method, state) if method not in s.NEW_METHODS else None
            action, info = select_action(g, reads, set(observed), budget - len(observed), method, rng, 1., 2, 24, .6, observed, 7, state)
            s.require(action is None, "Replay requests an unrecorded answer")
            stop = info.get("reason", "no_action")
            terminal = {"spent_before": len(observed), "remaining": budget-len(observed), "action": None,
                        "selection_info": semantic(info), "candidate_trace": semantic(info.get("candidate_trace", candidate)),
                        "partition_before": partition(g), "edges_before": [list(sorted(e)) for e in g.edges],
                        "observed_answers_before": [{"pair": list(e), "answer": a} for e, a in sorted(observed.items())],
                        "is_paid_batch": False}
        s.require(stop == run["stop_reason"] and len(observed) == run["spent"]
                  and reads.calls == run["score_accesses"], "Replay cost/stop differs")
    return {"batches": batches, "terminal_decision": terminal, "events": events, "states": states, "complete": complete, "stop_reason": stop,
            "logical_score_accesses": reads.calls, "diagnostic_score_accesses": diagnostic_calls, "new_oracle_answers": 0}


def evaluate_replay(replay, truth, expected_trace=None):
    s.require(set(truth) == {u for c in replay["states"][0]["partition"] for u in c}, "Evaluator reference membership differs")
    states = [{"spent": r["spent"], **pair_metrics(r["partition"], truth)} for r in replay["states"]]
    if expected_trace is not None:
        s.require(len(expected_trace) <= len(states), "Metric trace longer than recorded paid states")
        for a, b in zip(expected_trace, states):
            s.require(all(a[k] == b[k] for k in ("spent", "fp", "fn", "loss")), "Offline metric replay differs")
        if replay["complete"]: s.require(len(expected_trace) == len(states), "Complete metric trace truncated")
    events = []
    for event, before, after in zip(replay["events"], states, states[1:]):
        u, v = event["pair"]
        s.require(event["answer"] == (truth[u] == truth[v]), "Offline reference disagrees with fixed paid answer")
        fp, fn = before["fp"] - after["fp"], after["fn"] - before["fn"]
        s.require(fp >= 0 and fn >= 0 and fp - fn == before["loss"] - after["loss"], "Event conservation failed")
        if event["category"] != "negative_split": s.require(fp == fn == 0, "Nonsplit altered closure metrics")
        events.append({**event, "fp_removed": fp, "fn_added": fn, "loss_reduction": fp - fn,
                       "fp_after": after["fp"], "fn_after": after["fn"], "loss_after": after["loss"]})
    return {"states": states, "events": events, "initial": states[0], "final": states[-1]}


def external_gate(endpoints):
    """Natural contemporary matched controls only; strictly lower completed loss."""
    index = {(r["dataset"], r["method"], r["budget"]): r for r in endpoints if r.get("phase") == "natural"}
    s.require(len(index) == sum(r.get("phase") == "natural" for r in endpoints), "Duplicate natural gate endpoint")
    witnesses, missing = [], []
    for dataset in s.DATASETS:
        for budget in (12, 24, 48):
            full = index.get((dataset, "cut_plan_cover_fixed", budget))
            raw = index.get((dataset, "cut_plan_fixed", budget))
            if not full or not raw or full["status"] != "completed" or raw["status"] != "completed":
                missing.append({"dataset": dataset, "budget": budget}); continue
            s.require(all(type(r.get("loss")) in (int, float) and math.isfinite(r["loss"]) and r["loss"] >= 0 for r in (full, raw)), "Complete gate endpoint lacks finite loss")
            if full["loss"] < raw["loss"]:
                witnesses.append({"dataset": dataset, "budget": budget, "full_loss": full["loss"],
                                  "raw_loss": raw["loss"], "full_minus_raw": full["loss"] - raw["loss"]})
    return {"eligible": bool(witnesses), "status": "gate_passed" if witnesses else "gate_not_passed",
            "rule": s.fixed_config()["external_gate"], "witnesses": witnesses, "missing_comparisons": missing,
            "external_data_run_authorized_by_this_file": False, "meaning": "Development gate only; not superiority, qualification or submission evidence"}


def csv_write(path, rows, defaults=("run_id", "status")):
    fields = list(dict.fromkeys(k for r in rows for k in r)) or list(defaults)
    with Path(path).open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list, tuple)) else v for k, v in row.items()})


def stages(batch):
    """Actual method order. An identity stage does not invent candidate loss."""
    trace = batch.get("candidate_trace") or {}; info = batch["selection_info"]
    raw = trace.get("union_generated", trace.get("legacy_generated", []))
    capped = trace.get("capped_order", raw)
    valid = trace.get("validated_order", capped)
    if info.get("cap_applied") is True or batch.get("method") in ("cut_plan_fixed", "cut_plan_adaptive"):
        wanted = {tuple(tuple(e) for e in p) for p in capped}
        valid = [p for p in valid if tuple(tuple(e) for e in p) in wanted]
    filtered = trace.get("eligible_order", valid)
    if info.get("cap_applied") is True:
        wanted = {tuple(tuple(e) for e in p) for p in valid}
        filtered = [p for p in filtered if tuple(tuple(e) for e in p) in wanted]
    selected = [batch["planned_action"]] if batch.get("planned_action") and not info.get("fallback") else []
    if batch.get("method") == "edge_betweenness":
        candidates = [[row["pair"]] for row in trace.get("bc_ranked", [])]
        return {**{k:candidates for k in ("generated","capped","validated","filtered","scored")},
                "selected":[batch["action"]]}
    return {"generated": raw, "capped": capped, "validated": valid, "filtered": filtered,
            "scored": trace.get("scored_order", []), "selected": selected}


def first_paid_difference(left, right):
    if left is None or right is None: return {"first_paid_difference": None, "sequence_status": "unavailable"}
    a, b = left["events"], right["events"]
    for index, (x, y) in enumerate(itertools.zip_longest(a, b), 1):
        if x is None or y is None or (x["pair"], x["answer"]) != (y["pair"], y["answer"]):
            return {"first_paid_difference": index, "sequence_status": "different_complete_sequences" if left["complete"] and right["complete"] else "recorded_prefix_difference"}
    return {"first_paid_difference": None, "sequence_status": "identical_complete_sequences" if left["complete"] and right["complete"] else "identical_recorded_prefix_only"}


def build_contrasts(endpoints, replays, *, historical=()):
    """Prespecified endpoint contrasts, with missing endpoints never imputed."""
    data = list(endpoints); old = list(historical)
    key = lambda r: (r["dataset"], r["budget"], r.get("reference"))
    groups = sorted({key(r) for r in data})
    current = {(*key(r), r["method"]): r for r in data}
    historic = {(*key(r), r["method"]): r for r in old}
    output = []
    full, raw = "cut_plan_cover_fixed", "cut_plan_fixed"
    pairs = [(full, method, "full_vs_"+method) for method in ("edge_betweenness", raw, "cut_plan_adaptive", "cut_plan_cover_singleton")]
    pairs += [("cut_plan_cover_bccap", raw, "coverage_with_bc_cap"),
              (full, "cut_plan_bound_fixed", "coverage_with_bound_screening"),
              ("cut_plan_bound_fixed", raw, "screening_old_pool"),
              (full, "cut_plan_cover_bccap", "screening_union_pool")]
    for group in groups:
        meta = {"dataset": group[0], "budget": group[1], "reference": group[2]}
        for method, comparator, contrast in pairs:
            left = current.get((*group, method)); right = current.get((*group, comparator)) or historic.get((*group, comparator))
            valid = left is not None and right is not None and left["status"] == right["status"] == "completed"
            scope = "contemporaneous_development" if (*group, comparator) in current else "historical_V4_quality_only_no_timing_ranking"
            output.append({**meta, "contrast": contrast, "method": method, "comparator": comparator,
                "scope": scope, "status": "complete" if valid else "missing_endpoint",
                **{"delta_"+k: left[k]-right[k] if valid else None for k in ("fp", "fn", "loss")},
                **first_paid_difference(replays.get(left["run_id"]) if left else None, replays.get(right["run_id"]) if right else None)})
        terms = [(full, 1), ("cut_plan_cover_bccap", -1), ("cut_plan_bound_fixed", -1), (raw, 1)]
        selected = [(current.get((*group, method)) or historic.get((*group, method)), coef) for method, coef in terms]
        valid = all(row is not None and row["status"] == "completed" for row, _ in selected)
        output.append({**meta, "contrast": "coverage_by_screening_factorial_interaction", "method": full, "comparator": "full-cover_bccap-bound_fixed+raw",
            "scope": "contemporaneous_development" if (*group, raw) in current else "historical_V4_quality_only_no_timing_ranking",
            "status": "complete" if valid else "missing_endpoint",
            **{"delta_"+k: sum(coef*row[k] for row,coef in selected) if valid else None for k in ("fp", "fn", "loss")},
            "first_paid_difference": None, "sequence_status": "not_defined_for_four_term_contrast"})
    return output


def analyze_phase(phase, out, *, root=ROOT):
    from cut_audit_er.telemetry import recover_journal
    root = Path(root).resolve(); out = Path(out).resolve()
    require = s.require
    frozen, snapshot = s.checked_freeze(root); study = root / s.SESSION / phase / "study"
    suite = s.read(study / "suite.json"); declared = s.slots(phase)
    require(suite["freeze_sha256"] == s.digest(root / s.SESSION / "freeze.json")
            and suite["phase"] == phase and suite["slots"] == declared, "Study freeze/grid mismatch")
    require(suite["status"] in ("completed", "completed_with_missing", "interrupted"), "Study is still running")
    rows, elapsed, pending = s.ledger_state(study, declared)
    require(pending is None and rows == suite["runs"] and elapsed == suite["active_elapsed_seconds"], "Unfinalized or altered time ledger")
    s.check_hashes(study / "ledger", suite["ledger_files_sha256"])
    # Observable replay inputs are loaded before and separately from evaluator labels.
    assets = s.load_phase_assets(snapshot, phase, include_truth=False)
    out.mkdir(parents=True, exist_ok=False); started = time.perf_counter()
    endpoints, reference_endpoints, events, states, batches, depths = [], [], [], [], [], []
    replay_index = {}
    pins = {"suite.json": s.digest(study / "suite.json"), "consumed.json": s.digest(study / "consumed.json")}
    pins.update({"ledger/" + n: h for n, h in suite["ledger_files_sha256"].items()})
    invocations = []
    for path in sorted((study/"invocations").glob("*.json")):
        invocations.append(s.read(path)); pins[path.relative_to(study).as_posix()] = s.digest(path)
    for slot in rows:
        key = {"run_id": slot["id"], "phase": phase, "dataset": slot["dataset"], "method": slot["method"], "budget": slot["budget"]}
        if phase == "synthetic": key.update(k=slot["k"], profile=slot["profile"])
        row = {**key, "status": slot["status"], "fp": None, "fn": None, "loss": None, "paid": None,
               "paid_lower_bound": 0, "paid_upper_bound": slot["budget"] if slot.get("path") else 0,
               "reason": slot.get("reason")}
        replay = None; complete = slot["status"] == "completed"
        if slot.get("path"):
            path = s.relative(study, slot["path"]); require(s.digest(path) == slot["sha256"], "Run hash differs")
            pins[slot["path"]] = s.digest(path); saved = s.read(path); identity = saved["identity"]
            require(saved["status"] == slot["status"], "Saved status differs from terminal ledger")
            if saved.get("process_absence_path"):
                proof = s.relative(study, saved["process_absence_path"])
                require(s.digest(proof) == saved["process_absence_sha256"], "Process-absence receipt changed")
                pins[saved["process_absence_path"]] = s.digest(proof)
            require(identity == {"run_id": slot["id"], "dataset": slot["dataset"], "method": slot["method"],
                "requested_budget": slot["budget"], "freeze_sha256": suite["freeze_sha256"], "fn_weight": 1., "phase": phase}, "Saved identity differs")
            journal = study / "journals" / (slot["id"] + ".jsonl")
            recovery = recover_journal(journal, identity)
            if journal.exists(): pins[journal.relative_to(study).as_posix()] = s.digest(journal)
            recorded = saved.get("checkpoint_telemetry", {})
            if recorded:
                require(semantic(recorded) == semantic(recovery), "Recorded durable journal recovery differs")
            run = saved["run"] if complete else {"method": slot["method"], "requested_budget": slot["budget"], **recovery}
            if complete:
                require(run.get("complete") is True and run["decisions"] == recovery["decisions"]
                        and run["trace"] == recovery["trace"] and recovery.get("terminal_marker", {}).get("complete") is True, "Complete endpoint lacks matching terminal journal")
            lo = recovery.get("paid_count_lower_bound"); hi = recovery.get("paid_count_upper_bound")
            row.update(paid_lower_bound=lo if lo is not None else 0, paid_upper_bound=hi if hi is not None else slot["budget"])
            if saved["status"] == "not_started_limit":
                require(not recovery.get("decisions"), "Unstarted cell contains paid events")
                row.update(paid_lower_bound=0, paid_upper_bound=0)
            if complete or recovery.get("decisions"):
                graph, scores, _ = assets[slot["dataset"]]
                replay = visible_replay(graph, scores, run, complete=complete)
                truth_path = snapshot / ("inputs/synthetic/H0.json" if phase == "synthetic" else "inputs/natural/"+slot["dataset"]+"/evaluator_reference.json")
                truth = s.read(truth_path)["reference"]
                evaluation = evaluate_replay(replay, truth, run.get("trace", []))
                replay.update(**key, acquisition_reference="H0" if phase == "synthetic" else "natural")
                replay_index[slot["id"]] = replay
                s.write(out / "replays" / (slot["id"] + ".json"), replay)
                row.update(initial_fp=evaluation["initial"]["fp"], initial_fn=evaluation["initial"]["fn"],
                    initial_loss=evaluation["initial"]["loss"], recorded_paid=len(replay["events"]),
                    recorded_prefix_loss=evaluation["final"]["loss"], batches=len(replay["batches"]),
                    committed_multi_batches=sum(len(b["action"]) > 1 for b in replay["batches"]),
                    planned_multi_batches=sum(len(b["planned_action"]) > 1 for b in replay["batches"]))
                if complete: row.update({k: evaluation["final"][k] for k in ("fp", "fn", "loss")}, paid=run["spent"])
                row.update(logical_score_accesses=run.get("score_accesses") if complete else None,
                    selector_seconds=run.get("selection_seconds") if complete else None,
                    audit_seconds=run.get("seconds") if complete else None, worker_wall_seconds=saved.get("worker_wall_seconds"),
                    stop_reason=run.get("stop_reason") if complete else None, **saved.get("worker_timing", {}))
                events.extend({**key, **e, "endpoint_complete": complete} for e in evaluation["events"])
                states.extend({**key, **v, "endpoint_complete": complete} for v in evaluation["states"])
                for batch in replay["batches"]:
                    info = batch["selection_info"]
                    brow = {**key, "batch": batch["batch"], "spent_before": batch["spent_before"],
                        "remaining": batch["remaining"], "action_size": len(batch["action"]), "planned_depth": len(batch["planned_action"]),
                        "recorded_queries": batch["recorded_queries"], "batch_fully_recorded": batch["batch_fully_recorded"],
                        "fallback": info.get("fallback"), "certificate_status": info.get("surrogate_certificate_status"),
                        "argmax_certified": info.get("surrogate_argmax_certified"), "endpoint_complete": complete}
                    positive = not info.get("fallback") and info.get("selected_proxy_score",0) > 0
                    brow.update(positive_plan_selected=bool(positive),
                        certified_positive_plan=bool(positive and info.get("surrogate_argmax_certified")),
                        certified_nonpositive_pool=bool(info.get("surrogate_argmax_certified") and info.get("selected_proxy_score",0)<=0),
                        selected_stage_scope="actual_BC_edge_action" if slot["method"]=="edge_betweenness" else "positive_proxy_plan_only")
                    for field in ("numeric_scan_score_entry_reads", "bound_evaluations", "enumerated_subsets", "score_limit_unscored",
                                  "scored_candidate_actions", "numeric_scan_cache_hit", "exhaustive_components", "oversized_components",
                                  "full_graph_bond_pool_complete", "small_component_bond_pool_complete", "max_unscored_upper_bound",
                                  "max_unscored_upper_bound_finite", "candidate_cap", "score_evaluation_cap", "cap_applied"):
                        brow[field] = info.get(field)
                    # Saved acquisition timings, not new replay timings; counted once per batch.
                    recorded_info = next(d["selection_info"] for d in run["decisions"] if d["batch"] == batch["batch"])
                    brow["selection_seconds"] = next(d["selection_seconds"] for d in run["decisions"] if d["batch"] == batch["batch"])
                    for field, value in recorded_info.items():
                        if field.endswith("_seconds"): brow[field] = value
                    for field, value in recorded_info.get("topology_cache", {}).items(): brow["topology_"+field] = value
                    batches.append(brow)
                    for stage, plans in stages(batch | {"method": slot["method"]}).items():
                        for depth in (1, 2, 3, 4):
                            depths.append({**key, "batch": batch["batch"], "stage": stage, "depth": depth,
                                           "count": sum(len(p) == depth for p in plans), "stage_denominator": len(plans),
                                           "endpoint_complete": complete})
        endpoints.append(row)
        if phase == "synthetic":
            for ref in ("H0", "H9"):
                erow = {**key, "reference": ref, "status": slot["status"], "fp": None, "fn": None, "loss": None,
                        "reused_acquisition": True, "independent_observation": False}
                if replay is not None:
                    truth = s.read(snapshot / f"inputs/synthetic/{ref}.json")["reference"]
                    result = evaluate_replay(replay, truth)
                    erow.update(initial_fp=result["initial"]["fp"], initial_fn=result["initial"]["fn"], recorded_prefix_loss=result["final"]["loss"])
                    if complete: erow.update({k: result["final"][k] for k in ("fp", "fn", "loss")})
                reference_endpoints.append(erow)
    historical_pins = {}
    contrasts = build_contrasts(endpoints, replay_index)
    if phase == "synthetic":
        old_base = root / s.HISTORICAL_SYNTHETIC
        historical_pins = {name: frozen["historical_inputs_sha256"][name]
                           for name in (s.HISTORICAL_SYNTHETIC+"/manifest.json", s.HISTORICAL_SYNTHETIC+"/endpoints.csv")}
        s.check_hashes(root, historical_pins)
        old_manifest = s.read(old_base / "manifest.json")
        # Only fixed historical endpoints are used; no new acquisition or V4 refit.
        with (old_base / "endpoints.csv").open(encoding="utf-8", newline="") as stream:
            old_rows = list(csv.DictReader(stream))
        historical = []
        for old in old_rows:
            historical.append({**old, "dataset": f"k{old['k']}_{old['score_profile']}", "budget": int(old["budget"]),
                               **{key: int(old[key]) if old[key] else None for key in ("fp", "fn", "loss")}})
            # Reuse already validated, saved V4 trace only for sequence identity comparison.
            path = old_base / "replays" / (old["run_id"]+".json")
            name = path.relative_to(old_base).as_posix()
            if name in old_manifest["files_sha256"] and old["run_id"] not in replay_index:
                s.check_hashes(old_base, {name: old_manifest["files_sha256"][name]})
                saved_replay = s.read(path)
                # V4 uses paid decisions in its visible trajectory; convert only
                # when actual pair/answer identities are present.
                saved_events = saved_replay.get("decisions", saved_replay.get("events", []))
                if saved_events and all(("pair" in e or ("u" in e and "v" in e)) and ("answer" in e or "observed_match" in e) for e in saved_events):
                    replay_index[old["run_id"]] = {"complete": old["status"] == "completed",
                        "events": [{"pair": e.get("pair",[e.get("u"),e.get("v")]), "answer": e.get("answer", e.get("observed_match"))} for e in saved_events]}
                historical_pins[path.relative_to(root).as_posix()] = s.digest(path)
        contrasts = build_contrasts(reference_endpoints, replay_index, historical=historical)
    if phase == "natural":
        gate = external_gate(endpoints); s.write(out / "external_gate.json", gate)
    tables = {"endpoints": endpoints, "reference_endpoints": reference_endpoints, "events": events,
              "states": states, "batches": batches, "candidate_depths": depths, "contrasts": contrasts,
              "missing": [{k: r.get(k) for k in ("run_id", "status", "reason", "paid_lower_bound", "paid_upper_bound")}
                          for r in endpoints if r["status"] != "completed"]}
    for name, values in tables.items(): csv_write(out / (name + ".csv"), values)
    s.write(out / "sources.json", {"study_files_sha256": pins, "freeze_sha256": suite["freeze_sha256"],
        "analysis_source_sha256": s.digest(Path(__file__)), "historical_files_sha256": historical_pins,
        "new_oracle_answers": 0, "new_policy_endpoints": 0})
    s.write(out/"timing.json", {"active_elapsed_seconds_in_ledger":elapsed,"invocations":invocations,
        "scope":"Per-clock ledger plus explicitly measured final-publication remainder; do not sum nested selector subphases",
        "no_strict_os_wall_guarantee":True})
    files = {p.relative_to(out).as_posix(): s.digest(p) for p in sorted(out.rglob("*")) if p.is_file()}
    result = {"schema": "cut-audit-v5-analysis-v1", "status": "passed", "phase": phase, "files_sha256": files,
              "counts": {"acquisitions_planned": len(rows), "acquisitions_completed": sum(r["status"] == "completed" for r in endpoints),
                         "reference_endpoints": len(reference_endpoints), "reference_completed": sum(r["status"] == "completed" for r in reference_endpoints),
                         "paid_lower_bound": sum(r["paid_lower_bound"] for r in endpoints), "paid_upper_bound": sum(r["paid_upper_bound"] for r in endpoints)},
              "seconds": time.perf_counter() - started, "cost_scope": "Acquisition counted once; H0/H9 dependent offline evaluations",
              "new_oracle_answers": 0, "opportunity_diagnosis": "separate module; no global absence inferred here"}
    s.write(out / "manifest.json", result); return result


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument("--phase", choices=("synthetic", "natural"), required=True)
    p.add_argument("--out", type=Path); args = p.parse_args()
    out = args.out or ROOT / s.SESSION / args.phase / "analysis"
    print(json.dumps(analyze_phase(args.phase, out)))


if __name__ == "__main__": main()
