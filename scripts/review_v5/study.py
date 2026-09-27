"""Frozen V5 acquisitions with an immutable one-attempt, per-graph time ledger.

No work runs on import. The fixed graphs are already exposed development data.
An unfinished launch is permanently missing; continuation never retries it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
SESSION = "outputs/session_20260927_v5"
CONFIG = "configs/review_v5_study.json"
PROTOCOL = "research/review_v5/PROTOCOL.md"
HISTORICAL_SYNTHETIC = "outputs/session_20260927_v4/synthetic/analysis"
NEW_METHODS = ("cut_plan_cover_bccap", "cut_plan_bound_fixed", "cut_plan_cover_fixed", "cut_plan_cover_singleton")
SYNTHETIC_METHODS = ("cut_plan_adaptive", *NEW_METHODS)
NATURAL_METHODS = ("edge_betweenness", "cut_plan_fixed", *SYNTHETIC_METHODS)
DATASETS = ("wdc", "dblp_acm", "dblp_unused")
ENV = {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def require(value, message):
    if not value: raise ValueError(message)


def blob(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def utc(): return datetime.now(timezone.utc).isoformat()


def write(path, value, *, replace=False):
    """Fsync contents before atomic publication; default is exclusive creation."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    target = path.with_name(path.name + ".tmp") if replace else path
    with target.open("wb" if replace else "xb") as stream:
        stream.write(blob(value)); stream.flush(); os.fsync(stream.fileno())
    if replace: os.replace(target, path)


def relative(root, name):
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name
            and not name.startswith("/") and all(x not in ("", ".", "..") for x in name.split("/")), "Unsafe relative path")
    path = (Path(root) / name).resolve()
    require(path.is_relative_to(Path(root).resolve()), "Path escapes root")
    return path


def check_hashes(root, pins):
    require(isinstance(pins, dict) and pins, "Empty source manifest")
    for name, expected in pins.items():
        path = relative(root, name)
        require(path.is_file() and digest(path) == expected, "Source hash mismatch: " + name)


def fixed_config():
    return {"schema": "cut-audit-v5-study-config-v1", "seed": 7, "noise": 0, "fn_weight": 1,
            "max_depth": 4, "candidate_cap": 64, "cpu_threads": 1, "formal_test_access": False,
            "new_fits": 0, "new_downloads": 0, "natural_datasets": list(DATASETS),
            "natural_methods": list(NATURAL_METHODS), "natural_budgets": [12, 24, 48],
            "natural_worker_seconds": 120, "natural_active_seconds_per_graph": 2700,
            "synthetic_methods": list(SYNTHETIC_METHODS), "synthetic_budgets": [1, 2, 3, 4, 6],
            "synthetic_conditions": [{"k": k, "profile": p} for k in (1, 2, 3) for p in ("uniform", "ranked")],
            "synthetic_worker_seconds": 30, "synthetic_active_seconds": 900,
            "order": "budget_then_dataset_or_condition_then_method", "one_attempt_per_cell": True,
            "external_gate": "complete_new_natural_cover_fixed_strictly_better_than_new_raw_matched_dataset_budget",
            "protocol": PROTOCOL, "output": SESSION}


def validate_config(value):
    require(blob(value) == blob(fixed_config()), "Prespecified V5 configuration differs")
    return value


def slots(phase):
    if phase == "synthetic":
        return [{"id": f"k{k}_{p}_{m}_B{b}", "dataset": f"k{k}_{p}", "k": k, "profile": p,
                 "method": m, "budget": b, "status": "not_started"}
                for b in (1, 2, 3, 4, 6) for k in (1, 2, 3) for p in ("uniform", "ranked") for m in SYNTHETIC_METHODS]
    require(phase == "natural", "Unknown phase")
    return [{"id": f"{d}_{m}_B{b}", "dataset": d, "method": m, "budget": b, "status": "not_started"}
            for b in (12, 24, 48) for d in DATASETS for m in NATURAL_METHODS]


