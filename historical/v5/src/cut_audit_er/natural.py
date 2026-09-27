"""Checkpointed CPU development suite. Never evaluates the held-out test split."""
from __future__ import annotations
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import shutil
import time
import traceback

from .audit import run_audit
from .data import load_csv, entity_splits, split_manifest
from .experiment import metadata, save_runs
from .guard import protocol_hash
from .matcher import PairMatcher
from .policy_score_sensitivity import transform_policy_scores
from .telemetry import AuditJournal, recover_journal, validate_identity


def extra_freeze_matches(root: Path, cfg: dict) -> bool:
    """Bind optional development methodology files without changing test approval."""
    root = root.resolve()
    for relative, expected in cfg.get('additional_frozen_files', {}).items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            raise ValueError('Additional freeze path must stay inside repository') from None
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            return False
    return True


def _worker(connection, arguments, journal_spec=None):
    try:
        if journal_spec is None:
            run = run_audit(**arguments)
        else:
            with AuditJournal(Path(journal_spec["path"]), journal_spec["identity"]) as journal:
                run = run_audit(**arguments, checkpoint_callback=journal)
        connection.send({"status": "completed", "run": run})
    except Exception:
        connection.send({"status": "failed", "error": traceback.format_exc()})
    finally:
        connection.close()


def bounded_audit(arguments, seconds, journal_path=None, journal_identity=None):
    """Requested result deadline with measured phases and bounded cleanup joins.

    Process.start() and Connection.recv() are synchronous and may themselves
    block; this is not a guaranteed upper bound on observed hardware wall time.
    """
    journal_spec = None
    if journal_path is not None:
        validate_identity(journal_identity)
        if (journal_identity["requested_budget"] != arguments.get("budget") or
                journal_identity["method"] != arguments.get("method") or
                "checkpoint_callback" in arguments):
            raise ValueError("Journal identity differs from worker arguments or callback already supplied")
        journal_path = Path(journal_path)
        if journal_path.exists():
            raise FileExistsError("Use a fresh journal path; previous evidence is never overwritten")
        journal_spec = {"path": str(journal_path), "identity": journal_identity}
    elif journal_identity is not None:
        raise ValueError("A journal identity requires a journal path")
    context = mp.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    child = context.Process(target=_worker, args=(sending, arguments) if journal_spec is None else
                            (sending, arguments, journal_spec))
    start = time.perf_counter()
    phases={"process_start_seconds":0.,"result_wait_seconds":0.,
            "payload_receive_seconds":0.,"cleanup_seconds":0.}
    result={"status":"failed","error":"Worker did not start"}
    started=False
    try:
        child.start();started=True
        phases["process_start_seconds"]=time.perf_counter()-start
        sending.close()
        waiting=time.perf_counter()
        available=receiving.poll(max(0, seconds-(waiting-start)))
        phases["result_wait_seconds"]=time.perf_counter()-waiting
        if available:
            receiving_start=time.perf_counter()
            try:
                result = receiving.recv()
            except (EOFError,OSError):
                result = {"status": "failed", "error": "Worker result transfer failed: "+traceback.format_exc()}
            finally:
                phases["payload_receive_seconds"]=time.perf_counter()-receiving_start
        else:
            result = {"status": "timeout", "error": f"Requested worker-result deadline {seconds}s expired; no complete outcome"}
    except Exception:
        if not started:phases["process_start_seconds"]=time.perf_counter()-start
        result={"status":"failed","error":traceback.format_exc()}
    finally:
        cleaning=time.perf_counter()
        sending.close()
        if started:
            if result["status"] == "completed":
                child.join(timeout=1)
            if child.is_alive():
                child.terminate()
                child.join(timeout=1)
            if child.is_alive():
                child.kill()
                child.join(timeout=1)
        still_alive=started and child.is_alive()
        receiving.close()
        phases["cleanup_seconds"]=time.perf_counter()-cleaning
    if still_alive:
        result={**result,"status":"cleanup_failed","previous_status":result["status"],
                "error":"Worker remains alive after terminate/kill and bounded cleanup joins"}
    result["worker_exit_code"] = child.exitcode if started else None
    result["worker_pid"] = child.pid if started else None
    result["worker_wall_seconds"] = time.perf_counter()-start
    result["worker_timing"] = phases
    result["requested_result_deadline_seconds"] = seconds
    result["observed_wall_exceeded_requested_deadline"] = result["worker_wall_seconds"]>seconds
    result["cleanup_worker_still_alive"] = still_alive
    result["deadline_scope"] = "result wait after synchronous start; start/payload receive may block; cleanup joins bounded to one second each"
    if journal_spec is not None:
        if still_alive:
            recovery = {"journal_status": "worker_not_stopped", "completed_result_available": False,
                        "paid_count_lower_bound": None, "paid_count_upper_bound": None}
        else:
            try:
                recovery = recover_journal(journal_path, journal_identity)
            except (OSError, ValueError, TypeError) as exc:
                recovery = {"journal_status": "invalid_journal", "completed_result_available": False,
                            "paid_count_lower_bound": None, "paid_count_upper_bound": None,
                            "error": f"{type(exc).__name__}: {exc}"}
        # Recovery is independent evidence. Never change a timeout into success,
        # even when a terminal marker was flushed just before result transfer.
        result["checkpoint_telemetry"] = recovery
    return result


