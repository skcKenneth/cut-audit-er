"""Constructed visual contracts; no acquisitions or private assets are opened."""
import importlib.util
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("public_v5_figures_fixture", ROOT / "scripts/make_figures.py")
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)


def test_all_synthetic_reference_slots_and_missing_cell_stay_visible(tmp_path):
    endpoints = [dict(reference=h, dataset=f"k{k}_{p}", method=m, budget=b,
                      status="completed", loss=9)
                 for h in ("H0", "H9") for k in (1, 2, 3) for p in ("uniform", "ranked")
                 for m in f.SYNTHETIC for b in (1, 2, 3, 4, 6)]
    endpoints[0].update(status="interrupted", loss=None)
    f.style()
    fig, projection = f.synthetic(endpoints)
    arrays = [ax.images[0].get_array() for ax in fig.axes]
    assert sum(a.size for a in arrays) == 300
    assert sum(np.ma.getmaskarray(a).sum() for a in arrays) == 1
    assert sum(bool(p.get_hatch()) for ax in fig.axes for p in ax.patches) == 1
    assert projection["independent_reference_evaluations"] is False
    assert projection["endpoints"][0]["loss"] is None
    (tmp_path / "data").mkdir()
    receipt = f.save(fig, tmp_path, "synthetic_fixture", projection)
    assert receipt["minimum_font_pt"] >= 8 and receipt["text_bounds_within_canvas"]


def test_all_reserved_natural_slots_are_missing_not_zero(tmp_path):
    endpoints = [dict(dataset=d, method=m, budget=b, status="not_started_gate", loss=None)
                 for d in (*f.DATASETS, "alaska_camera") for m in f.METHODS for b in (12, 24, 48)]
    f.style()
    fig, projection = f.natural(endpoints, [])
    assert len(projection["acquisitions"]) == 84
    assert sum(np.ma.getmaskarray(ax.images[0].get_array()).sum() for ax in fig.axes) == 84
    assert sum(bool(p.get_hatch()) for ax in fig.axes for p in ax.patches) == 84
    assert all(r["loss"] is None for r in projection["acquisitions"])
    (tmp_path / "data").mkdir()
    receipt = f.save(fig, tmp_path, "natural_fixture", projection)
    assert receipt["minimum_font_pt"] >= 8 and receipt["text_bounds_within_canvas"]


def test_schematic_rebuild_is_byte_identical(tmp_path):
    hashes = []
    f.style()
    for run in ("first", "second"):
        folder = tmp_path / run
        (folder / "data").mkdir(parents=True)
        fig, projection = f.contract()
        hashes.append(f.save(fig, folder, "schematic", projection)["files_sha256"])
    assert hashes[0] == hashes[1]