def source_names(root):
    names = {p.relative_to(root).as_posix() for p in (root / "src/cut_audit_er").glob("*.py")}
    names |= {CONFIG, PROTOCOL, "scripts/review_v4/synthetic.py", "scripts/review_v4/cohort.py",
              "scripts/review_v4/replay.py", "scripts/mechanism_study/assets.py",
              "scripts/conference_improvement/replay.py", "scripts/conference_improvement/finite_budget.py",
              "scripts/structural_study/assets.py", "scripts/run_logged.py",
              "scripts/review_v5/study.py", "scripts/review_v5/analysis.py",
              "scripts/review_v5/opportunities.py", "scripts/review_v5/legacy_validation.py",
              "research/review_v5/THEORY.md", "research/review_v5/NUMERIC_BOUND.md",
              "tests/test_review_v5_study.py", "tests/test_review_v5_analysis.py",
              "tests/test_review_v5_opportunities.py", "tests/test_review_v5_planner.py"}
    names.add("tests/test_review_v5_ledger_independent.py")
    # Only named scientific files: later delivery/plot/export scripts and their
    # tests are deliberately outside this acquisition freeze.
    for name in ("scripts/__init__.py", "scripts/review_v5/__init__.py", "scripts/review_v4/__init__.py",
                 "scripts/mechanism_study/__init__.py", "scripts/conference_improvement/__init__.py"):
        if (root / name).is_file(): names.add(name)
    return names


def historical_natural_assets(root):
    """Old freezes use original snapshots, never require new src == V4 src."""
    from scripts.mechanism_study.assets import load_assets
    from scripts.review_v4 import cohort
    assets, pins = {}, {}
    for name in DATASETS[:2]:
        graph, scores, truth, provenance, _, _ = load_assets(name, include_truth=True, root=root)
        assets[name] = (graph, scores, truth)
        pins.update(provenance["source_receipts"])
        pins[provenance["archive"]] = provenance["archive_sha256"]
    folder = root / cohort.SESSION
    frozen = read(folder / "freeze.json")
    snapshot = relative(root, frozen["snapshot"])
    old_sources = {n: h for n, h in frozen["files_sha256"].items()
                   if n.startswith("src/cut_audit_er/") or n in ("scripts/review_v4/cohort.py", cohort.CONFIG, cohort.PROTOCOL)}
    require(bool(old_sources), "Missing original V4 engine pins")
    check_hashes(snapshot, old_sources)
    pins.update({(snapshot / n).relative_to(root).as_posix(): h for n, h in old_sources.items()})
    graph, scores, truth, receipt = cohort.load_graph(root)
    assets["dblp_unused"] = (graph, scores, truth)
    for name in ("freeze.json", "graph/receipt.json", "restore/receipt.json", "audit/membership.json"):
        pins[(folder / name).relative_to(root).as_posix()] = digest(folder / name)
    pins.update({(folder / "graph" / n).relative_to(root).as_posix(): h for n, h in receipt["files_sha256"].items()})
    return assets, pins