def run_natural_suite(root: Path, cfg: dict, out: Path, resume_from: Path|None=None):
    if cfg.get("phase") != "development":
        raise ValueError("This runner is development only; no held-out evaluation")
    telemetry_enabled = cfg.get("checkpoint_telemetry", False)
    if type(telemetry_enabled) is not bool:
        raise ValueError("checkpoint_telemetry must be an explicit boolean")
    out.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    frozen_hash = protocol_hash(root)
    if not extra_freeze_matches(root, cfg):
        raise ValueError('Additional development methodology freeze mismatch')
    base = metadata(root, cfg)
    source_manifest = {}
    for folder in ("src", "configs", "scripts", "tests", "research"):
        for source in (root / folder).rglob("*"):
            if source.is_file() and source.suffix in (".py", ".json", ".md") and "literature" not in source.parts:
                relative = source.relative_to(root)
                destination = out / "source_snapshot" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                source_manifest[relative.as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    (out / "source_manifest.json").write_text(json.dumps(source_manifest, indent=2)+"\n", encoding="utf-8")
    inherited = []
    if resume_from is not None:
        previous = json.loads(resume_from.read_text(encoding="utf-8"))
        if (previous["metadata"]["protocol_sha256"] != frozen_hash or
                previous["metadata"]["config_sha256"] != base["config_sha256"]):
            raise ValueError("Resume requires identical frozen source/protocol and config")
        inherited = previous["records"]
    ledger = {"metadata": base, "records": list(inherited), "status": "running",
              "resume_from": str(resume_from) if resume_from else None}
    attempted = {(r["dataset"],r["seed"],r.get("setting_index"),r.get("method")) for r in inherited}

    def checkpoint():
        ledger["elapsed_seconds"] = time.perf_counter()-start
        (out / "suite.json").write_text(json.dumps(ledger, indent=2)+"\n", encoding="utf-8")

    checkpoint()
    for dataset in cfg["datasets"]:
        path = root / dataset["input"]
        provenance = json.loads((root / dataset["provenance"]).read_text(encoding="utf-8"))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if provenance.get("normalized_sha256") != digest:
            raise ValueError("Normalized dataset hash does not match provenance")
        frame = load_csv(path)
        if len(frame) > 4000:
            raise ValueError("Dense input cap exceeded")
        for seed in cfg["seeds"]:
            if ((dataset["name"],seed,None,None) in attempted or
                    all((dataset["name"],seed,i,m) in attempted
                        for i in range(len(cfg["settings"])) for m in cfg["methods"])):
                continue
            fitting_start = time.perf_counter()
            try:
                splits = entity_splits(frame, seed, holdout_seed=cfg.get("holdout_seed", 7))
                for split in ("train", "calibration", "development"):
                    if len(splits[split]) > 1500:
                        raise ValueError(f"{split} split exceeds dense cap")
                matcher = PairMatcher(seed, max_pairs=cfg.get("matcher_max_pairs", 50000), matcher_variant=cfg.get("matcher_variant", "char4")).fit(splits["train"], splits["calibration"])
            except Exception:
                ledger["records"].append({"dataset": dataset["name"], "seed": seed,
                    "status": "matcher_failed", "error": traceback.format_exc()})
                checkpoint()
                continue
            fit_seconds = time.perf_counter()-fitting_start
            target = splits["development"]
            truth = dict(zip(target.record_id, target.entity_id))
            for setting_index, setting in enumerate(cfg["settings"]):
                graph_start = time.perf_counter()
                graph, scores, diagnostics = matcher.graph_for(
                    target, setting["threshold"], setting["top_k"])
                graph_seconds = time.perf_counter()-graph_start
                score_mode = setting.get("policy_score_mode", "all_pair")
                score_temperature = setting.get("policy_score_temperature", 1.0)
                policy_graph, policy_scores, policy_score_info = graph, scores, None
                try:
                    if score_mode != "all_pair" or score_temperature != 1.0:
                        policy_scores, policy_score_info = transform_policy_scores(
                            graph, scores, mode=score_mode, temperature=score_temperature)
                        attribute_start = time.perf_counter()
                        policy_graph = graph.copy()
                        for u, v in policy_graph.edges:
                            i, j = policy_scores.index[u], policy_scores.index[v]
                            policy_graph.edges[u, v]["p"] = float(policy_scores.matrix[i, j])
                        policy_score_info["graph_copy_and_attribute_seconds"] = time.perf_counter()-attribute_start
                        policy_score_info["transformed_edge_attribute_reads"] = policy_graph.number_of_edges()
                        policy_score_info["shared_preprocessing_scope"] = "once per dataset/seed/setting, shared across policies"
                        if set(policy_graph) != set(graph) or set(policy_graph.edges) != set(graph.edges):
                            raise AssertionError("Policy-score stress changed graph topology")
                except Exception:
                    error = traceback.format_exc()
                    for method in cfg["methods"]:
                        if (dataset["name"],seed,setting_index,method) not in attempted:
                            ledger["records"].append({"dataset":dataset["name"], "seed":seed,
                                "setting_index":setting_index, "setting":setting, "method":method,
                                "status":"score_preprocessing_failed", "error":error,
                                "study_kind":cfg.get("study_kind", "observed_matcher_errors"),
                                "policy_score_transform":policy_score_info})
                    checkpoint()
                    continue
                original_graph_fingerprint = hashlib.sha256(json.dumps({
                    "nodes": sorted(graph),
                    "edges": sorted((min(u,v),max(u,v),float(a["p"])) for u,v,a in graph.edges(data=True))
                }, sort_keys=True).encode()).hexdigest()
                original_topology_fingerprint = hashlib.sha256(json.dumps({
                    "nodes":sorted(graph), "edges":sorted(tuple(sorted(e)) for e in graph.edges)
                }, sort_keys=True).encode()).hexdigest()
                original_edge_probability_fingerprint = hashlib.sha256(json.dumps(
                    sorted((min(u,v),max(u,v),float(a["p"])) for u,v,a in graph.edges(data=True))
                ).encode()).hexdigest()
                for method in cfg["methods"]:
                    if (dataset["name"],seed,setting_index,method) in attempted:
                        continue  # Retain failed/timeout attempts too; no favorable reruns.
                    if time.perf_counter()-start >= cfg.get("max_wall_seconds", 1800):
                        ledger["status"] = "suite_time_limit_incomplete"
                        checkpoint()
                        return ledger
                    if protocol_hash(root) != frozen_hash or not extra_freeze_matches(root, cfg):
                        ledger["status"] = "source_changed_incomplete"
                        checkpoint()
                        raise RuntimeError("Protected source changed during suite")
                    args = dict(g=policy_graph, scores=policy_scores, truth=truth, method=method,
                        budget=setting.get("budget", cfg["budget"]), seed=seed,
                        noise=setting.get("oracle_noise", 0),
                        fn_weight=setting.get("fn_weight", 1),
                        max_width=setting.get("max_width", 2),
                        shortlist=setting.get("shortlist", 24),
                        match_threshold=setting["threshold"])
                    destination = out / dataset["name"] / f"seed_{seed}" / f"setting_{setting_index:02d}" / method
                    if telemetry_enabled:
                        journal_identity = {"method": method, "requested_budget": args["budget"],
                            "seed": seed, "noise": args["noise"], "fn_weight": args["fn_weight"],
                            "dataset": dataset["name"], "setting_index": setting_index,
                            "run_settings": setting, "input_sha256": digest,
                            "protocol_sha256": frozen_hash, "config_sha256": base["config_sha256"],
                            "original_graph_fingerprint_sha256": original_graph_fingerprint}
                        journal_path = destination / "answers.jsonl"
                        result = bounded_audit(args, cfg.get("per_policy_seconds", 45),
                                               journal_path, journal_identity)
                        progress = result["checkpoint_telemetry"]
                        if result["status"] != "completed":
                            destination.mkdir(parents=True, exist_ok=True)
                            partial_path = destination / "partial.json"
                            with partial_path.open("x", encoding="utf-8") as handle:
                                json.dump({"not_a_completed_run": True, "worker_status": result["status"],
                                           "identity": journal_identity, "progress": progress}, handle,
                                          indent=2, allow_nan=False)
                                handle.write("\n")
                        result["checkpoint_telemetry"] = {
                            k:v for k,v in progress.items() if k not in ("decisions", "trace")}
                        result["checkpoint_telemetry"]["journal_path"] = journal_path.relative_to(root).as_posix()
                        if result["status"] != "completed":
                            result["checkpoint_telemetry"]["partial_path"] = partial_path.relative_to(root).as_posix()
                    else:
                        result = bounded_audit(args, cfg.get("per_policy_seconds", 45))
                    if protocol_hash(root) != frozen_hash or not extra_freeze_matches(root, cfg):
                        ledger["status"] = "source_changed_incomplete"
                        checkpoint()
                        raise RuntimeError("Protected source changed during policy execution")
                    record = {"dataset": dataset["name"], "seed": seed,
                        "setting_index": setting_index, "setting": setting,
                        "method": method, "study_kind":cfg.get("study_kind", "observed_matcher_errors"),
                        "policy_score_transform":policy_score_info,
                        **{k:v for k,v in result.items() if k != "run"}}
                    if result["status"] == "completed":
                        run = result["run"]
                        run.update(dataset=dataset["name"], regime="observed_matcher_errors")
                        if policy_score_info is not None:
                            run["study_kind"] = "heuristic_policy_score_perturbation_stress"
                            run["policy_score_preprocessing_pair_accesses"] = policy_score_info["preprocessing_pair_score_accesses"]
                            run["policy_graph_attribute_score_reads"] = policy_score_info["transformed_edge_attribute_reads"]
                            run["standalone_score_accesses_including_preprocessing"] = (
                                run["score_accesses"] + run["policy_score_preprocessing_pair_accesses"]
                                + run["policy_graph_attribute_score_reads"])
                            run["policy_score_preprocessing_seconds"] = (
                                policy_score_info["preprocessing_seconds"]
                                + policy_score_info["graph_copy_and_attribute_seconds"])
                        meta = base | {"phase": "development", "data_kind": "real",
                            "input_sha256": digest, "provenance": provenance,
                            "splits": split_manifest(splits), "matcher_diagnostics": diagnostics,
                            "matcher_variant": matcher.matcher_variant,
                            "study_kind":cfg.get("study_kind", "observed_matcher_errors"),
                            "policy_score_transform":policy_score_info,
                            "original_graph_fingerprint_sha256":original_graph_fingerprint,
                            "original_topology_sha256":original_topology_fingerprint,
                            "original_edge_probability_sha256":original_edge_probability_fingerprint,
                            "run_settings": {**setting, "seed": seed, "method": method,
                                             "budget": args["budget"]},
                            "shared_fit_seconds": fit_seconds, "graph_seconds": graph_seconds,
                            "worker_wall_seconds": result["worker_wall_seconds"]}
                        save_runs(destination, [run], meta)
                        record["result_path"] = destination.relative_to(root).as_posix()
                    ledger["records"].append(record)
                    checkpoint()
                    print(json.dumps({k:record[k] for k in ("dataset", "seed", "setting_index", "method", "status")}), flush=True)
    ledger["status"] = "completed_with_failures" if any(r["status"] != "completed" for r in ledger["records"]) else "completed"
    checkpoint()
    return ledger
