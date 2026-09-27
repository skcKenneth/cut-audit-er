"""Synthetic correctness fixtures only; never additional research acquisitions."""
from copy import deepcopy
from fractions import Fraction
import inspect
import json

import networkx as nx
import numpy as np
import pytest

from cut_audit_er.audit import run_audit
from cut_audit_er.scores import PairScores
from scripts.review_v4.synthetic import visible_recipe, load_visible, reference_recipe
from scripts.review_v5.analysis import visible_replay
from scripts.review_v6 import audit as a


def fixture(k=2, budget=4, profile="uniform"):
    graph, scores = load_visible(visible_recipe(k, profile))
    run = run_audit(graph, scores, reference_recipe("H0"), "cut_plan_cover_fixed", budget, match_threshold=.6)
    replay = visible_replay(graph, scores, run, complete=True)
    return graph, scores, replay


def saved_states(graph, replay):
    current = graph.copy()
    for batch in replay["batches"]:
        history = [{"pair": event["pair"], "answer": event["answer"]} for event in replay["events"] if event["spent"] <= batch["spent_before"]]
        yield current.copy(), batch, history
        for event in replay["events"]:
            if event["batch"] == batch["batch"] and not event["answer"]:
                current.remove_edge(*event["pair"])


@pytest.mark.parametrize("k,budget,profile", [(1, 1, "uniform"), (1, 6, "ranked"), (2, 4, "uniform"), (2, 6, "ranked"), (3, 3, "uniform"), (3, 6, "ranked")])
def test_all_saved_states_full_pool_certificates_and_two_reference_gains(k, budget, profile):
    graph, scores, replay = fixture(k, budget, profile)
    for current, batch, history in saved_states(graph, replay):
        calls = scores.calls
        result = a.audit_visible_state(current, scores, batch, history, source_identity="0" * 64)
        assert scores.calls == calls
        assert result["searched_pool_complete_audit"] and result["small_component_bonds_complete"]
        assert result["graph_wide_bonds_complete"]
        before = a.fingerprint(result)
        for name in ("H0", "H9"):
            evaluation = a.evaluate_visible_state(result, reference_recipe(name))
            assert evaluation["single_batch_oracle_gap"] >= 0
            assert evaluation["selected"]["query_cost"] == len(batch["action"])
            assert evaluation["selected"]["loss_gain"] == evaluation["selected"]["fp_removed"] - evaluation["selected"]["fn_added"]
            candidates = [Fraction(r["loss_gain"], r["query_cost"]) for r in evaluation["candidates"]]
            selected = Fraction(evaluation["selected"]["loss_gain"], evaluation["selected"]["query_cost"])
            assert Fraction(*evaluation["gap_fraction"]) == max([Fraction(0), selected] + candidates) - selected
        assert a.fingerprint(result) == before
        assert "reference" not in inspect.signature(a.audit_visible_state).parameters


@pytest.mark.parametrize("tamper", ["bound", "score", "order", "selected", "small", "status", "history", "remaining"])
def test_frozen_trace_corruption_is_rejected(tamper):
    graph, scores, replay = fixture()
    batch = deepcopy(replay["batches"][0])
    trace = batch["candidate_trace"]
    if tamper == "bound": trace["bound_records"][0]["upper_bound"] = -1
    elif tamper == "score": trace["score_records"][0]["proxy"] += 1
    elif tamper == "order": trace["screening_order"] = list(reversed(trace["screening_order"]))
    elif tamper == "selected": batch["action"] = [["A0", "A1"]]
    elif tamper == "small": trace["enumerated"] = trace["enumerated"][:-1]
    elif tamper == "status": batch["selection_info"]["surrogate_certificate_status"] = "score_limit_uncertified"
    elif tamper == "history": batch["spent_before"] = 1
    else: batch["remaining"] = 0
    with pytest.raises(ValueError): a.audit_visible_state(graph, scores, batch, [], source_identity="0" * 64)


def test_positive_answer_commits_full_batch_and_nonsplit_negative_costs():
    graph = nx.cycle_graph(["a", "b", "c"])
    for u, v in graph.edges: graph.edges[u, v]["p"] = .7
    truth = {"a": 0, "b": 0, "c": 1}
    before = a.metric(a.partition(graph), truth)
    positive_mixed = a.realized_action(graph, truth, [("a", "b"), ("a", "c")], before)
    assert positive_mixed["query_cost"] == 2 and positive_mixed["positive_answers"] == 1
    assert positive_mixed["loss_gain"] == 0
    nonsplit = a.realized_action(graph, truth, [("a", "c")], before)
    assert nonsplit["query_cost"] == 1 and nonsplit["loss_gain"] == 0
    split = a.realized_action(graph, truth, [("a", "c"), ("b", "c")], before)
    assert split["fp_removed"] == 2 and split["fn_added"] == 0