def create_freeze(root=ROOT, validation=None, baseline=None):
    import numpy as np
    from scripts.review_v4.synthetic import visible_recipe, load_visible, reference_recipe, answer_table
    from scripts.review_v4.replay import observable, graph_from_observable
    root = Path(root).resolve(); cfg = validate_config(read(root / CONFIG))
    folder = root / SESSION; freeze_path = folder / "freeze.json"; snapshot = folder / "source_snapshot"
    require(not freeze_path.exists() and not snapshot.exists(), "V5 freeze already exists")
    names = source_names(root)
    numeric_path = root/"research/review_v5/NUMERIC_AUDIT.json"
    numeric = read(numeric_path)
    require(numeric.get("status") == "PASS_WITH_EXPLICIT_SCOPE", "Independent numerical audit must pass")
    check_hashes(root,numeric["source_sha256"])
    require(digest(relative(root,numeric["test_receipt"])) == numeric["test_receipt_sha256"], "Numerical test receipt changed")
    names.add(numeric_path.relative_to(root).as_posix()); names.add(numeric["test_receipt"])
    ntest=relative(root,numeric["test_receipt"]); nreceipt=read(ntest)
    require(nreceipt["exit_code"]==0 and not nreceipt["timed_out"], "Numerical tests failed")
    check_hashes(ntest.parent,nreceipt["output_sha256"])
    names.update((ntest.parent/n).relative_to(root).as_posix() for n in nreceipt["output_sha256"])
    legacy_path=root/SESSION/"legacy_replay/receipt.json"; legacy=read(legacy_path)
    require(legacy.get("status")=="passed" and legacy.get("cases")==21 and legacy.get("new_oracle_answers")==0, "Complete 21-case legacy replay required")
    check_hashes(legacy_path.parent,legacy["files_sha256"])
    names.add(legacy_path.relative_to(root).as_posix())
    names.update((legacy_path.parent/n).relative_to(root).as_posix() for n in legacy["files_sha256"])
    for name in ("standard_smoke_command", "new_policy_smoke_command"):
        path=root/SESSION/name/"command.json"; receipt=read(path)
        require(receipt["exit_code"]==0 and not receipt["timed_out"], "Graph/policy smoke must pass")
        check_hashes(path.parent,receipt["output_sha256"]); names.add(path.relative_to(root).as_posix())
        names.update((path.parent/n).relative_to(root).as_posix() for n in receipt["output_sha256"])
    for receipt_path in (validation, baseline):
        require(receipt_path is not None, "Both baseline and integration receipts are required")
        path = Path(receipt_path).resolve(); require(path.is_relative_to(root), "Validation outside root")
        receipt = read(path)
        require(receipt.get("exit_code") == 0 and receipt.get("timed_out") is False
                and receipt.get("cpu_threads") == 1 and receipt.get("python_hash_seed") == "0", "Pinned passing validation required")
        check_hashes(path.parent, receipt["output_sha256"])
        names.add(path.relative_to(root).as_posix())
        names.update((path.parent / n).relative_to(root).as_posix() for n in receipt["output_sha256"])
    natural, historic = historical_natural_assets(root)
    old_analysis = root / HISTORICAL_SYNTHETIC
    old_manifest = read(old_analysis / "manifest.json")
    check_hashes(old_analysis, old_manifest["files_sha256"])
    historic[HISTORICAL_SYNTHETIC + "/manifest.json"] = digest(old_analysis / "manifest.json")
    historic[HISTORICAL_SYNTHETIC + "/endpoints.csv"] = digest(old_analysis / "endpoints.csv")
    pins = {n: digest(relative(root, n)) for n in sorted(names)}
    snapshot.mkdir(parents=True)
    for name in names:
        target = snapshot / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    input_pins = {}
    for name, (graph, scores, truth) in natural.items():
        dest = snapshot / "inputs/natural" / name; dest.mkdir(parents=True)
        description = observable(graph, scores)
        restored, restored_scores = graph_from_observable(description, scores.matrix)
        require(observable(restored, restored_scores) == description, "Observable order round trip differs")
        write(dest / "observable.json", description); np.save(dest / "scores.npy", scores.matrix, allow_pickle=False)
        write(dest / "evaluator_reference.json", {"reference": truth, "scope": "already exposed development oracle/evaluator only"})
    for k in (1, 2, 3):
        for profile in ("uniform", "ranked"):
            value = visible_recipe(k, profile); graph, _ = load_visible(value)
            require(answer_table(graph, reference_recipe("H0")) == answer_table(graph, reference_recipe("H9")), "Paired oracle answers differ")
            write(snapshot / f"inputs/synthetic/k{k}_{profile}.json", value)
    for ref in ("H0", "H9"):
        write(snapshot / f"inputs/synthetic/{ref}.json", {"reference": reference_recipe(ref), "offline_only": True})
    for path in sorted((snapshot / "inputs").rglob("*")):
        if path.is_file(): input_pins[path.relative_to(snapshot).as_posix()] = digest(path)
    frozen = {"schema": "cut-audit-v5-freeze-v1", "created_utc": utc(), "config": cfg,
              "formal_test_access": False, "human_approval_claimed": False, "before_v5_acquisition": True,
              "source_snapshot": snapshot.relative_to(root).as_posix(), "files_sha256": pins,
              "historical_inputs_sha256": historic, "snapshot_inputs_sha256": input_pins,
              "synthetic_slots": slots("synthetic"), "natural_slots": slots("natural"),
              "environment": {"python": platform.python_version(), **ENV}}
    write(freeze_path, frozen); return frozen


