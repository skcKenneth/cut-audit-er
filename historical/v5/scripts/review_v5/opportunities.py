"""Independent offline batch-state opportunity audit; never imported by selectors.

Gold is accepted only here. Visible-stage lists must be captured/reconstructed
before calling this evaluator. Absent witnesses on large components mean unknown.
No acquisition, policy selection, model fitting or score reads occur here.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations
import hashlib
import json
import time
from pathlib import Path

import networkx as nx

STAGES = ("generated", "capped", "validated", "filtered", "scored", "selected")


def canonical(plan):
    value = tuple(sorted(tuple(sorted(e)) for e in plan))
    if not value or any(len(e) != 2 or e[0] == e[1] for e in value) or len(set(value)) != len(value):
        raise ValueError("Invalid candidate edge set")
    return value


def independent_partition(component, plan):
    """An independent deletion/two-connected-sides bond check."""
    if any(not component.has_edge(*edge) for edge in plan):
        return None
    retained = component.copy()
    retained.remove_edges_from(plan)
    parts = sorted(tuple(sorted(c)) for c in nx.connected_components(retained))
    if len(parts) != 2:
        return None
    left = set(parts[0])
    if any((u in left) == (v in left) for u, v in plan):
        return None
    return parts


def node_bipartition_bonds(component, verified=(), max_width=4):
    """Independent correctness oracle: node partitions, not edge subsets."""
    nodes = sorted(component)
    if not nodes or len(nodes) > 16 or component.number_of_edges() > 16:
        raise ValueError("Independent exhaustive oracle limited to16nodes/16edges")
    blocked = {tuple(sorted(e)) for e in verified}
    out = set()
    for mask in range(1 << (len(nodes) - 1)):
        left = {nodes[0]} | {n for i, n in enumerate(nodes[1:]) if mask & (1 << i)}
        right = set(nodes) - left
        if not right or not nx.is_connected(component.subgraph(left)) or not nx.is_connected(component.subgraph(right)):
            continue
        cut = tuple(sorted(tuple(sorted((u, v))) for u, v in component.edges if (u in left) != (v in left)))
        if cut and len(cut) <= max_width and not blocked.intersection(cut):
            out.add(cut)
    return sorted(out, key=lambda q: (len(q), q))


def stage_sets(stages):
    if set(stages) != set(STAGES):
        raise ValueError("All visible candidate stages must be explicitly supplied")
    return {key: {canonical(q) for q in value} for key, value in stages.items()}


def first_exclusion(plan, stages, remaining, *, baseline=False):
    if len(plan) > remaining:
        return "budget_insufficient"
    if baseline:
        return "selected" if plan in stages["selected"] else "baseline_edge_policy"
    for stage, missing in (("generated", "generation_missing"), ("capped", "cap_excluded"),
                           ("validated", "legality_rejected"), ("filtered", "method_filtered"),
                           ("scored", "execution_or_scoring_limit")):
        if plan not in stages[stage]:
            return missing
    return "selected" if plan in stages["selected"] else "scored_not_selected"


def audit_state(graph, reference, observed, remaining, stages, *, baseline=False):
    """Audit all small components and only explicit witnesses on large ones.

    ``stages`` contains six lists of visible candidates. For a method without a
    cap/filter, its stage is the previous unchanged list, not an empty list.
    ``selected`` is the committed/planned candidate; actual execution is separate.
    Opportunities require all their edges to be negative under this offline
    reference. They can still add FN across disconnected true matches.
    """
    started = time.perf_counter()
    if set(graph) != set(reference) or type(remaining) is not int or remaining < 0:
        raise ValueError("Reference membership or remaining budget differs")
    if any(type(a) is not bool for a in observed.values()):
        raise ValueError("Non-Boolean paid answer")
    if any(len(e) != 2 or e[0] not in graph or e[1] not in graph or e[0] == e[1]
           for e in observed):
        raise ValueError("Paid answer membership differs")
    paid = {tuple(sorted(e)) for e in observed}
    if any(graph.has_edge(*e) for e, a in observed.items() if not a):
        raise ValueError("Paid negative edge was not removed")
    if any(not graph.has_edge(*e) for e, a in observed.items() if a):
        raise ValueError("Paid positive edge was removed")
    visible = stage_sets(stages)
    known = set().union(*visible.values())
    components, witnesses = [], []
    for index, nodes in enumerate(sorted(tuple(sorted(c)) for c in nx.connected_components(graph))):
        local = graph.subgraph(nodes).copy()
        labels = Counter(reference[n] for n in nodes)
        fp = len(nodes) * (len(nodes) - 1) // 2 - sum(n * (n - 1) // 2 for n in labels.values())
        exact = len(nodes) <= 16 and local.number_of_edges() <= 16
        negatives = sorted(tuple(sorted(e)) for e in local.edges
                           if reference[e[0]] != reference[e[1]] and tuple(sorted(e)) not in paid)
        negative_set = set(negatives)
        if exact:
            candidates = [q for width in range(1, min(4, len(negatives)) + 1)
                          for q in combinations(negatives, width)]
        else:
            candidates = sorted(q for q in known if 1 <= len(q) <= 4 and set(q) <= negative_set)
        found = 0
        for candidate in candidates:
            parts = independent_partition(local, candidate)
            if parts is None:
                continue
            left, right = (Counter(reference[n] for n in side) for side in parts)
            true_cross = sum(n * right.get(label, 0) for label, n in left.items())
            total_cross = len(parts[0]) * len(parts[1])
            gain = total_cross - 2 * true_cross
            found += 1
            witnesses.append({"component": index, "edges": [list(e) for e in candidate],
                              "depth": len(candidate), "fp_removed": total_cross - true_cross,
                              "fn_added": true_cross, "loss_gain": gain,
                              "beneficial": gain > 0, "affordable": len(candidate) <= remaining,
                              "first_exclusion": first_exclusion(candidate, visible, remaining, baseline=baseline),
                              "membership": {key: candidate in value for key, value in visible.items()},
                              "enumeration_scope": "complete_small" if exact else "explicit_large_witness"})
        components.append({"component": index, "nodes": len(nodes), "edges": local.number_of_edges(),
                           "current_fp": fp, "exhaustive": exact,
                           "status": "complete" if exact else "partial_witnesses" if found else "unknown",
                           "negative_subsets_checked": len(candidates), "bonds_found": found})
    total_fp = sum(row["current_fp"] for row in components)
    covered_fp = sum(row["current_fp"] for row in components if row["exhaustive"])
    positive = graph.copy()
    positive.remove_edges_from([(u, v) for u, v in graph.edges if reference[u] != reference[v]])
    def connected_true_pairs(g):
        return sum(sum(n * (n - 1) // 2 for n in Counter(reference[v] for v in c).values())
                   for c in nx.connected_components(g))
    headroom = connected_true_pairs(graph) - connected_true_pairs(positive)
    return {"schema": "cut-audit-v5-offline-opportunities-v1", "remaining": remaining,
            "stage_counts": {key: len(value) for key, value in visible.items()},
            "components": components, "witnesses": witnesses,
            "exact_components": sum(row["exhaustive"] for row in components),
            "total_components": len(components), "covered_fp": covered_fp, "total_fp": total_fp,
            "fp_coverage": covered_fp / total_fp if total_fp else None,
            "offline_headroom": headroom,
            "zero_fp_denominator": total_fp == 0, "selector_score_accesses": 0,
            "offline_seconds": time.perf_counter() - started,
            "interpretation": "Descriptive first exclusion, not additive causal loss attribution"}


def checked_bundle(path, expected_sha256):
    """Standalone evaluator input is bound to a caller-recorded visible hash."""
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Offline visible input hash mismatch")
    return json.loads(data)


def batch_stages(batch, method):
    """Normalize saved visible stages; a scoring limit is never a BC cap."""
    trace = batch["candidate_trace"]
    if method == "edge_betweenness":
        candidates = [[row["pair"]] for row in trace["bc_ranked"]]
        result = {key: candidates for key in STAGES}
        result["selected"] = [batch["action"]]
        return result
    required = ("union_generated", "capped_order", "validated_order", "eligible_order", "scored_order")
    if any(key not in trace for key in required):
        raise ValueError("Visible batch lacks a candidate stage")
    capped = {canonical(q) for q in trace["capped_order"]}
    # A coverage+BC-cap implementation may already have validated the union for
    # reusable bookkeeping. Its method's legal stage is still capped intersect
    # legal, and candidates dropped by the cap are not counted as scored.
    legal = [q for q in trace["validated_order"] if canonical(q) in capped]
    eligible_set = {canonical(q) for q in trace["eligible_order"]}
    filtered = [q for q in legal if canonical(q) in eligible_set]
    selected = [] if batch["selection_info"].get("fallback") else [batch["planned_action"]]
    return {"generated": trace["union_generated"], "capped": trace["capped_order"],
            "validated": legal, "filtered": filtered, "scored": trace["scored_order"],
            "selected": selected}


def analyze_saved(phase, analysis, manifest_sha256, out, root):
    """Explicit offline process over hash-bound visible replays and references."""
    from scripts.review_v5 import study
    from scripts.review_v5.analysis import csv_write
    root, analysis, out = map(lambda p: Path(p).resolve(), (root, analysis, out))
    if not all(p.is_relative_to(root) for p in (analysis, out)) or out.exists():
        raise ValueError("Fresh contained offline output required")
    manifest = checked_bundle(analysis / "manifest.json", manifest_sha256)
    if manifest.get("status") != "passed" or manifest.get("phase") != phase:
        raise ValueError("Successful matching visible analysis required")
    study.check_hashes(analysis, manifest["files_sha256"])
    frozen, snapshot = study.checked_freeze(root)
    out.mkdir(parents=True)
    rows, witnesses, components = [], [], []
    references = {}
    if phase == "synthetic":
        references = {label: study.read(snapshot / f"inputs/synthetic/{label}.json")["reference"]
                      for label in ("H0", "H9")}
    started = time.perf_counter()
    for path in sorted((analysis / "replays").glob("*.json")):
        replay = study.read(path)
        if phase == "natural":
            folder = snapshot / "inputs/natural" / replay["dataset"]
            references = {"natural": study.read(folder / "evaluator_reference.json")["reference"]}
        for batch in replay["batches"]:
            graph = nx.Graph()
            graph.add_nodes_from(n for group in batch["partition_before"] for n in group)
            graph.add_edges_from(batch["edges_before"])
            if sorted(sorted(c) for c in nx.connected_components(graph)) != batch["partition_before"]:
                raise ValueError("Saved batch graph/partition disagreement")
            observed = {tuple(row["pair"]): row["answer"] for row in batch["observed_answers_before"]}
            stages = batch_stages(batch, replay["method"])
            for label, truth in references.items():
                result = audit_state(graph, truth, observed, batch["remaining"], stages,
                                     baseline=replay["method"] == "edge_betweenness")
                key = {"run_id": replay["run_id"], "dataset": replay["dataset"], "method": replay["method"],
                       "budget": replay["budget"], "reference": label, "batch": batch["batch"],
                       "spent_before": batch["spent_before"], "endpoint_complete": replay["complete"]}
                counted = Counter(w["first_exclusion"] for w in result["witnesses"] if w["beneficial"])
                rows.append({**key, **{k: v for k, v in result.items() if k not in ("components", "witnesses", "schema")},
                             "beneficial_first_exclusions": dict(counted), "witnesses": len(result["witnesses"]),
                             "committed_depth": len(batch["action"]), "planned_depth": len(batch["planned_action"]),
                             "recorded_queries": batch["recorded_queries"], "fallback": bool(batch["selection_info"].get("fallback"))})
                for witness in result["witnesses"]:
                    witnesses.append({**key, **witness,
                                      "is_actual_action": canonical(witness["edges"]) == canonical(batch["action"])})
                components.extend({**key, **row} for row in result["components"])
    for name, data in (("batch_diagnoses", rows), ("opportunities", witnesses), ("coverage", components)):
        csv_write(out / (name + ".csv"), data)
    report = {"schema": "cut-audit-v5-opportunity-analysis-v1", "status": "passed", "phase": phase,
              "visible_analysis_manifest_sha256": manifest_sha256,
              "freeze_sha256": study.digest(root / study.SESSION / "freeze.json"),
              "offline_evaluator_source_sha256": study.digest(Path(__file__)),
              "batch_reference_states": len(rows), "witness_rows": len(witnesses),
              "new_oracle_answers": 0, "selector_score_accesses": 0,
              "seconds": time.perf_counter() - started,
              "scope": "Repeated witnesses across states are dependent; large-component absence is unknown",
              "files_sha256": {p.name: study.digest(p) for p in out.iterdir() if p.is_file()}}
    study.write(out / "manifest.json", report)
    return report


if __name__ == "__main__":
    import argparse
    import sys
    workspace = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(workspace))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("synthetic", "natural"), required=True)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze_saved(args.phase, args.analysis, args.manifest_sha256, args.out, workspace)))
