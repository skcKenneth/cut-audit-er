"""Constructed fixtures only: durable partial evidence is never a final outcome."""
from copy import deepcopy
import hashlib
import json
import multiprocessing as mp
from pathlib import Path
import time

import networkx as nx
import numpy as np
import pytest

from cut_audit_er.audit import run_audit
from cut_audit_er.natural import bounded_audit
from cut_audit_er.oracle import BudgetedOracle
from cut_audit_er.scores import PairScores
from cut_audit_er.telemetry import AuditJournal, recover_journal


def arguments(method="random", noise=0.):
    ids = tuple("abcdef")
    matrix = np.full((6, 6), .1)
    matrix[:3, :3] = matrix[3:, 3:] = .95
    np.fill_diagonal(matrix, 1.)
    graph = nx.Graph()
    graph.add_nodes_from(ids)
    for left, right in (("a", "b"), ("a", "c"), ("b", "c"), ("d", "e"),
                        ("d", "f"), ("e", "f"), ("c", "d"), ("b", "e")):
        graph.add_edge(left, right, p=float(matrix[ids.index(left), ids.index(right)]))
    return dict(g=graph, scores=PairScores(ids, matrix), truth={x: "A" if x < "d" else "B" for x in ids},
                method=method, budget=4, seed=7, noise=noise, fn_weight=1.)


def identity(args):
    return {"method": args["method"], "requested_budget": args["budget"],
            "seed": args["seed"], "noise": args["noise"], "fn_weight": args["fn_weight"],
            "input_sha256": "constructed-fixture-not-real-data"}


def observable(result):
    result = deepcopy(result)
    for key in ("seconds", "selection_seconds", "batch_timings", "telemetry_seconds"):
        result.pop(key, None)
    for decision in result["decisions"]:
        decision.pop("selection_seconds")
        # The planner reports measured internal phases, which cannot be equal.
        for key in list(decision["selection_info"]):
            if key.endswith("_seconds"):
                decision["selection_info"].pop(key)
    return result


@pytest.mark.parametrize("method", ["random", "cut_plan_fixed", "cut_plan_adaptive", "transclean_audit"])
@pytest.mark.parametrize("noise", [0., .4])
def test_enabled_journal_preserves_paid_sequence_scores_and_metrics(tmp_path, method, noise):
    args = arguments(method, noise)
    ordinary = run_audit(**args)
    path = tmp_path / "answers.jsonl"
    with AuditJournal(path, identity(args)) as journal:
        observed = run_audit(**args, checkpoint_callback=journal)
    assert observable(ordinary) == observable(observed)
    assert "telemetry_seconds" not in ordinary and observed["telemetry_seconds"] >= 0
    recovered = recover_journal(path, identity(args))
    assert recovered["paid_count_exact"] and recovered["confirmed_paid_answers"] == observed["spent"]
    assert recovered["trace"] == observed["trace"] and recovered["decisions"] == observed["decisions"]
    assert not recovered["completed_result_available"]  # Journal is not the result-transport contract.


def test_callback_cannot_mutate_selector_state_or_metrics():
    args = arguments("cut_plan_adaptive")
    expected = run_audit(**args)
    def corrupt_copy(event):
        if "decision" in event:
            event["decision"]["pair"][:] = ["not", "a-purchased-pair"]
            event["decision"]["selection_info"].clear()
        if "checkpoint" in event:
            event["checkpoint"].clear()
    actual = run_audit(**args, checkpoint_callback=corrupt_copy)
    assert observable(actual) == observable(expected)


def _pause_after_event(path, event_kind, ready):
    """Real child blocks only after a chosen event was durably written."""
    args = arguments()
    with AuditJournal(Path(path), identity(args)) as journal:
        def checkpoint(event):
            journal(event)
            spent = event.get("decision", event.get("checkpoint", {})).get("spent")
            if event["kind"] == event_kind and spent == 2:
                ready.set()
                time.sleep(60)
        run_audit(**args, checkpoint_callback=checkpoint)