def checked_freeze(root):
    root = Path(root).resolve(); frozen = read(root / SESSION / "freeze.json")
    require(frozen.get("schema") == "cut-audit-v5-freeze-v1" and frozen.get("formal_test_access") is False, "Wrong V5 freeze")
    validate_config(frozen["config"]); validate_config(read(root / CONFIG))
    require(frozen["synthetic_slots"] == slots("synthetic") and frozen["natural_slots"] == slots("natural"), "Frozen grid differs")
    require(source_names(root) <= frozen["files_sha256"].keys(), "Execution dependency omitted from freeze")
    check_hashes(root, frozen["files_sha256"])
    snapshot = relative(root, frozen["source_snapshot"])
    check_hashes(snapshot, frozen["files_sha256"]); check_hashes(snapshot, frozen["snapshot_inputs_sha256"])
    return frozen, snapshot


def load_phase_assets(snapshot, phase, *, include_truth=True):
    import numpy as np
    from scripts.review_v4.synthetic import load_visible
    from scripts.review_v4.replay import graph_from_observable
    assets = {}
    if phase == "synthetic":
        truth = read(snapshot / "inputs/synthetic/H0.json")["reference"] if include_truth else None
        for k in (1, 2, 3):
            for profile in ("uniform", "ranked"):
                name = f"k{k}_{profile}"; graph, scores = load_visible(read(snapshot / f"inputs/synthetic/{name}.json"))
                assets[name] = (graph, scores, dict(truth) if include_truth else None)
    else:
        for name in DATASETS:
            base = snapshot / "inputs/natural" / name
            graph, scores = graph_from_observable(read(base / "observable.json"), np.load(base / "scores.npy", allow_pickle=False))
            assets[name] = (graph, scores, read(base / "evaluator_reference.json")["reference"] if include_truth else None)
    return assets


def ledger_events(out):
    """Exclusive immutable event files form a verified append-only hash chain."""
    out = Path(out); events = []; previous = None
    for index, path in enumerate(sorted((out / "ledger").glob("*.json"))):
        require(path.name == f"{index:06d}.json", "Ledger sequence gap")
        event = read(path); require(event.get("seq") == index and event.get("previous_sha256") == previous, "Ledger hash chain differs")
        events.append(event); previous = digest(path)
    return events


def append_event(out, event):
    events = ledger_events(out)
    previous = digest(Path(out) / "ledger" / f"{len(events)-1:06d}.json") if events else None
    value = {**event, "seq": len(events), "previous_sha256": previous}
    write(Path(out) / "ledger" / f"{len(events):06d}.json", value)
    return value


def ledger_state(out, declared):
    rows = {s["id"]: dict(s) for s in declared}; active = {}; elapsed = {}; pending = None
    launches = []; events = ledger_events(out)
    for event in events:
        kind = event["kind"]
        if kind == "launch":
            run_id = event["id"]
            require(pending is None and run_id in rows and run_id not in active, "Repeated or overlapping launch")
            require(run_id == next((s["id"] for s in declared if rows[s["id"]]["status"] == "not_started"), None), "Launch order differs")
            require(event["active_elapsed_before"] == elapsed.get(event["clock_key"], 0.), "Cumulative elapsed ledger reset")
            require(type(event["remaining_before"]) in (int, float) and math.isfinite(event["remaining_before"])
                    and event["remaining_before"] > 0, "Launch without remaining time")
            active[run_id] = event; pending = event; launches.append(run_id); rows[run_id]["status"] = "running"
        elif kind == "finish":
            run_id = event["id"]
            require(pending is not None and pending["id"] == run_id, "Finish without unique launch")
            require(type(event["charged_seconds"]) in (int, float) and math.isfinite(event["charged_seconds"])
                    and event["charged_seconds"] >= 0, "Invalid elapsed debit")
            key = pending["clock_key"]; elapsed[key] = elapsed.get(key, 0.) + event["charged_seconds"]
            row = event["result"]
            require(row["status"] not in ("not_started", "running"), "Nonterminal finish")
            require(not (set(row) & (set(rows[run_id]) - {"status"})), "Finish overwrites declared slot")
            rows[run_id].update(row); pending = None
        elif kind == "skip":
            run_id = event["id"]
            require(pending is None and run_id in rows and rows[run_id]["status"] == "not_started", "Invalid skipped cell")
            require(run_id == next((s["id"] for s in declared if rows[s["id"]]["status"] == "not_started"), None), "Skip order differs")
            rows[run_id].update(status="not_started_limit", reason=event["reason"])
        elif kind == "time_debit":
            require(pending is None and event["clock_key"] in {"synthetic", *(r["dataset"] for r in declared)}, "Invalid overhead clock")
            require(type(event["charged_seconds"]) in (int,float) and math.isfinite(event["charged_seconds"])
                    and event["charged_seconds"] >= 0, "Invalid overhead debit")
            key = event["clock_key"]; elapsed[key] = elapsed.get(key,0.) + event["charged_seconds"]
        else: raise ValueError("Unknown ledger event")
    return [rows[s["id"]] for s in declared], elapsed, pending


