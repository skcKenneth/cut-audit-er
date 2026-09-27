"""Finite runner fixtures verify consumed inputs, source pins and shared budgets."""
import json
from pathlib import Path

import pytest

from scripts.review_v5 import study as s
from scripts.review_v6 import audit_runner as r


def job(index=1, phase="natural"):
    dataset = "wdc" if phase == "natural" else "k1_uniform"
    return {"id": "fixture_state" + str(index), "run_id": "fixture", "dataset": dataset,
            "budget": 12, "batch": index, "phase": phase, "cohort": dataset if phase == "natural" else "synthetic",
            "worker_seconds": 120 if phase == "natural" else 30,
            "suite_seconds": 2700 if phase == "natural" else 900}


@pytest.mark.parametrize("field,value", [("worker_seconds", 121), ("suite_seconds", 2701), ("cohort", "new_group"), ("batch", 0), ("phase", "test")])
def test_fixed_job_scope_and_resources_rejected(field, value):
    bad = job(); bad[field] = value
    with pytest.raises(ValueError): r.validate_jobs([bad])


def test_duplicate_job_is_not_an_independent_attempt():
    with pytest.raises(ValueError, match="Duplicate"): r.validate_jobs([job(), job()])


def test_bound_sources_reject_corruption_even_with_correct_manifest_hash(tmp_path):
    (tmp_path / "engine.py").write_text("pinned source", encoding="utf-8")
    (tmp_path / "data.json").write_text("{}", encoding="utf-8")
    manifest = {"code_sha256": {"engine.py": s.digest(tmp_path / "engine.py")},
                "files_sha256": {"data.json": s.digest(tmp_path / "data.json")}}
    s.write(tmp_path / "manifest.json", manifest)
    pin = s.digest(tmp_path / "manifest.json")
    assert r.checked_manifest(tmp_path / "manifest.json", pin, root=tmp_path) == manifest
    (tmp_path / "data.json").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Source hash mismatch"): r.checked_manifest(tmp_path / "manifest.json", pin, root=tmp_path)


@pytest.mark.parametrize("case", ["spent", "unknown", "technical"])
def test_evaluator_shares_visible_budget_and_keeps_unresolved_slots(tmp_path, monkeypatch, case):
    source = tmp_path / "visible" / "manifest.json"; source.parent.mkdir()
    refs = tmp_path / "references" / "manifest.json"; refs.parent.mkdir()
    vjob = {**job(), "status": "passed" if case != "unknown" else "timeout_unknown", "result_file": "states/a.json"}
    vm = {"schema": "cut-audit-v6-visible-suite-v1", "rows": [vjob],
          "source_manifest_sha256": "a" * 64, "code_sha256": {"engine.py": "hash"},
          "files_sha256": {"source.json": "hash"}, "cohort_charged_seconds": {"wdc": 2700. if case == "spent" else 2690.}}
    em = {"visible_input_manifest_sha256": "a" * 64, "code_sha256": {"engine.py": "hash"}, "files_sha256": {"reference.json": "hash"}}
    source.write_text("{}", encoding="utf-8"); refs.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(r, "ROOT", tmp_path)
    monkeypatch.setattr(r, "checked_manifest", lambda path, *args, **kwargs: vm if Path(path) == source else em)
    monkeypatch.setattr(s, "check_hashes", lambda *args: None)
    calls = []
    def process(command, folder, limit):
        calls.append(limit)
        return {"exit_code": 2, "timed_out": False, "wall_seconds": 1.}
    monkeypatch.setattr(r, "run_process", process)
    report = r.run_suite("evaluate", source, "b" * 64, tmp_path / "out", reference_manifest=refs, reference_hash="c" * 64)
    saved = s.read(tmp_path / "out/manifest.json")
    if case == "spent":
        assert calls == [] and saved["rows"][0]["status"] == "not_started_suite_limit"
        assert report["unknown_states"] == 1
    elif case == "unknown":
        assert calls == [] and saved["rows"][0]["status"] == "unknown_visible_not_completed"
    else:
        assert 0 < calls[0] <= 10. and report["technical_mismatch_count"] == 1
        assert report["status"] == "failed" and saved["cohort_charged_seconds"]["wdc"] > 2690.
        assert saved["rows"][0]["state_charged_seconds"] > 0
    with pytest.raises(ValueError, match="already consumed"):
        r.run_suite("evaluate", source, "b" * 64, tmp_path / "second_attempt", reference_manifest=refs, reference_hash="c" * 64)


def test_source_pin_can_not_be_omitted(tmp_path):
    manifest = {"code_sha256": {}, "files_sha256": {}}
    s.write(tmp_path / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Empty source manifest"):
        r.checked_manifest(tmp_path / "manifest.json", s.digest(tmp_path / "manifest.json"), root=tmp_path)
