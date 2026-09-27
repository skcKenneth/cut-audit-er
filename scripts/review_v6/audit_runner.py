"""Hash-bound V6 saved-state diagnostics in separate visible/evaluator processes.

No paid query, model fitting, download or selector modification occurs here.
Each input manifest can launch each stage once. Visible and evaluator stages
share the original per-cohort time allowance. Timed-out states remain unknown.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from scripts.review_v5 import study as s
from scripts.review_v5.analysis import csv_write

FULL = "cut_plan_cover_fixed"
ENV = {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}


def code_pins(root):
    names = ["scripts/review_v6/audit.py", "scripts/review_v6/audit_runner.py",
             "scripts/review_v4/replay.py", "scripts/review_v4/synthetic.py",
             "scripts/review_v5/opportunities.py", "scripts/review_v5/analysis.py", "scripts/review_v5/study.py"]
    names += [p.relative_to(root).as_posix() for p in (root / "src/cut_audit_er").glob("*.py")]
    return {n: s.digest(root / n) for n in sorted(names)}


def checked_manifest(path, expected, *, root=ROOT, all_files=True):
    path = Path(path).resolve()
    s.require(path.is_file() and s.digest(path) == expected, "Source manifest hash mismatch")
    manifest = s.read(path)
    s.check_hashes(Path(root), manifest["code_sha256"])
    if all_files:
        s.check_hashes(path.parent, manifest["files_sha256"])
    return manifest


def validate_jobs(jobs):
    s.require(isinstance(jobs, list) and len({j["id"] for j in jobs}) == len(jobs), "Duplicate diagnostic state slots")
    for job in jobs:
        phase = job["phase"]
        s.require(phase in ("natural", "synthetic", "external"), "Unknown diagnostic phase")
        s.require(job["worker_seconds"] == (30 if phase == "synthetic" else 120)
                  and job["suite_seconds"] == (900 if phase == "synthetic" else 2700),
                  "Frozen diagnostic resource limits differ")
        s.require(job["cohort"] == ("synthetic" if phase == "synthetic" else job["dataset"]), "Diagnostic cohort grouping differs")
        s.require(type(job["batch"]) is int and job["batch"] > 0, "Invalid diagnostic batch")
    return jobs


def prepare_inputs(out, assets, replays, references, *, source_receipts, root=ROOT):
    """Common V5/external adapter. Assets=(graph,scores); gold is separate.

    ``references`` maps dataset to label->complete reference. It is written only
    to evaluator_inputs. No reference or path to its contents enters the visible
    manifest. Supplied replay must contain the V5 visible-replay structure.
    """
    import numpy as np
    from scripts.review_v4.replay import observable
    out, root = Path(out).resolve(), Path(root).resolve()
    s.require(out.is_relative_to(root) and not out.exists(), "Fresh contained input directory required")
    s.require(source_receipts and isinstance(source_receipts, dict), "Source receipts required")
    s.check_hashes(root, source_receipts)
    visible, evaluator = out / "visible_inputs", out / "evaluator_inputs"
    visible.mkdir(parents=True); evaluator.mkdir()
    asset_map, reference_map = {}, {}
    for name, (graph, scores) in assets.items():
        s.require(name.replace("_", "").isalnum(), "Unsafe dataset name")
        folder = visible / "assets" / name
        folder.mkdir(parents=True)
        s.write(folder / "observable.json", observable(graph, scores))
        np.save(folder / "scores.npy", scores.matrix, allow_pickle=False)
        asset_map[name] = {"observable": f"assets/{name}/observable.json", "scores": f"assets/{name}/scores.npy"}
        reference_map[name] = {}
        for label, reference in references[name].items():
            s.require(label.replace("_", "").isalnum() and set(reference) == set(graph), "Reference name/membership mismatch")
            refpath = evaluator / name / (label + ".json")
            s.write(refpath, {"reference": reference, "offline_evaluator_only": True})
            reference_map[name][label] = refpath.relative_to(evaluator).as_posix()
    jobs, seen = [], set()
    dataset_order = ["wdc", "dblp_acm", "dblp_unused"] + [f"k{k}_{profile}" for k in (1, 2, 3) for profile in ("uniform", "ranked")]
    phases = {"natural": 0, "synthetic": 1, "external": 2}
    def order(replay):
        dataset = replay["dataset"]
        return (phases[replay["phase"]], replay["budget"],
                dataset_order.index(dataset) if dataset in dataset_order else len(dataset_order), replay["run_id"])
    for replay in sorted(replays, key=order):
        s.require(replay["method"] == FULL and replay["dataset"] in assets, "Only Full saved states admitted")
        runid = replay["run_id"]
        s.require(runid.replace("_", "").isalnum() and runid not in seen, "Duplicate/unsafe run id")
        seen.add(runid)
        # Only observable fields survive. acquisition_reference, endpoints and
        # evaluator annotations are deliberately not copied.
        fields = ("run_id", "dataset", "method", "budget", "phase", "complete", "batches", "events", "states", "stop_reason", "logical_score_accesses")
        clean = {key: replay[key] for key in fields}
        rp = visible / "replays" / (runid + ".json")
        s.write(rp, clean)
        for batch in clean["batches"]:
            phase = replay["phase"]
            s.require(phase in ("synthetic", "natural", "external"), "Unknown evidence phase")
            jobs.append({"id": runid + "_state" + str(batch["batch"]).zfill(3), "run_id": runid,
                         "dataset": replay["dataset"], "budget": replay["budget"], "batch": batch["batch"],
                         "phase": phase, "replay": rp.relative_to(visible).as_posix(),
                         "cohort": "synthetic" if phase == "synthetic" else replay["dataset"],
                         "worker_seconds": 30 if phase == "synthetic" else 120,
                         "suite_seconds": 900 if phase == "synthetic" else 2700})
    pins = code_pins(root)
    validate_jobs(jobs)
    vm = {"schema": "cut-audit-v6-visible-inputs-v1", "created_utc": s.utc(), "assets": asset_map,
          "jobs": jobs, "code_sha256": pins, "source_receipts": source_receipts,
          "contains_evaluator_reference": False, "new_oracle_answers": 0,
          "order": "natural_then_synthetic_then_external; within_phase_budget_then_original_dataset_or_condition_order_then_batch",
          "files_sha256": {p.relative_to(visible).as_posix(): s.digest(p) for p in visible.rglob("*") if p.is_file()}}
    s.write(visible / "manifest.json", vm)
    em = {"schema": "cut-audit-v6-evaluator-inputs-v1", "references": reference_map,
          "visible_input_manifest_sha256": s.digest(visible / "manifest.json"), "code_sha256": pins,
          "files_sha256": {p.relative_to(evaluator).as_posix(): s.digest(p) for p in evaluator.rglob("*") if p.is_file()}}
    s.write(evaluator / "manifest.json", em)
    return {"visible_manifest": str(visible / "manifest.json"), "visible_sha256": s.digest(visible / "manifest.json"),
            "evaluator_manifest": str(evaluator / "manifest.json"), "evaluator_sha256": s.digest(evaluator / "manifest.json"),
            "states": len(jobs), "phase_counts": dict(Counter(j["phase"] for j in jobs))}


def prepare_v5(out, source_freeze_sha256, *, root=ROOT):
    root = Path(root)
    freeze_path = root / s.SESSION / "freeze.json"
    s.require(s.digest(freeze_path) == source_freeze_sha256, "V5 source freeze hash mismatch")
    frozen, snapshot = s.checked_freeze(root)
    assets, refs, replays = {}, {}, []
    sources = {freeze_path.relative_to(root).as_posix(): source_freeze_sha256}
    for phase in ("natural", "synthetic"):
        analysis = root / s.SESSION / phase / "analysis"
        manifest = s.read(analysis / "manifest.json")
        s.require(manifest["status"] == "passed", "V5 replay analysis must pass")
        s.check_hashes(analysis, manifest["files_sha256"])
        sources[(analysis / "manifest.json").relative_to(root).as_posix()] = s.digest(analysis / "manifest.json")
        for name, (graph, scores, _) in s.load_phase_assets(snapshot, phase, include_truth=False).items():
            assets[name] = (graph, scores)
            refs[name] = ({label: s.read(snapshot / f"inputs/synthetic/{label}.json")["reference"] for label in ("H0", "H9")}
                          if phase == "synthetic" else {"natural": s.read(snapshot / f"inputs/natural/{name}/evaluator_reference.json")["reference"]})
        for path in sorted((analysis / "replays").glob("*.json")):
            replay = s.read(path)
            if replay["method"] == FULL:
                replays.append(replay)
                sources[path.relative_to(root).as_posix()] = s.digest(path)
    counts = Counter(r["phase"] for r in replays for _ in r["batches"])
    s.require(counts == {"natural": 241, "synthetic": 60}, "Fixed V5 Full state scope differs")
    return prepare_inputs(out, assets, replays, refs, source_receipts=sources, root=root)


def restore_job(manifest, base, job):
    import numpy as np
    from scripts.review_v4.replay import graph_from_observable
    asset = manifest["assets"][job["dataset"]]
    needed = (asset["observable"], asset["scores"], job["replay"])
    s.check_hashes(base, {name: manifest["files_sha256"][name] for name in needed})
    graph, scores = graph_from_observable(s.read(base / asset["observable"]), np.load(base / asset["scores"], allow_pickle=False))
    # Match V5 visible_replay's explicit initial copy. On undirected graphs,
    # copying can alter adjacency insertion order even with identical topology.
    graph = graph.copy()
    replay = s.read(base / job["replay"])
    batches = replay["batches"]
    s.require([b["batch"] for b in batches] == list(range(1, len(batches) + 1)), "Missing/reordered recorded batch")
    batch = next(b for b in batches if b["batch"] == job["batch"])
    history = []
    for index, event in enumerate(replay["events"], 1):
        s.require(event["spent"] == index, "Paid-event sequence gap")
        if event["spent"] > batch["spent_before"]:
            break
        pair = tuple(event["pair"])
        s.require(type(event["answer"]) is bool and graph.has_edge(*pair), "Invalid saved paid event")
        history.append({"pair": list(pair), "answer": event["answer"]})
        if not event["answer"]:
            graph.remove_edge(*pair)
    identity = hashlib.sha256(s.blob({name: manifest["files_sha256"][name] for name in (asset["observable"], asset["scores"])})).hexdigest()
    return graph, scores, batch, history, identity


def worker_visible(manifest_path, expected, job_id, out):
    from scripts.review_v6.audit import audit_visible_state
    manifest_path = Path(manifest_path)
    manifest = checked_manifest(manifest_path, expected, all_files=False)
    job = next(j for j in manifest["jobs"] if j["id"] == job_id)
    graph, scores, batch, history, identity = restore_job(manifest, manifest_path.parent, job)
    result = audit_visible_state(graph, scores, batch, history, source_identity=identity)
    result["job"] = job
    s.write(out, result)


def worker_evaluate(visible_path, visible_hash, references_path, reference_hash, job_id, out):
    from scripts.review_v6.audit import evaluate_visible_state
    vm = checked_manifest(visible_path, visible_hash, all_files=False)
    em = checked_manifest(references_path, reference_hash, all_files=False)
    job = next(j for j in vm["rows"] if j["id"] == job_id)
    rel = job["result_file"]
    base = Path(visible_path).parent
    s.check_hashes(base, {rel: vm["files_sha256"][rel]})
    visible = s.read(base / rel)
    results = {}
    for label, refname in em["references"][job["dataset"]].items():
        s.check_hashes(Path(references_path).parent, {refname: em["files_sha256"][refname]})
        reference = s.read(Path(references_path).parent / refname)["reference"]
        results[label] = evaluate_visible_state(visible, reference)
    s.write(out, {"schema": "cut-audit-v6-evaluated-state-v1", "job": {k: visible["job"][k] for k in visible["job"]}, "references": results})


def run_process(command, folder, limit):
    """Result deadline with explicitly measured startup/wait/cleanup overhead."""
    folder.mkdir(parents=True)
    start = time.perf_counter()
    env = os.environ.copy(); env.update(ENV); env["PYTHONIOENCODING"] = "utf-8"
    with (folder / "stdout.txt").open("x", encoding="utf-8") as stdout, (folder / "stderr.txt").open("x", encoding="utf-8") as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
        startup = time.perf_counter() - start
        wait_start = time.perf_counter(); timed_out = False; interrupted = False
        try:
            code = child.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True; code = 124
        except KeyboardInterrupt:
            interrupted = True; code = 130
        result_wait = time.perf_counter() - wait_start
        cleanup = time.perf_counter()
        if timed_out or interrupted:
            child.kill(); child.wait(timeout=10)
        cleanup = time.perf_counter() - cleanup
    return {"command": command, "exit_code": code, "timed_out": timed_out, "interrupted": interrupted,
            "startup_seconds": startup, "result_wait_seconds": result_wait,
            "cleanup_seconds": cleanup, "wall_seconds": time.perf_counter() - start,
            "worker_result_limit_seconds": limit, "strict_OS_wall_guarantee": False}


def run_suite(stage, source, source_hash, out, *, reference_manifest=None, reference_hash=None):
    stage_started = time.perf_counter()
    source, out = Path(source).resolve(), Path(out).resolve()
    manifest = checked_manifest(source, source_hash)
    s.require(out.is_relative_to(ROOT) and not out.exists(), "Fresh contained diagnostic output required")
    s.require(stage in ("visible", "evaluate"), "Unknown diagnostic stage")
    if stage == "visible":
        s.require(manifest["schema"] == "cut-audit-v6-visible-inputs-v1", "Wrong visible input schema")
        jobs = manifest["jobs"]
        charged = {j["cohort"]: 0. for j in jobs}
        consumed = source.parent / "consumed_visible.json"
    else:
        s.require(manifest["schema"] == "cut-audit-v6-visible-suite-v1", "Wrong visible suite schema")
        em = checked_manifest(reference_manifest, reference_hash)
        s.require(em["visible_input_manifest_sha256"] == manifest["source_manifest_sha256"], "Evaluator/visible provenance mismatch")
        jobs = manifest["rows"]
        charged = dict(manifest["cohort_charged_seconds"])
        consumed = Path(reference_manifest).parent / "consumed_evaluator.json"
    validate_jobs(jobs)
    s.require(not consumed.exists(), "This fixed diagnostic input/stage was already consumed; no retry")
    out.mkdir(parents=True)
    s.write(consumed, {"stage": stage, "source_sha256": source_hash, "started_utc": s.utc(), "out": str(out)})
    rows, mismatch = [], []
    initialization_seconds = time.perf_counter() - stage_started
    stopped_by_interruption = False
    for job in jobs:
        state_started = time.perf_counter()
        # A fresh immutable launch entry precedes every worker. If the parent is
        # interrupted, consumed marker forbids silently retrying this stage.
        row = {k: job[k] for k in ("id", "run_id", "dataset", "budget", "batch", "phase", "cohort", "worker_seconds", "suite_seconds")}
        cohort = job["cohort"]
        residual = max(0., job["suite_seconds"] - charged[cohort])
        if stopped_by_interruption:
            row.update(status="not_started_interrupted_suite", result_file=None)
        elif stage == "evaluate" and job["status"] != "passed":
            row.update(status="unknown_visible_not_completed", result_file=None)
        elif residual <= 0:
            row.update(status="not_started_suite_limit", result_file=None)
        else:
            result_rel = "states/" + job["id"] + ".json"
            result_path = out / result_rel
            limit = min(job["worker_seconds"], residual)
            s.write(out / "ledger" / (str(len(rows)).zfill(6) + "_launch.json"),
                    {"job": row, "remaining_suite_seconds": residual, "limit_seconds": limit, "utc": s.utc()})
            command = [sys.executable, "-m", "scripts.review_v6.audit_runner", "_" + stage,
                       "--manifest", str(source), "--manifest-sha256", source_hash,
                       "--job", job["id"], "--out", str(result_path)]
            if stage == "evaluate":
                command += ["--references", str(reference_manifest), "--references-sha256", reference_hash]
            # Launch preparation consumes the same allowance. Startup and
            # cleanup may still exceed the result wait; this is not an OS clock.
            limit = min(job["worker_seconds"], max(0., residual - (time.perf_counter() - state_started)))
            if limit <= 0:
                receipt = {"exit_code": None, "timed_out": False, "wall_seconds": 0., "not_launched_after_preparation": True}
            else:
                try:
                    receipt = run_process(command, out / "commands" / job["id"], limit)
                except KeyboardInterrupt:
                    receipt = {"exit_code": 130, "timed_out": False, "interrupted": True, "wall_seconds": 0.}
                except Exception as error:
                    receipt = {"exit_code": 2, "timed_out": False, "wall_seconds": 0., "launcher_error": repr(error)}
            if receipt.get("not_launched_after_preparation"):
                status = "not_started_suite_limit"
            elif receipt.get("interrupted"):
                status = "interrupted_unknown"
                stopped_by_interruption = True
            elif receipt["timed_out"]:
                status = "timeout_unknown"
            elif receipt["exit_code"] or not result_path.is_file():
                status = "technical_error"
                mismatch.append({"id": job["id"], "phase": job["phase"], "exit_code": receipt["exit_code"],
                                 "stderr": "commands/" + job["id"] + "/stderr.txt"})
            else:
                status = "passed"
            row.update(status=status, result_file=result_rel if status == "passed" else None, **receipt)
        rows.append(row)
        s.write(out / "ledger" / (str(len(rows) - 1).zfill(6) + "_result.json"), row)
        # Includes preparation, worker startup/wait/cleanup, and the completed
        # result-ledger write. Stage-wide verification/export are reported below.
        row["state_charged_seconds"] = time.perf_counter() - state_started
        charged[cohort] += row["state_charged_seconds"]
    finalization_started = time.perf_counter()
    try:
        s.check_hashes(ROOT, manifest["code_sha256"])
        s.check_hashes(source.parent, manifest["files_sha256"])
    except Exception as error:
        mismatch.append({"id": "final_source_integrity", "error": repr(error)})
    csv_write(out / "states.csv", rows)
    summaries, candidate_rows, component_rows = [], [], []
    for row in rows:
        if row["status"] != "passed":
            continue
        data = s.read(out / row["result_file"])
        meta = {k: row[k] for k in ("id", "run_id", "dataset", "budget", "batch", "phase")}
        if stage == "visible":
            keys = ("state_sha256", "certificate_status", "certificate_for_selected_positive", "pool_argmax_certified", "searched_pool_complete_audit", "graph_wide_bonds_complete", "pool_max_proxy", "selected_proxy", "max_unscored_upper_bound", "strict_margin", "scored_count", "pool_count", "diagnostic_score_accesses", "diagnostic_seconds", "fallback")
            summaries.append(meta | {k: data[k] for k in keys})
        else:
            for label, result in data["references"].items():
                key = meta | {"reference": label, "state_sha256": result["state_sha256"]}
                summaries.append(key | {k: result[k] for k in ("status", "fallback", "selected_positive_certificate", "single_batch_oracle_gap", "gap_fraction", "gap_scope", "best_known_gain_per_query", "covered_fp", "total_fp", "fp_coverage", "zero_fp_denominator", "candidate_occurrences", "offline_seconds")}
                                 | {"selected_" + k: v for k, v in result["selected"].items() if k != "after"})
                candidate_rows.extend(key | candidate for candidate in result["candidates"])
                component_rows.extend(key | component for component in result["components"])
    csv_write(out / "summary.csv", summaries)
    if stage == "evaluate":
        csv_write(out / "candidates.csv", candidate_rows); csv_write(out / "components.csv", component_rows)
    unique = {}
    for row in summaries:
        key = (row["state_sha256"], row.get("reference"))
        if key not in unique:
            unique[key] = {**row, "occurrences": 0}
        unique[key]["occurrences"] += 1
    csv_write(out / "unique_states.csv", list(unique.values()))
    unknown = sum(r["status"] != "passed" and r["status"] != "technical_error" for r in rows)
    report = {"schema": "cut-audit-v6-" + ("visible" if stage == "visible" else "evaluator") + "-suite-v1",
              "status": "failed" if mismatch else "completed_with_unknown" if unknown else "passed",
              "stage": stage, "source_manifest_sha256": source_hash, "rows": rows,
              "planned_states": len(jobs), "completed_states": sum(r["status"] == "passed" for r in rows),
              "unknown_states": unknown, "technical_mismatch_count": len(mismatch), "technical_mismatches": mismatch,
              "cohort_charged_seconds": charged, "time_budget_includes_prior_visible_stage": stage == "evaluate",
              "state_budget_scope": "entire state loop through result-ledger close, including launch, IPC/result wait and cleanup",
              "stage_initialization_outside_cohort_budget_seconds": initialization_seconds,
              "stage_finalization_through_payload_hashing_outside_cohort_budget_seconds": None,
              "phase_counts": dict(Counter(r["phase"] for r in rows)), "reference_state_rows": len(summaries) if stage == "evaluate" else None,
              "unique_state_rows": len(unique), "new_oracle_answers": 0, "selector_score_accesses": 0,
              "code_sha256": manifest["code_sha256"],
              "files_sha256": {p.relative_to(out).as_posix(): s.digest(p) for p in sorted(out.rglob("*")) if p.is_file()}}
    report["stage_finalization_through_payload_hashing_outside_cohort_budget_seconds"] = time.perf_counter() - finalization_started
    report["stage_wall_through_manifest_serialization_start_seconds"] = time.perf_counter() - stage_started
    if stage == "evaluate":
        report.update(reference_manifest_sha256=reference_hash, visible_input_manifest_sha256=manifest["source_manifest_sha256"])
    s.write(out / "manifest.json", report)
    return {k: v for k, v in report.items() if k not in ("rows", "files_sha256", "code_sha256", "technical_mismatches")}


def make_gate(root, method_freeze_sha256, visible, evaluator, out):
    """Recheck fixed 301-state audit scope and evidence; unknown is not failure."""
    root, visible, evaluator, out = map(Path, (root, visible, evaluator, out))
    reports = [checked_manifest(path, s.digest(path), root=root) for path in (visible, evaluator)]
    vm, em = reports
    s.require(vm["schema"] == "cut-audit-v6-visible-suite-v1" and em["schema"] == "cut-audit-v6-evaluator-suite-v1", "Gate scope schema mismatch")
    s.require(em["source_manifest_sha256"] == s.digest(visible), "Gate evaluator does not bind visible audit")
    s.require(all(r["planned_states"] == 301 and r["phase_counts"] == {"natural": 241, "synthetic": 60} for r in reports), "Gate lacks full fixed audit scope")
    for report in reports:
        validate_jobs(report["rows"])
        s.require(len(report["rows"]) == 301 and Counter(r["phase"] for r in report["rows"]) == {"natural": 241, "synthetic": 60}, "Gate declared/actual state scope differs")
        s.require(report["technical_mismatch_count"] == len(report["technical_mismatches"])
                  >= sum(r["status"] == "technical_error" for r in report["rows"]), "Gate technical error accounting differs")
    technical = sum(r["technical_mismatch_count"] for r in reports)
    report = {"schema": "cut-audit-v6-audit-gate-v1", "status": "passed" if technical == 0 else "blocked_technical_mismatch",
              "eligible": technical == 0, "method_freeze_sha256": method_freeze_sha256,
              "audit_manifests_sha256": {p.resolve().relative_to(root.resolve()).as_posix(): s.digest(p) for p in (visible, evaluator)},
              "scopes_finalized": True, "mismatches": technical, "technical_errors": technical,
              "timeout_unknown_states": vm["unknown_states"] + em["unknown_states"],
              "technical_mismatch_count": technical, "technical_error_count": technical,
              "planned_visible_states": 301, "natural_states": 241, "synthetic_states": 60,
              "completed_visible_states": vm["completed_states"], "completed_evaluator_states": em["completed_states"],
              "unknown_visible_states": vm["unknown_states"], "unknown_evaluator_states": em["unknown_states"],
              "rule": "No technical/certificate/trace mismatch in the complete fixed audit slot list; timeouts are unknown, not favourable evidence",
              "new_oracle_answers": 0, "V5_method_progression_gate_changed": False}
    s.write(out, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare-v5", "visible", "evaluate", "_visible", "_evaluate"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--references", type=Path)
    parser.add_argument("--references-sha256")
    parser.add_argument("--source-freeze-sha256")
    parser.add_argument("--job")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare-v5":
        result = prepare_v5(args.out, args.source_freeze_sha256)
    elif args.command == "_visible":
        worker_visible(args.manifest, args.manifest_sha256, args.job, args.out); result = {"status": "passed"}
    elif args.command == "_evaluate":
        worker_evaluate(args.manifest, args.manifest_sha256, args.references, args.references_sha256, args.job, args.out); result = {"status": "passed"}
    else:
        result = run_suite(args.command, args.manifest, args.manifest_sha256, args.out,
                           reference_manifest=args.references, reference_hash=args.references_sha256)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("status") != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