def recover_pending(out, declared, absence_receipt, *, now=time.time):
    rows, elapsed, pending = ledger_state(out, declared)
    require(pending is not None, "No interrupted launch to recover")
    proof = read(absence_receipt)
    require(proof.get("status") == "confirmed_absent" and proof.get("scope") == "V5_workers_and_supervisor"
            and proof.get("active_python_workers") == 0, "Independent process-absence receipt required")
    require(proof.get("launch_identity_sha256") == hashlib.sha256(blob(pending)).hexdigest(), "Process-absence receipt belongs to another launch")
    require(type(proof.get("checked_epoch_seconds")) in (int, float)
            and proof["checked_epoch_seconds"] >= pending["started_epoch_seconds"], "Stale process-absence receipt")
    require(now() >= proof["checked_epoch_seconds"], "Future process-absence receipt")
    proof_path = Path(out) / "recovery" / (pending["id"] + ".process_absence.json")
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with proof_path.open("xb") as stream:
        stream.write(Path(absence_receipt).read_bytes()); stream.flush(); os.fsync(stream.fileno())
    from cut_audit_er.telemetry import recover_journal
    journal = Path(out) / "journals" / (pending["id"] + ".jsonl")
    recovery = recover_journal(journal, pending["identity"])
    result = {"status": "interrupted", "reason": "Supervisor lost; formal slot permanently missing, never retried",
              "identity": pending["identity"], "checkpoint_telemetry": recovery,
              "process_absence_sha256": digest(proof_path), "process_absence_path": proof_path.relative_to(out).as_posix(),
              "complete_result_promoted": False}
    path = Path(out) / "runs" / (pending["id"] + ".json")
    # A payload not committed to the ledger is retained as an unaccepted artifact.
    if path.exists():
        result["unaccepted_result_sha256"] = digest(path)
        path = Path(out) / "runs" / (pending["id"] + ".interrupted.json")
    write(path, result)
    charged = max(0., now() - pending["started_epoch_seconds"])
    append_event(out, {"kind": "finish", "id": pending["id"], "charged_seconds": charged,
        "charge_scope": "Conservative entire interrupted active interval including downtime; original cap not reset",
        "result": {"status": "interrupted", "reason": result["reason"], "path": path.relative_to(out).as_posix(), "sha256": digest(path)}})


