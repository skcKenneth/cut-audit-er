"""Strict, standard-library-only public evidence schema and typed CSV reader.

Blank optional numeric cells mean unavailable, never zero. This module contains
no graph records, oracle answers, learned scores or selector access.
"""
from __future__ import annotations

import csv
import hashlib
import math
from pathlib import Path
import re

DATASETS = ("wdc", "dblp_acm")
METHODS = ("edge_betweenness", "cut_plan_fixed", "cut_plan_fixed_singleton")
BUDGETS = (12, 24, 48)
STAGES = ("generated", "capped", "scored", "selected")
KEY = {"run_id": "text", "dataset": "text", "method": "text", "budget": "int"}

SCHEMAS = {
    "endpoints": {**KEY, "status": "text", **{k: "int" for k in (
        "fp", "fn", "loss", "paid", "initial_fp", "initial_fn", "initial_loss",
        "unique_recorded_batches", "logical_score_accesses", "score_value_cache_hits",
        "positive_queries", "negative_queries", "negative_no_split_queries",
        "negative_split_queries", "fp_removed", "fn_added")},
        **{k: "float" for k in ("selector_seconds", "audit_seconds", "worker_wall_seconds",
        "requested_result_deadline_seconds", "cleanup_seconds", "payload_receive_seconds",
        "process_start_seconds", "result_wait_seconds")},
        **{k: "float?" for k in ("negative_fraction", "split_given_negative", "fp_removed_per_split")},
        "stop_reason": "text"},
    "events": {**KEY, "spent": "int", "batch": "int", "category": "text",
        **{k: "int" for k in ("fp_removed", "fn_added", "loss_reduction", "fp_after", "fn_after", "loss_after")}},
    "states": {**KEY, **{k: "int" for k in ("spent", "fp", "fn", "loss", "components")}},
    "batches": {**KEY, **{k: "int" for k in ("batch", "spent_before", "recorded_physical_queries", "committed_action_size")},
        "selection_seconds": "float", **{k: "int?" for k in ("raw_candidate_plans", "candidate_actions", "scored_candidate_actions")},
        **{f"{s}_depth_{d}": "int" for s in (*STAGES, "validated") for d in range(1, 5)},
        "singleton_filtered_candidates": "int", "fallback": "text", "fallback_trigger": "text"},
    "candidate_depths": {**KEY, "stage": "text", **{k: "int" for k in ("depth", "count", "total", "multi_count")}, "multi_fraction": "float?"},
    "cache_counts": {**KEY, "cache": "text", "hits": "int", "misses": "int"},
    "coverage": {"dataset": "text", **{k: "int" for k in ("exact_components", "components", "skipped_components", "covered_fp", "initial_fp", "initial_fn", "nodes", "edges")},
        "component_fraction": "float?", "fp_fraction": "float?", "status": "text"},
    "bound_curve": {"dataset": "text", "budget": "int", "status": "text",
        **{k: "int" for k in ("exact_loss", "exact_fp", "exact_fn", "feasible_deleted_edges")}},
    "contrasts": {"dataset": "text", "budget": "int", "comparison": "text", "status": "text",
        **{k: "int" for k in ("loss_difference", "fp_difference", "fn_difference")},
        "first_paid_sequence_divergence": "int?", "first_paid_or_batch_divergence": "int?",
        "equal_endpoint_loss": "bool", "same_paid_and_batch_sequence": "bool", "sequence_provenance": "text"},
    "historical_missing": {"category": "text", "status": "text", "count": "int", "scope": "text"},
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def parse_value(value, kind):
    if kind.endswith("?"):
        if value == "":
            return None
        kind = kind[:-1]
    if kind == "int":
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
            raise ValueError("Noncanonical integer")
        return int(value)
    if kind == "float":
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite public number")
        return number
    if kind == "bool":
        if value not in ("true", "false"):
            raise ValueError("Invalid public boolean")
        return value == "true"
    if any(t in value for t in ("\\", "\n", "\r", "\x00")) or re.search(r"[A-Za-z]:[/\\]|(?:^|\s)/(?:home|Users|tmp)/", value):
        raise ValueError("Private path or multiline public field")
    return value


def load_table(directory, name):
    path = Path(directory) / (name + ".csv")
    if path.is_symlink():
        raise ValueError("Evidence symlink forbidden")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(SCHEMAS[name]):
            raise ValueError("Unexpected public columns: " + name)
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Malformed public CSV row")
            rows.append({key: parse_value(value, SCHEMAS[name][key]) for key, value in row.items()})
        return rows


def load_evidence(directory):
    """Return canonical table names mapped to typed row dictionaries."""
    return {name: load_table(directory, name) for name in SCHEMAS}