@pytest.mark.parametrize("event_kind,trace_spent", [("answer", 1), ("checkpoint", 2)])
def test_real_worker_kill_recovers_receipt_and_only_evaluated_prefix(tmp_path, event_kind, trace_spent):
    context = mp.get_context("spawn")
    ready = context.Event()
    path = tmp_path / "killed.jsonl"
    child = context.Process(target=_pause_after_event, args=(str(path), event_kind, ready))
    child.start()
    try:
        assert ready.wait(20), "Fixture child failed to reach its durable checkpoint"
        child.kill()
        child.join(timeout=5)
        assert not child.is_alive() and child.exitcode != 0
    finally:
        if child.is_alive():
            child.kill()
            child.join(timeout=5)
    partial = recover_journal(path, identity(arguments()))
    assert partial["confirmed_paid_answers"] == 2
    assert partial["paid_count_lower_bound"] <= 2 <= partial["paid_count_upper_bound"] == 3
    assert not partial["paid_count_exact"] and not partial["completed_result_available"]
    assert partial["last_evaluated_checkpoint"]["spent"] == trace_spent
    assert len(partial["trace"]) == trace_spent + 1 and len(partial["decisions"]) == 2
    assert partial["terminal_marker"] is None


def _prefix(path, with_checkpoint=True):
    ident = identity(arguments())
    with AuditJournal(path, ident) as journal:
        journal({"kind": "initial", "checkpoint": {"spent": 0, "fp": 4, "fn": 1, "loss": 5}})
        journal({"kind": "answer", "decision": {"pair": ["a", "b"], "spent": 1, "observed_match": False}})
        if with_checkpoint:
            journal({"kind": "checkpoint", "checkpoint": {"spent": 1, "fp": 2, "fn": 1, "loss": 3}})
    return ident


def test_truncated_last_line_recovers_prefix_without_fill_forward(tmp_path):
    path = tmp_path / "tail.jsonl"
    ident = _prefix(path)
    path.write_bytes(path.read_bytes()[:-12])
    partial = recover_journal(path, ident)
    assert partial["journal_status"] == "truncated_tail" and partial["truncated_tail_bytes"] > 0
    assert partial["confirmed_paid_answers"] == 1 and partial["last_evaluated_checkpoint"]["spent"] == 0
    assert partial["paid_count_lower_bound"] == 1 and partial["paid_count_upper_bound"] == 2


def test_corrupted_complete_tail_and_wrong_identity_are_rejected(tmp_path):
    path = tmp_path / "corrupt.jsonl"
    ident = _prefix(path)
    with pytest.raises(ValueError, match="identity"):
        recover_journal(path, ident | {"method": "another-method"})
    lines = path.read_bytes().splitlines(keepends=True)
    last = json.loads(lines[-1]); last["event"]["checkpoint"]["fp"] = 999
    path.write_bytes(b"".join(lines[:-1]) + json.dumps(last).encode() + b"\n")
    with pytest.raises(ValueError, match="chain"):
        recover_journal(path, ident)


def test_missing_header_initial_checkpoint_and_spend_gap_are_distinct(tmp_path):
    path = tmp_path / "missing.jsonl"; ident = identity(arguments())
    assert recover_journal(path, ident)["journal_status"] == "missing_journal"
    path.write_bytes(b'{"schema":')
    assert recover_journal(path, ident)["journal_status"] == "missing_valid_header"
    header = tmp_path / "header.jsonl"
    with AuditJournal(header, ident):
        pass
    partial = recover_journal(header, ident)
    assert partial["journal_status"] == "missing_initial_checkpoint"
    assert partial["paid_count_lower_bound"] == partial["paid_count_upper_bound"] == 0
    gap = tmp_path / "gap.jsonl"
    with AuditJournal(gap, ident) as journal:
        journal({"kind": "initial", "checkpoint": {"spent": 0, "fp": 0, "fn": 0, "loss": 0}})
        journal({"kind": "answer", "decision": {"pair": ["a", "b"], "spent": 2, "observed_match": True}})
    with pytest.raises(ValueError, match="spend gap"):
        recover_journal(gap, ident)