def test_fallback_is_separate_from_certified_nonpositive_pool_zero_denominator():
    graph = nx.path_graph(["a", "b", "c", "d"])
    for u, v in graph.edges: graph.edges[u, v]["p"] = .99
    scores = PairScores(tuple(graph), np.full((4, 4), .99))
    truth = {n: "same" for n in graph}
    run = run_audit(graph, scores, truth, "cut_plan_cover_fixed", 2, match_threshold=.6)
    replay = visible_replay(graph, scores, run, complete=True)
    for current, batch, history in saved_states(graph, replay):
        visible = a.audit_visible_state(current, scores, batch, history, source_identity="0" * 64)
        assert visible["fallback"] and not visible["certificate_for_selected_positive"]
        evaluation = a.evaluate_visible_state(visible, truth)
        assert evaluation["zero_fp_denominator"] and evaluation["fp_coverage"] is None
        assert evaluation["single_batch_oracle_gap"] == 0


def test_partial_universe_is_only_a_lower_bound_and_keeps_actual_plus_noop():
    graph, scores, replay = fixture()
    visible = a.audit_visible_state(graph, scores, replay["batches"][0], [], source_identity="0" * 64)
    visible["status"] = "partial"
    visible["searched_pool_complete_audit"] = False
    visible["candidates"] = []
    value = a.evaluate_visible_state(visible, reference_recipe("H0"))
    assert value["status"] == "partial_lower_bound"
    assert value["gap_scope"].startswith("lower_bound")
    assert value["single_batch_oracle_gap"] == 0


def test_reference_conflict_and_membership_missing_rejected():
    graph, scores, replay = fixture(1, 6)
    current, batch, history = list(saved_states(graph, replay))[-1]
    visible = a.audit_visible_state(current, scores, batch, history, source_identity="0" * 64)
    with pytest.raises(ValueError, match="membership"): a.evaluate_visible_state(visible, {})
    with pytest.raises(ValueError, match="paid answer"): a.evaluate_visible_state(visible, {n: "same" for n in graph})


def test_visible_dedup_changes_with_budget_ordered_history_or_score_identity():
    graph, scores, replay = fixture(1, 6)
    current, batch, history = next(saved_states(graph, replay))
    first = a.audit_visible_state(current, scores, batch, history, source_identity="0" * 64)
    second = a.audit_visible_state(current, scores, batch, history, source_identity="1" * 64)
    assert first["state_sha256"] != second["state_sha256"]
    # repeated identical state has identical identity despite diagnostic timing
    again = a.audit_visible_state(current, scores, batch, history, source_identity="0" * 64)
    assert first["state_sha256"] == again["state_sha256"]


def test_source_manifest_hash_mismatch_rejected(tmp_path):
    from scripts.review_v6.audit_runner import checked_manifest
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({}), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash"): checked_manifest(path, "0" * 64)


def test_missing_and_large_component_are_not_zero_coverage():
    graph = nx.path_graph([str(n).zfill(2) for n in range(17)])
    for u, v in graph.edges: graph.edges[u, v]["p"] = .1
    scores = PairScores(tuple(graph), np.full((17, 17), .1))
    truth = {n: n for n in graph}
    run = run_audit(graph, scores, truth, "cut_plan_cover_fixed", 1, match_threshold=.6)
    replay = visible_replay(graph, scores, run, complete=True)
    result = a.audit_visible_state(graph, scores, replay["batches"][0], [], source_identity="0" * 64)
    assert result["searched_pool_complete_audit"] and not result["graph_wide_bonds_complete"]
    assert result["components"][0]["independent_bonds"] is None
    assert result["components"][0]["status"] == "large_coverage_unknown"


def test_more_than_64_tied_candidates_remain_uncertified():
    graph = nx.star_graph([str(n).zfill(2) for n in range(70)])
    for u, v in graph.edges: graph.edges[u, v]["p"] = 0.
    scores = PairScores(tuple(graph), np.zeros((70, 70)))
    truth = {n: n for n in graph}
    run = run_audit(graph, scores, truth, "cut_plan_cover_fixed", 1, match_threshold=.6)
    replay = visible_replay(graph, scores, run, complete=True)
    result = a.audit_visible_state(graph, scores, replay["batches"][0], [], source_identity="0" * 64)
    assert result["pool_count"] == 69 and result["scored_count"] == 64
    assert result["certificate_status"] == "score_limit_uncertified"
    assert not result["certificate_for_selected_positive"]
    assert sum(row["unscored_reason"] == "score_limit_unscored" for row in result["candidates"]) == 5
