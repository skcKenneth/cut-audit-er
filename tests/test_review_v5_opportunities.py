import hashlib
import json
from itertools import combinations
import networkx as nx
import pytest

from scripts.review_v5.opportunities import (
    STAGES, audit_state, batch_stages, checked_bundle, first_exclusion, independent_partition,
    node_bipartition_bonds, stage_sets,
)
from scripts.review_v4.synthetic import load_visible, reference_recipe, visible_recipe


def stages(candidates=()):
    return {key: list(candidates) for key in STAGES}


def test_h0_h9_same_visible_opportunity_different_fn_risk():
    graph, _ = load_visible(visible_recipe(3, "uniform"))
    plan = tuple((f"r{i}", f"r{i+3}") for i in range(3))
    a = audit_state(graph, reference_recipe("H0"), {}, 6, stages([plan]))
    b = audit_state(graph, reference_recipe("H9"), {}, 6, stages([plan]))
    wa = next(w for w in a["witnesses"] if w["edges"] == [list(e) for e in plan])
    wb = next(w for w in b["witnesses"] if w["edges"] == [list(e) for e in plan])
    assert (wa["fp_removed"], wa["fn_added"], wa["loss_gain"]) == (18, 0, 18)
    assert (wb["fp_removed"], wb["fn_added"], wb["loss_gain"]) == (9, 9, 0)
    assert a["selector_score_accesses"] == b["selector_score_accesses"] == 0
    assert (a["offline_headroom"], b["offline_headroom"]) == (0, 9)


def test_budget_exclusion_kept_even_when_not_generated():
    graph, _ = load_visible(visible_recipe(3, "uniform"))
    result = audit_state(graph, reference_recipe("H0"), {}, 2, stages())
    assert len(result["witnesses"]) == 2
    assert {r["first_exclusion"] for r in result["witnesses"]} == {"budget_insufficient"}


@pytest.mark.parametrize("stage,expected", [
    ("generated", "generation_missing"), ("capped", "cap_excluded"),
    ("validated", "legality_rejected"), ("filtered", "method_filtered"),
    ("scored", "execution_or_scoring_limit"), ("selected", "scored_not_selected"),
])
def test_first_exclusion(stage, expected):
    plan = (("a", "b"),)
    value = stages([plan])
    value[stage] = []
    assert first_exclusion(plan, stage_sets(value), 1) == expected


def test_large_absence_is_unknown_and_zero_fp_denominator_is_null():
    graph = nx.complete_graph([str(i) for i in range(17)])
    result = audit_state(graph, dict.fromkeys(graph, "same"), {}, 4, stages())
    assert result["components"][0]["status"] == "unknown"
    assert result["fp_coverage"] is None and result["zero_fp_denominator"]
    assert not result["witnesses"]


def test_large_concrete_witness_is_certified_without_completeness():
    graph = nx.path_graph([str(i) for i in range(17)])
    plan = (("7", "8"),)
    result = audit_state(graph, {str(i): "A" if i < 8 else "B" for i in range(17)}, {}, 1, stages([plan]))
    assert result["components"][0]["status"] == "partial_witnesses"
    assert result["witnesses"][0]["loss_gain"] == 72
    assert result["covered_fp"] == 0 and result["total_fp"] == 72


def test_hash_mismatch_and_missing_stages_rejected(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"visible": True}), encoding="utf-8")
    assert checked_bundle(path, hashlib.sha256(path.read_bytes()).hexdigest())["visible"]
    with pytest.raises(ValueError, match="hash"):
        checked_bundle(path, "0" * 64)
    with pytest.raises(ValueError, match="stages"):
        stage_sets({})


def test_independent_bipartition_oracle_and_paid_positive_protection():
    graph, _ = load_visible(visible_recipe(3, "uniform"))
    bonds = node_bipartition_bonds(graph)
    edges = sorted(tuple(sorted(e)) for e in graph.edges)
    edge_enumerated = {q for width in range(1, 5) for q in combinations(edges, width)
                       if independent_partition(graph, q) is not None}
    assert set(bonds) == edge_enumerated
    assert len(bonds) == 17
    assert all(independent_partition(graph, q) is not None for q in bonds)
    paid = ("r0", "r1")
    protected = node_bipartition_bonds(graph, [paid])
    assert all(paid not in q for q in protected)
    with pytest.raises(ValueError, match="positive"):
        audit_state(graph, reference_recipe("H0"), {("r0", "r8"): True}, 1, stages())


def test_stage_normalization_respects_cap_and_score_limit_separately():
    a, b = [["a", "b"]], [["b", "c"]]
    batch = {"action": a, "planned_action": a, "selection_info": {},
             "candidate_trace": {"union_generated": [a, b], "capped_order": [a],
                                 "validated_order": [a, b], "eligible_order": [a, b], "scored_order": [a]}}
    normalized = batch_stages(batch, "cut_plan_cover_bccap")
    assert normalized["validated"] == [a]
    assert first_exclusion((("b", "c"),), stage_sets(normalized), 2) == "cap_excluded"
    batch["candidate_trace"]["capped_order"] = [a, b]
    normalized = batch_stages(batch, "cut_plan_cover_fixed")
    assert first_exclusion((("b", "c"),), stage_sets(normalized), 2) == "execution_or_scoring_limit"


def test_fallback_is_not_a_positive_scored_plan():
    a = [["a", "b"]]
    batch = {"action": a, "planned_action": a, "selection_info": {"fallback": "bc"},
             "candidate_trace": {"union_generated": [a], "capped_order": [a],
                                 "validated_order": [a], "eligible_order": [a], "scored_order": [a]}}
    assert batch_stages(batch, "cut_plan_cover_fixed")["selected"] == []
