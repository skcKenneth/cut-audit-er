"""Independently check sanitized arithmetic, completeness and source hashes.

This validates the public projection, not hidden pair identities, graph truth,
the offline optimizer or a rerun of selector experiments.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re

try:
    from .schema import BUDGETS, DATASETS, METHODS, SCHEMAS, STAGES, load_evidence, ratio, sha256
except ImportError:
    from schema import BUDGETS, DATASETS, METHODS, SCHEMAS, STAGES, load_evidence, ratio, sha256

SCHEMA = "cut-audit-public-evidence-v3"
PROVENANCE = "private_pair_audit_not_recomputable_from_public_rows"
SOURCE_HASH = "b19bb2499f28a014b7a83404fff431d5592537577802133b13e192d7121643aa"
SCOPE = "exposed_development_projection_no_new_experiments"
CACHE_NAMES = {"original_centrality", "centrality", "canonical", "bonds", "bridges",
               "component_graph", "component_partition", "seed_bridges"}
HISTORICAL_SCOPES = {
    "historical_primary_cell": "missing_matched_historical_comparison",
    "historical_wdc_primary_cell": "old_30_second_worker_result_deadline",
    "diagnostic_graph_nonzero_optimum": "large_components_outside_exact_solver_caps",
    "equivalence_validation": "old_900_second_replay_deadline",
    "command_failure": "historical_engineering_command_not_repair_experiment",
    "native_qualification": "native_method_not_eligible_no_full_reproduction",
    "presentation_qa": "historical_figure_superseded",
    "source_retrieval": "historical_retrieval_failure",
    "candidate_not_needed": "first_candidate_qualified_no_substitution",
}
HISTORICAL_STATUSES = {"not_run_historically", "timeout", "missing_B1_to_B48",
    "not_verified_validation_timeout", "1", "124", "NOT_RUN_NATIVE_FIDELITY_INELIGIBLE",
    "NOT_RUN_NATIVE_RESOURCE_AND_FIDELITY_INELIGIBLE", "superseded_by_figures_v2", "HTTP406", "not_attempted"}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def same_number(actual, expected, label):
    if expected is None:
        require(actual is None, label + " must remain null")
    else:
        require(actual is not None and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-9), label + " differs")


def unique_index(rows, fields, label):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in fields)
        require(key not in result, "Duplicate " + label)
        result[key] = row
    return result


def validate(directory):
    directory = Path(directory)
    manifest_path = directory / "manifest.json"
    require(not manifest_path.is_symlink(), "Manifest symlink forbidden")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(set(manifest) == {"schema", "scope", "source_archive_sha256", "source_verification",
                             "sequence_provenance", "counts", "files"}, "Unexpected manifest field")
    require(manifest["schema"] == SCHEMA and manifest["scope"] == SCOPE, "Invalid evidence scope")
    require(manifest["source_archive_sha256"] == SOURCE_HASH, "Pinned source hash mismatch")
    require(manifest["source_verification"] == "archive_hash_all_member_hashes_and_private_arithmetic_passed", "Source verification status differs")
    require(manifest["sequence_provenance"] == PROVENANCE, "Pair identity limitation missing")
    filenames = {name + ".csv" for name in SCHEMAS}
    require(set(manifest["files"]) == filenames, "Manifest file set differs")
    require({p.name for p in directory.iterdir()} == filenames | {"manifest.json"}, "Unexpected evidence file")
    for name, item in manifest["files"].items():
        path = directory / name
        require(set(item) == {"sha256", "bytes", "rows"}, "Unexpected file manifest field")
        require(path.is_file() and not path.is_symlink(), "Nonregular evidence file")
        require(sha256(path) == item["sha256"] and path.stat().st_size == item["bytes"], "Evidence source hash/size mismatch: " + name)
    tables = load_evidence(directory)
    for name, rows in tables.items():
        require(len(rows) == manifest["files"][name + ".csv"]["rows"], "Manifest row count differs")
        for row in rows:
            for key, value in row.items():
                if isinstance(value, float):
                    require(value >= 0, "Negative public ratio/time")
                if isinstance(value, int) and not isinstance(value, bool) and key not in {
                    "loss_reduction", "loss_difference", "fp_difference", "fn_difference"}:
                    require(value >= 0, "Negative public count")

    endpoints = unique_index(tables["endpoints"], ("run_id",), "endpoint")
    expected_ids = {f"{d}_{m}_B{b}" for d in DATASETS for m in METHODS for b in BUDGETS}
    require({k[0] for k in endpoints} == expected_ids, "Expected all 18 independent endpoint cells")
    for name in ("endpoints", "events", "states", "batches", "candidate_depths", "cache_counts"):
        for row in tables[name]:
            require(row["run_id"] in expected_ids and row["run_id"] == f"{row['dataset']}_{row['method']}_B{row['budget']}", "Invalid descriptive run key")
    totals = {"endpoints": 18, "events": 504, "batches": 493, "states": 522}
    require(manifest["counts"] == totals, "Unexpected declared scientific counts")
    require(all(len(tables[k]) == v for k, v in totals.items()), "Public event/batch/state totals differ")
    grouped = {}
    for name in ("events", "states", "batches", "candidate_depths", "cache_counts"):
        grouped[name] = defaultdict(list)
        for row in tables[name]:
            grouped[name][row["run_id"]].append(row)

    for (run_id,), endpoint in endpoints.items():
        require(endpoint["status"] == "completed" and endpoint["stop_reason"] == "budget_exhausted", "Unexpected completed scope")
        require(endpoint["paid"] == endpoint["budget"], "Exact paid budget differs")
        require(endpoint["loss"] == endpoint["fp"] + endpoint["fn"] and endpoint["initial_loss"] == endpoint["initial_fp"] + endpoint["initial_fn"], "Endpoint FP/FN sum differs")
        events = grouped["events"][run_id]
        states = grouped["states"][run_id]
        batches = grouped["batches"][run_id]
        require([r["spent"] for r in events] == list(range(1, endpoint["paid"] + 1)), "Missing/nonconsecutive event")
        require([r["spent"] for r in states] == list(range(endpoint["paid"] + 1)), "Missing/nonconsecutive state")
        require([r["batch"] for r in batches] == list(range(1, len(batches) + 1)), "Missing/nonconsecutive batch")
        require(len(batches) == endpoint["unique_recorded_batches"], "Batch endpoint total differs")
        require((states[0]["fp"], states[0]["fn"]) == (endpoint["initial_fp"], endpoint["initial_fn"]), "Initial state differs")
        categories = Counter()
        for event, before, after in zip(events, states, states[1:]):
            require(event["category"] in ("paid_positive", "negative_no_split", "negative_split"), "Unknown event category")
            categories[event["category"]] += 1
            require(after["fp"] + after["fn"] == after["loss"], "State loss differs")
            require(before["fp"] - after["fp"] == event["fp_removed"] >= 0, "FP conservation failed")
            require(after["fn"] - before["fn"] == event["fn_added"] >= 0, "FN conservation failed")
            require(before["loss"] - after["loss"] == event["loss_reduction"] == event["fp_removed"] - event["fn_added"], "Event loss conservation failed")
            require(all(after[k] == event[k + "_after"] for k in ("fp", "fn", "loss")), "Event state mismatch")
            split = after["components"] - before["components"]
            require(split in (0, 1), "One deleted edge cannot split into more than two")
            require((event["category"] == "negative_split") == (split == 1), "Split category mismatch")
            if not split:
                require(event["fp_removed"] == event["fn_added"] == 0, "Nonsplit metrics changed")
        require(all(states[-1][k] == endpoint[k] for k in ("fp", "fn", "loss")), "Final endpoint differs")
        require(sum(r["fp_removed"] for r in events) == endpoint["fp_removed"], "FP event sum differs")
        require(sum(r["fn_added"] for r in events) == endpoint["fn_added"], "FN event sum differs")
        positive, negative_split, negative_no = (categories[k] for k in ("paid_positive", "negative_split", "negative_no_split"))
        negative = negative_split + negative_no
        require((positive, negative, negative_no, negative_split) == tuple(endpoint[k] for k in ("positive_queries", "negative_queries", "negative_no_split_queries", "negative_split_queries")), "Event classification totals differ")
        same_number(endpoint["negative_fraction"], ratio(negative, endpoint["paid"]), "Negative fraction")
        same_number(endpoint["split_given_negative"], ratio(negative_split, negative), "Split fraction")
        same_number(endpoint["fp_removed_per_split"], ratio(endpoint["fp_removed"], negative_split), "FP per split")
        same_number(sum(r["selection_seconds"] for r in batches), endpoint["selector_seconds"], "Batch selector time")
        require(endpoint["selector_seconds"] <= endpoint["audit_seconds"] <= endpoint["worker_wall_seconds"], "Nested timing order differs")
        spent = 0
        for batch in batches:
            action_events = [r for r in events if r["batch"] == batch["batch"]]
            size = batch["committed_action_size"]
            require(batch["spent_before"] == spent and size == batch["recorded_physical_queries"] == len(action_events), "Batch physical query accounting differs")
            require([e["spent"] for e in action_events] == list(range(spent + 1, spent + size + 1)), "Batch boundary differs")
            require(1 <= size <= 4 and sum(batch[f"selected_depth_{d}"] for d in range(1, 5)) == 1 and batch[f"selected_depth_{size}"] == 1, "Selected action width differs")
            spent += size
            require(batch["fallback"] in ("", "edge_betweenness") and batch["fallback_trigger"] in ("", "empty_pool", "nonpositive_utility"), "Unknown fallback classification")
            if endpoint["method"] != METHODS[0]:
                sums = {s: sum(batch[f"{s}_depth_{d}"] for d in range(1, 5)) for s in (*STAGES, "validated")}
                require(sums["generated"] == batch["raw_candidate_plans"] and sums["capped"] <= 64, "Generated/truncated count differs")
                require(sums["validated"] == batch["candidate_actions"] and sums["scored"] == batch["scored_candidate_actions"], "Scoring count differs")
                for d in range(1, 5):
                    require(batch[f"generated_depth_{d}"] >= batch[f"capped_depth_{d}"] >= batch[f"validated_depth_{d}"] >= batch[f"scored_depth_{d}"], "Stage count containment failed")
                if endpoint["method"] == METHODS[2]:
                    require(all(batch[f"scored_depth_{d}"] == 0 for d in (2, 3, 4)), "Singleton scored multiedge candidates")
                    require(size == 1, "Singleton executed multiedge action")
        require(spent == endpoint["paid"], "Batch cost does not conserve paid answers")
        depth_rows = grouped["candidate_depths"][run_id]
        if endpoint["method"] == METHODS[0]:
            require(not depth_rows, "BC has no planner depth pool")
        else:
            depth_index = unique_index(depth_rows, ("stage", "depth"), "candidate depth")
            require(set(depth_index) == {(s, d) for s in STAGES for d in range(1, 5)}, "Candidate stage/depth coverage missing")
            for stage in STAGES:
                values = {d: sum(r[f"{stage}_depth_{d}"] for r in batches) for d in range(1, 5)}
                total, multi = sum(values.values()), sum(values[d] for d in (2, 3, 4))
                for depth in range(1, 5):
                    row = depth_index[stage, depth]
                    require((row["count"], row["total"], row["multi_count"]) == (values[depth], total, multi), "Depth aggregate double counted/mismatch")
                    same_number(row["multi_fraction"], ratio(multi, total), "Stage multi fraction")
        caches = unique_index(grouped["cache_counts"][run_id], ("cache",), "cache")
        require(all(k[0] in CACHE_NAMES for k in caches), "Unknown cache")
        relevant = "original_centrality" if endpoint["method"] == METHODS[0] else "centrality"
        require((relevant,) in caches, "Missing centrality cache counts")
        require(caches[relevant,]["hits"] + caches[relevant,]["misses"] == len(batches), "Centrality accesses differ from batches")

    coverage = unique_index(tables["coverage"], ("dataset",), "coverage")
    require(set(coverage) == {(d,) for d in DATASETS}, "Coverage datasets differ")
    for (dataset,), row in coverage.items():
        require(row["components"] == row["exact_components"] + row["skipped_components"] and row["covered_fp"] <= row["initial_fp"], "Coverage counts differ")
        same_number(row["component_fraction"], ratio(row["exact_components"], row["components"]), "Component coverage")
        same_number(row["fp_fraction"], ratio(row["covered_fp"], row["initial_fp"]), "FP mass coverage")
        require(row["status"] == ("exact" if row["skipped_components"] == 0 else "partial_component_diagnosis"), "Partial bound mislabeled exact")
        for endpoint in tables["endpoints"]:
            if endpoint["dataset"] == dataset:
                require((row["initial_fp"], row["initial_fn"]) == (endpoint["initial_fp"], endpoint["initial_fn"]), "Coverage initial metrics differ")
    curve = tables["bound_curve"]
    require([r["budget"] for r in curve] == list(range(49)), "Complete DBLP bound curve missing")
    previous = None
    for row in curve:
        require(row["dataset"] == "dblp_acm" and row["status"] == "exact", "Only DBLP complete bound may be public curve")
        require(row["exact_loss"] == row["exact_fp"] + row["exact_fn"] and row["feasible_deleted_edges"] <= row["budget"], "Bound cost/loss invalid")
        require(previous is None or row["exact_loss"] <= previous, "Bound curve not monotone")
        previous = row["exact_loss"]
    require(curve[0]["exact_loss"] == coverage["dblp_acm",]["initial_fp"] + coverage["dblp_acm",]["initial_fn"], "B0 bound differs")
    for endpoint in tables["endpoints"]:
        if endpoint["dataset"] == "dblp_acm":
            require(endpoint["loss"] >= curve[endpoint["budget"]]["exact_loss"], "Observed loss below offline bound")
    contrasts = unique_index(tables["contrasts"], ("dataset", "budget", "comparison"), "contrast")
    require(set(contrasts) == {(d, b, c) for d in DATASETS for b in BUDGETS for c in ("raw_minus_singleton", "raw_minus_bc")}, "Missing prespecified contrast")
    for (dataset, budget, comparison), row in contrasts.items():
        other = METHODS[2] if comparison == "raw_minus_singleton" else METHODS[0]
        raw = endpoints[f"{dataset}_{METHODS[1]}_B{budget}",]
        comparator = endpoints[f"{dataset}_{other}_B{budget}",]
        require(row["status"] == "available" and row["sequence_provenance"] == PROVENANCE, "Contrast provenance missing")
        require(all(row[k + "_difference"] == raw[k] - comparator[k] for k in ("loss", "fp", "fn")), "Contrast direction/value differs")
        require(row["equal_endpoint_loss"] == (raw["loss"] == comparator["loss"]), "Equal loss flag differs")
        for key in ("first_paid_sequence_divergence", "first_paid_or_batch_divergence"):
            require(row[key] is None or 1 <= row[key] <= budget, "Reported private divergence outside query range")
        require(row["same_paid_and_batch_sequence"] == (row["first_paid_or_batch_divergence"] is None), "Sequence status internally inconsistent")
    historical = unique_index(tables["historical_missing"], ("category", "status"), "historical category")
    for (category, status), row in historical.items():
        require(category in HISTORICAL_SCOPES and row["scope"] == HISTORICAL_SCOPES[category] and status in HISTORICAL_STATUSES and row["count"] > 0, "Invalid historical scope")
    require(historical.get(("historical_primary_cell", "not_run_historically"), {}).get("count") == 42, "42 historical unrun comparisons missing")
    require(historical.get(("historical_wdc_primary_cell", "timeout"), {}).get("count") == 3, "Old WDC timeouts missing")
    return {"status": "PASS", **totals, "tables": len(tables), "candidate_depth_rows": len(tables["candidate_depths"]),
            "manifest_sha256": sha256(manifest_path), "source_archive_sha256": SOURCE_HASH,
            "scope": "public_numeric_consistency_only_no_pair_identity_or_full_experiment_reproduction"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=Path(__file__).resolve().parents[1] / "evidence")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    receipt = validate(args.evidence)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