def execute_grid(out, phase, declared, assets, freeze_sha, *, continue_run=False, absence_receipt=None,
                 audit_fn=None, clock=time.perf_counter, epoch=time.time, before_cell=lambda: None):
    from cut_audit_er.natural import bounded_audit
    audit_fn = bounded_audit if audit_fn is None else audit_fn
    require(phase in ("synthetic", "natural"), "Unknown study phase")
    out = Path(out); invocation_start = clock()
    scope = {"phase": phase, "freeze_sha256": freeze_sha, "slots": declared, "retries_allowed": False,
             "worker_seconds": 30 if phase == "synthetic" else 120,
             "active_seconds_per_clock": 900 if phase == "synthetic" else 2700}
    if not continue_run:
        out.mkdir(parents=True, exist_ok=False)
        write(out / "consumed.json", scope | {"created_utc": utc()})
    else:
        stored = read(out / "consumed.json")
        require(all(stored.get(k) == v for k, v in scope.items()), "Consumed scope/freeze differs")
        prior_checkpoint=read(out/"suite.json")
        if prior_checkpoint.get("ledger_files_sha256"):
            check_hashes(out/"ledger",prior_checkpoint["ledger_files_sha256"])
    rows, elapsed, pending = ledger_state(out, declared)
    if continue_run:
        require(not any(r["status"] == "cleanup_failed" for r in rows), "Cleanup failure permanently blocks continuation")
        for row in rows:
            if row.get("path"):
                path = relative(out,row["path"])
                require(path.is_file() and digest(path) == row["sha256"], "Prior run changed before continuation")
                require(not read(path).get("cleanup_worker_still_alive"), "Live worker permanently blocks continuation")
        already = {e.get("receipt_sha256") for e in ledger_events(out) if e["kind"] == "time_debit"}
        if pending is None:
            for path in sorted((out/"invocations").glob("*.json")):
                prior = read(path); remainder = prior.get("final_publication_seconds_not_in_ledger")
                if remainder and digest(path) not in already:
                    append_event(out, {"kind":"time_debit", "clock_key":prior["clock_key"], "charged_seconds":remainder,
                        "reason":"Closing publication remainder from prior invocation, charged before continuation",
                        "receipt_sha256":digest(path), "receipt_path":path.relative_to(out).as_posix()})
    if pending:
        require(continue_run and absence_receipt is not None, "Unfinished worker requires independent absence proof")
        recover_pending(out, declared, absence_receipt, now=epoch)
    suite = {"schema": "cut-audit-v5-suite-v1", **scope, "formal_test_access": False,
             "new_fits": 0, "new_downloads": 0, "status": "running", "phase_started_utc": utc(),
             "timing_scope": "Active cell preparation, worker, serialization and orchestration ledger debits; per-graph clocks. Final receipt publication remainder reported separately. Synchronous startup/IPC not strict OS wall limit."}
    def checkpoint():
        rr, ee, pp = ledger_state(out, declared)
        suite.update(runs=rr, active_elapsed_seconds=ee, pending_launch=pp,
                     ledger_files_sha256={p.name: digest(p) for p in sorted((out / "ledger").glob("*.json"))})
        write(out / "suite.json", suite, replace=True)
    checkpoint()
    last_accounted = invocation_start
    previous_key = "synthetic" if phase == "synthetic" else declared[0]["dataset"]
    def overhead(key, reason):
        nonlocal last_accounted
        measured = clock()
        seconds = max(0., measured-last_accounted)
        if seconds:
            append_event(out, {"kind":"time_debit", "clock_key":key, "charged_seconds":seconds, "reason":reason})
        last_accounted = measured
    try:
        for slot in declared:
            overhead(previous_key, "Prior orchestration including ledger publication/checkpoint")
            start = last_accounted
            rr, ee, pp = ledger_state(out, declared)
            row = next(r for r in rr if r["id"] == slot["id"])
            if row["status"] != "not_started": continue
            key = "synthetic" if phase == "synthetic" else slot["dataset"]
            previous_key = key
            remaining = scope["active_seconds_per_clock"] - ee.get(key, 0.)
            if remaining <= 0:
                append_event(out, {"kind": "skip", "id": slot["id"], "reason": "Original active suite budget exhausted"}); checkpoint(); continue
            identity = {"run_id": slot["id"], "dataset": slot["dataset"], "method": slot["method"],
                        "requested_budget": slot["budget"], "freeze_sha256": freeze_sha, "fn_weight": 1., "phase": phase}
            append_event(out, {"kind": "launch", "id": slot["id"], "clock_key": key, "identity": identity,
                "started_epoch_seconds": epoch(), "started_utc": utc(), "supervisor_pid": os.getpid(),
                "active_elapsed_before": ee.get(key, 0.), "remaining_before": remaining})
            checkpoint(); before_cell()
            graph, scores, truth = assets[slot["dataset"]]
            left = remaining - (clock() - start)
            if left <= 0:
                result = {"status": "not_started_limit", "error": "Cell preparation exhausted remaining active budget", "identity": identity}
            else:
                result = audit_fn(dict(g=graph.copy(), scores=scores.copy(), truth=dict(truth), method=slot["method"],
                    budget=slot["budget"], seed=7, noise=0., fn_weight=1., max_width=2, shortlist=24, match_threshold=.6),
                    min(scope["worker_seconds"], left), out / "journals" / (slot["id"] + ".jsonl"), identity)
                result["identity"] = identity
            if result.get("status") == "completed" and result.get("run", {}).get("complete") is not True:
                result["status"] = "incomplete"
            path = out / "runs" / (slot["id"] + ".json"); write(path, result)
            item = {"status": result["status"], "path": path.relative_to(out).as_posix(), "sha256": digest(path)}
            if result["status"] != "completed": item["reason"] = result.get("error", result["status"])
            measured = clock()
            append_event(out, {"kind": "finish", "id": slot["id"], "charged_seconds": max(0., measured - start), "result": item})
            last_accounted = measured
            checkpoint()
            require(not result.get("cleanup_worker_still_alive"), "Worker still alive; no subsequent launch")
        suite["status"] = "completed" if all(r["status"] == "completed" for r in suite["runs"]) else "completed_with_missing"
    except BaseException as exc:
        suite.update(status="interrupted", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        rr, ee, pp = ledger_state(out,declared)
        if pp is None: overhead(previous_key, "Final orchestration before closing publication")
        suite["invocation_wall_seconds_before_closing_publication"] = max(0.,clock()-invocation_start)
        checkpoint()
        remainder = max(0.,clock()-last_accounted) if pp is None else None
        # This independent receipt measures the last ledger/checkpoint writes;
        # its own write is necessarily outside its timing observation.
        receipt = {"phase":phase,"clock_key":previous_key,"status":suite["status"],
            "actual_wall_seconds_before_receipt_write":max(0.,clock()-invocation_start),
            "final_publication_seconds_not_in_ledger":remainder,
            "active_elapsed_seconds_in_ledger":suite["active_elapsed_seconds"],
            "scope":"Final ledger append and suite checkpoint; receipt's own write excluded; no further worker starts in this invocation",
            "pending_launch":pp is not None,"suite_sha256":digest(out/"suite.json")}
        number=len(list((out/"invocations").glob("*.json")))
        write(out/"invocations"/f"{number:04d}.json",receipt)
    return suite


def run_phase(phase, *, root=ROOT, continue_run=False, absence_receipt=None):
    root = Path(root).resolve(); frozen, snapshot = checked_freeze(root)
    require(all(os.environ.get(k) == v for k, v in ENV.items()), "Pin CPU/hash environment before startup")
    if phase == "natural":
        prior = root / SESSION / "synthetic/study"; previous = read(prior / "suite.json")
        require(previous["status"] in ("completed", "completed_with_missing") and previous.get("pending_launch") is None,
                "Synthetic phase must finish before natural acquisitions")
        require(previous["freeze_sha256"] == digest(root / SESSION / "freeze.json")
                and previous["slots"] == slots("synthetic") and previous["phase"] == "synthetic", "Prior synthetic freeze/grid differs")
        rr, ee, pp = ledger_state(prior, slots("synthetic"))
        require(pp is None and rr == previous["runs"] and ee == previous["active_elapsed_seconds"], "Prior synthetic ledger differs")
        check_hashes(prior / "ledger", previous["ledger_files_sha256"])
    assets = load_phase_assets(snapshot, phase)
    return execute_grid(root / SESSION / phase / "study", phase, slots(phase), assets,
                        digest(root / SESSION / "freeze.json"), continue_run=continue_run,
                        absence_receipt=absence_receipt, before_cell=lambda: checked_freeze(root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "continue")); parser.add_argument("--phase", choices=("synthetic", "natural"))
    parser.add_argument("--validation", type=Path); parser.add_argument("--baseline", type=Path); parser.add_argument("--absence-receipt", type=Path)
    args = parser.parse_args()
    if args.action == "freeze": value = create_freeze(validation=args.validation, baseline=args.baseline)
    else:
        require(args.phase is not None, "Study phase required")
        value = run_phase(args.phase, continue_run=args.action == "continue", absence_receipt=args.absence_receipt)
    print(json.dumps({"status": value.get("status", "frozen"), "phase": args.phase}))


if __name__ == "__main__": main()