def test_fsync_failure_aborts_before_another_query(tmp_path, monkeypatch):
    from cut_audit_er import telemetry
    args = arguments(); path = tmp_path / "io_failure.jsonl"
    fsync = telemetry.os.fsync; query = BudgetedOracle.query; counts = {"writes": 0, "queries": 0}
    def failing_fsync(fd):
        counts["writes"] += 1
        if counts["writes"] == 3:  # header, initial, first paid receipt
            raise OSError("Constructed fsync failure")
        fsync(fd)
    def count_query(self, u, v):
        counts["queries"] += 1
        return query(self, u, v)
    monkeypatch.setattr(telemetry.os, "fsync", failing_fsync)
    monkeypatch.setattr(BudgetedOracle, "query", count_query)
    with pytest.raises(OSError, match="fsync failure"):
        with AuditJournal(path, identity(args)) as journal:
            run_audit(**args, checkpoint_callback=journal)
    assert counts["queries"] == 1


def test_natural_worker_optional_journal_and_existing_path_protection(tmp_path):
    args = arguments(); ident = identity(args); path = tmp_path / "worker.jsonl"
    result = bounded_audit(args, 20, path, ident)
    assert result["status"] == "completed" and result["run"]["spent"] == 4
    assert result["checkpoint_telemetry"]["confirmed_paid_answers"] == 4
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        bounded_audit(args, 20, path, ident)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError, match="identity"):
        bounded_audit(args, 20, tmp_path / "wrong.jsonl", ident | {"requested_budget": 3})


def test_repeated_paid_pair_is_not_accepted_in_a_valid_hash_chain(tmp_path):
    path = tmp_path / "duplicate.jsonl"; ident = identity(arguments())
    with AuditJournal(path, ident) as journal:
        journal({"kind": "initial", "checkpoint": {"spent": 0, "fp": 0, "fn": 0, "loss": 0}})
        journal({"kind": "answer", "decision": {"pair": ["a", "b"], "spent": 1, "observed_match": True}})
        journal({"kind": "checkpoint", "checkpoint": {"spent": 1, "fp": 0, "fn": 0, "loss": 0}})
        journal({"kind": "answer", "decision": {"pair": ["b", "a"], "spent": 2, "observed_match": True}})
    with pytest.raises(ValueError, match="Repeated"):
        recover_journal(path, ident)


def test_terminal_journal_does_not_upgrade_worker_timeout(tmp_path, monkeypatch):
    from cut_audit_er import natural
    args = arguments(); ident = identity(args); path = tmp_path / "transport_timeout.jsonl"
    class Pipe:
        def close(self):
            pass
        def poll(self, timeout):
            return False
    class Process:
        pid = 123
        exitcode = None
        alive = False
        def start(self):
            _prefix(path)
            # A separately constructed valid terminal sequence represents a
            # computation that finished before its result transport was lost.
            data = path.read_bytes(); lines = data.splitlines(); previous = json.loads(lines[-1])["sha256"]
            body = {"schema": "cut-audit-answer-journal-v1", "seq": len(lines), "previous_sha256": previous,
                    "event": {"kind": "terminal", "spent": 1, "complete": True, "stop_reason": "no_action"}}
            canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            with path.open("ab") as handle:
                handle.write(json.dumps(body | {"sha256": hashlib.sha256(canonical).hexdigest()}).encode() + b"\n")
            self.alive = True
        def is_alive(self):
            return self.alive
        def terminate(self):
            self.alive = False; self.exitcode = -15
        def kill(self):
            self.terminate()
        def join(self, timeout):
            assert timeout <= 1
    class Context:
        def Pipe(self, duplex):
            return Pipe(), Pipe()
        def Process(self, **kwargs):
            return Process()
    monkeypatch.setattr(natural.mp, "get_context", lambda _: Context())
    result = bounded_audit(args, 0, path, ident)
    assert result["status"] == "timeout" and "run" not in result
    recovered = result["checkpoint_telemetry"]
    assert recovered["terminal_marker"]["complete"] and recovered["paid_count_exact"]
    assert not recovered["completed_result_available"]
