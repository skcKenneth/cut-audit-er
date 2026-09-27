"""Finite runner fault injections; never invokes a formal dataset worker."""
from copy import deepcopy
import hashlib
import json
import pytest
from scripts.review_v5 import study as s


class Copyable:
    def copy(self): return Copyable()


def grid():
    return [{"id": f"{d}_{i}", "dataset": d, "method": "edge_betweenness", "budget": 1,
             "status": "not_started"} for i in range(2) for d in ("wdc", "dblp_acm")]


def assets(): return {d: (Copyable(), Copyable(), {"x": "A"}) for d in ("wdc", "dblp_acm")}


class Clock:
    def __init__(self): self.value = 0.
    def __call__(self): return self.value


def completed(*_): return {"status": "completed", "run": {"complete": True}}


def test_fixed_grids_and_types():
    assert len(s.slots("synthetic")) == 150
    assert len(s.slots("natural")) == 63
    assert s.slots("natural")[0]["dataset"] == "wdc"
    assert s.slots("natural")[7]["dataset"] == "dblp_acm"
    assert s.slots("natural")[21]["budget"] == 24
    altered = s.fixed_config(); altered["candidate_cap"] = 64.0
    with pytest.raises(ValueError): s.validate_config(altered)


@pytest.mark.parametrize("path", ["../a", "a/../b", "/root", "a\\b", "C:/b", "a//b"])
def test_unsafe_paths_rejected(tmp_path, path):
    with pytest.raises(ValueError): s.relative(tmp_path, path)


def test_sources_ignore_future_delivery_modules(tmp_path):
    (tmp_path/"scripts/review_v5").mkdir(parents=True)
    (tmp_path/"src/cut_audit_er").mkdir(parents=True)
    before = s.source_names(tmp_path)
    (tmp_path/"scripts/review_v5/package.py").write_text("pass")
    assert before == s.source_names(tmp_path)


def test_source_hash_mismatch_rejects(tmp_path):
    path = tmp_path/"source.py"; path.write_text("old")
    pins = {"source.py": s.digest(path)}; path.write_text("changed")
    with pytest.raises(ValueError, match="hash mismatch"): s.check_hashes(tmp_path, pins)


def test_each_cell_once_cold_and_existing_output_rejected(tmp_path):
    calls = []
    def audit(arguments, seconds, journal, identity):
        calls.append((id(arguments["g"]), identity["run_id"], seconds))
        return completed()
    out = tmp_path/"study"
    result = s.execute_grid(out, "natural", grid(), assets(), "a"*64, audit_fn=audit)
    assert [c[1] for c in calls] == [x["id"] for x in grid()]
    assert result["status"] == "completed"
    with pytest.raises(FileExistsError): s.execute_grid(out, "natural", grid(), assets(), "a"*64, audit_fn=audit)
    s.execute_grid(out, "natural", grid(), assets(), "a"*64, audit_fn=audit, continue_run=True)
    assert len(calls) == 4


def test_interleaved_per_graph_budget_does_not_reset(tmp_path):
    clock = Clock(); calls = []
    def audit(arguments, seconds, journal, identity):
        calls.append((identity["run_id"], seconds)); clock.value += 2701 if identity["dataset"] == "wdc" else 5
        return completed()
    result = s.execute_grid(tmp_path/"study", "natural", grid(), assets(), "a"*64, audit_fn=audit, clock=clock)
    assert [r["status"] for r in result["runs"]] == ["completed", "completed", "not_started_limit", "completed"]
    assert len(calls) == 3
    assert result["active_elapsed_seconds"]["wdc"] >= 2701


def test_timeout_not_retried_and_missing_kept(tmp_path):
    calls = []
    def audit(*args): calls.append(1); return {"status": "timeout"}
    result = s.execute_grid(tmp_path/"study", "natural", grid(), assets(), "a"*64, audit_fn=audit)
    assert len(calls) == 4 and all(r["status"] == "timeout" for r in result["runs"])
    assert result["status"] == "completed_with_missing"


def test_interrupt_requires_proof_and_only_continues_never_started(tmp_path):
    out = tmp_path/"study"; clock = Clock()
    def interrupt(*args): raise KeyboardInterrupt("fixture supervisor loss")
    with pytest.raises(KeyboardInterrupt):
        s.execute_grid(out, "natural", grid(), assets(), "a"*64, audit_fn=interrupt, clock=clock, epoch=lambda:100)
    with pytest.raises(ValueError, match="absence"):
        s.execute_grid(out, "natural", grid(), assets(), "a"*64, audit_fn=completed, continue_run=True)
    _, _, pending = s.ledger_state(out, grid())
    proof = tmp_path/"proof.json"
    s.write(proof, {"status":"confirmed_absent", "scope":"V5_workers_and_supervisor", "active_python_workers":0,
                    "launch_identity_sha256":hashlib.sha256(s.blob(pending)).hexdigest(), "checked_epoch_seconds":200})
    result = s.execute_grid(out, "natural", grid(), assets(), "a"*64, audit_fn=completed,
        continue_run=True, absence_receipt=proof, epoch=lambda:300, clock=clock)
    assert [r["status"] for r in result["runs"]] == ["interrupted", "completed", "completed", "completed"]
    assert result["active_elapsed_seconds"]["wdc"] == 200
    assert (out/"recovery"/(grid()[0]["id"]+".process_absence.json")).read_bytes() == proof.read_bytes()
    assert len([e for e in s.ledger_events(out) if e["kind"] == "launch"]) == 4


def test_ledger_tamper_and_changed_continuation_scope_rejected(tmp_path):
    out = tmp_path/"study"
    s.execute_grid(out, "natural", grid(), assets(), "a"*64, audit_fn=completed)
    with pytest.raises(ValueError, match="scope/freeze"):
        s.execute_grid(out, "natural", grid(), assets(), "b"*64, audit_fn=completed, continue_run=True)
    path=out/"ledger/000000.json"; value=s.read(path); value["remaining_before"]=1; path.write_bytes(s.blob(value))
    with pytest.raises(ValueError, match="hash chain"): s.ledger_events(out)


def test_cleanup_failure_prevents_next_worker(tmp_path):
    calls=[]
    def failed(*args): calls.append(1); return {"status":"cleanup_failed", "cleanup_worker_still_alive":True}
    with pytest.raises(ValueError, match="Worker still alive"):
        s.execute_grid(tmp_path/"study", "natural", grid(), assets(), "a"*64, audit_fn=failed)
    assert calls==[1]
    assert s.read(tmp_path/"study/suite.json")["status"]=="interrupted"


def test_preparation_limit_never_starts_worker(tmp_path):
    clock=Clock(); calls=[]
    def before(): clock.value += 3000
    result=s.execute_grid(tmp_path/"study", "natural", grid(), assets(), "a"*64,
        audit_fn=lambda *_:calls.append(1), clock=clock, before_cell=before)
    assert not calls and all(r["status"]=="not_started_limit" for r in result["runs"])
