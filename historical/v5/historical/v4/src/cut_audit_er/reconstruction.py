"""Explicit exact-array replay and numerical reconstruction contracts.

No matcher, oracle, evaluator, or hidden entity labels enter this module. A
numerical pass establishes only the declared score comparison, not selector or
query-sequence equivalence. Existing historical hash guards remain separate.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Mapping

import networkx as nx
import numpy as np


ATOL = 1e-12
RTOL = 1e-10
MODES = ("exact_archival", "numerical_validation")
IDENTITY_FIELDS = frozenset(("dataset", "partition", "source_sha256",
                             "config_sha256", "data_sha256", "split_sha256"))
ARRAY_FILES = {"edge_indices": "edge_indices.npy",
               "edge_probabilities": "edge_probabilities.npy",
               "dense_probabilities": "dense_probabilities.npy",
               "neighbor_offsets": "neighbor_offsets.npy",
               "neighbor_indices": "neighbor_indices.npy"}
SCHEMA = "cut-audit-scored-graph-arrays-v1"


def digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _identity(value: Mapping[str, str]) -> dict[str, str]:
    result = dict(value)
    if set(result) != IDENTITY_FIELDS:
        raise ValueError("Identity requires exactly dataset, partition and source/config/data/split hashes")
    for key, val in result.items():
        if not isinstance(val, str) or not val or len(val) > 128:
            raise ValueError("Identity values must be nonempty bounded strings")
        if key.endswith("_sha256") and not re.fullmatch(r"[0-9a-f]{64}", val):
            raise ValueError("Identity hashes must be lowercase SHA-256")
    return result


def _array(value, *, floating: bool) -> np.ndarray:
    array = np.asarray(value)
    if floating:
        if array.dtype.kind != "f" or array.dtype.itemsize != 8:
            raise ValueError("Scores must already be float64; no precision conversion or rounding")
        if not np.isfinite(array).all() or ((array < 0) | (array > 1)).any():
            raise ValueError("Scores must be finite probabilities in [0,1]")
        result = np.array(array, dtype="<f8", order="C", copy=True)
    else:
        if array.dtype.kind not in "iu" or (array < 0).any():
            raise ValueError("Graph arrays must contain nonnegative integer indices")
        result = np.array(array, dtype="<i8", order="C", copy=True)
        if not np.array_equal(array, result):
            raise ValueError("Graph index overflow")
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class ScoredGraphArrays:
    """Label-free graph/score representation. Missing dense reference is explicit.

    Historical edge-only references may omit dense probabilities and neighbor
    order. They cannot be saved or accepted as an exact full archival replay.
    """
    record_ids: tuple[str, ...]
    edge_indices: np.ndarray
    edge_probabilities: np.ndarray
    identity: Mapping[str, str]
    dense_probabilities: np.ndarray | None = None
    neighbor_offsets: np.ndarray | None = None
    neighbor_indices: np.ndarray | None = None

    def __post_init__(self):
        ids = tuple(self.record_ids)
        if len(ids) > 1500 or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError("Expected unique nonempty record IDs, at most 1500")
        identity = _identity(self.identity)
        edges = _array(self.edge_indices, floating=False)
        probabilities = _array(self.edge_probabilities, floating=True)
        n = len(ids)
        if edges.ndim != 2 or edges.shape[1] != 2 or probabilities.shape != (len(edges),):
            raise ValueError("Misaligned edge arrays")
        if len(edges) and ((edges >= n).any() or (edges[:, 0] >= edges[:, 1]).any()):
            raise ValueError("Edges must have distinct ascending in-range endpoints")
        tuples = [tuple(x) for x in edges.tolist()]
        if tuples != sorted(set(tuples)):
            raise ValueError("Edge indices must be unique and lexicographically ordered")
        dense = None
        if self.dense_probabilities is not None:
            dense = _array(self.dense_probabilities, floating=True)
            if dense.shape != (n, n) or not np.array_equal(dense, dense.T):
                raise ValueError("Dense scores must be exactly symmetric and aligned")
            if not np.array_equal(np.diag(dense), np.ones(n)):
                raise ValueError("Dense diagonal must equal one")
            if len(edges) and not np.array_equal(dense[edges[:, 0], edges[:, 1]], probabilities):
                raise ValueError("Graph edge probabilities disagree with dense scores")
        offsets, neighbors = None, None
        if (self.neighbor_offsets is None) != (self.neighbor_indices is None):
            raise ValueError("Neighbor order arrays must be supplied together")
        if self.neighbor_offsets is not None:
            offsets = _array(self.neighbor_offsets, floating=False)
            neighbors = _array(self.neighbor_indices, floating=False)
            if offsets.shape != (n+1,) or neighbors.ndim != 1 or offsets[0] != 0 or offsets[-1] != len(neighbors):
                raise ValueError("Invalid neighbor-order offsets")
            if (np.diff(offsets) < 0).any() or len(neighbors) != 2*len(edges):
                raise ValueError("Neighbor order does not cover graph")
            expected = [set() for _ in ids]
            for a, b in tuples:
                expected[a].add(b); expected[b].add(a)
            for i in range(n):
                row = neighbors[offsets[i]:offsets[i+1]].tolist()
                if len(set(row)) != len(row) or set(row) != expected[i]:
                    raise ValueError("Neighbor-order topology mismatch")
        for key, value in (("record_ids", ids), ("identity", MappingProxyType(identity)),
                           ("edge_indices", edges), ("edge_probabilities", probabilities),
                           ("dense_probabilities", dense), ("neighbor_offsets", offsets),
                           ("neighbor_indices", neighbors)):
            object.__setattr__(self, key, value)


def capture_scored_graph(graph: nx.Graph, scores, identity: Mapping[str, str]) -> ScoredGraphArrays:
    """Capture only visible scores/IDs. Reject graph attributes hiding evaluator data."""
    if graph.is_directed() or graph.is_multigraph() or nx.number_of_selfloops(graph):
        raise ValueError("Expected a simple undirected graph")
    if graph.graph or any(attrs for _, attrs in graph.nodes(data=True)):
        raise ValueError("Graph and node attributes are forbidden in selector artifacts")
    if any(set(attrs) != {"p"} for _, _, attrs in graph.edges(data=True)):
        raise ValueError("Only the explicit visible probability p is allowed on edges")
    ids = tuple(scores.ids)
    if tuple(graph.nodes) != ids:
        raise ValueError("Graph node order must match score record order exactly")
    index = {name: i for i, name in enumerate(ids)}
    edges = sorted((min(index[u], index[v]), max(index[u], index[v])) for u, v in graph.edges)
    offsets, neighbors = [0], []
    for u in ids:
        neighbors.extend(index[v] for v in graph.neighbors(u))
        offsets.append(len(neighbors))
    return ScoredGraphArrays(ids, np.array(edges, dtype=np.int64).reshape(-1, 2),
        np.array([graph[ids[a]][ids[b]]["p"] for a, b in edges], dtype=np.float64),
        identity, scores.matrix, np.array(offsets, dtype=np.int64),
        np.array(neighbors, dtype=np.int64))


def restore_graph(arrays: ScoredGraphArrays) -> nx.Graph:
    """Restore original neighbor iteration order using edge precedence constraints."""
    if arrays.neighbor_offsets is None:
        raise ValueError("Exact graph replay requires archived neighbor order")
    edges = [tuple(row) for row in arrays.edge_indices.tolist()]
    precedence = nx.DiGraph(); precedence.add_nodes_from(edges)
    for i in range(len(arrays.record_ids)):
        neighbors = arrays.neighbor_indices[arrays.neighbor_offsets[i]:arrays.neighbor_offsets[i+1]]
        ordered = [tuple(sorted((i, int(j)))) for j in neighbors]
        precedence.add_edges_from(zip(ordered, ordered[1:]))
    try:
        insertion = list(nx.lexicographical_topological_sort(precedence))
    except nx.NetworkXUnfeasible as exc:
        raise ValueError("Archived neighbor order cannot arise from a shared edge insertion order") from exc
    values = dict(zip(edges, arrays.edge_probabilities))
    graph = nx.Graph(); graph.add_nodes_from(arrays.record_ids)
    for a, b in insertion:
        graph.add_edge(arrays.record_ids[a], arrays.record_ids[b], p=float(values[a, b]))
    for i, name in enumerate(arrays.record_ids):
        expected = [arrays.record_ids[j] for j in arrays.neighbor_indices[
            arrays.neighbor_offsets[i]:arrays.neighbor_offsets[i+1]]]
        if list(graph.neighbors(name)) != expected:
            raise ValueError("Restored neighbor order differs")
    return graph


class ReconstructionMismatch(ValueError):
    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report


def _differences(reference, candidate, *, atol, rtol):
    delta = np.abs(candidate-reference)
    positive = reference != 0
    zero_changed = int(np.count_nonzero((~positive) & (delta != 0)))
    relative = delta[positive]/np.abs(reference[positive])
    bound = atol + rtol*np.abs(reference)
    ratio = (float((delta/bound).max(initial=0)) if np.all(bound > 0)
             else (None if np.any(delta > 0) else 0.0))
    return {"entries": int(reference.size), "exact_bytes_equal": reference.tobytes() == candidate.tobytes(),
            "unequal_value_count": int(np.count_nonzero(reference != candidate)),
            "max_absolute_difference": float(delta.max(initial=0)),
            "max_finite_relative_difference": float(relative.max(initial=0)),
            "nonzero_differences_at_zero_reference": zero_changed,
            "relative_difference_infinite": bool(zero_changed),
            "max_tolerance_ratio": ratio,
            "above_tolerance_count": int(np.count_nonzero(delta > bound))}


def validate_reconstruction(reference: ScoredGraphArrays, candidate: ScoredGraphArrays,
                            *, mode: str) -> dict:
    """Identity/topology are exact in both modes. Tolerances cannot be overridden."""
    if mode not in MODES:
        raise ValueError("Explicit supported reconstruction mode required")
    if dict(reference.identity) != dict(candidate.identity):
        raise ReconstructionMismatch("Exact source/config/data/split identity changed")
    if reference.record_ids != candidate.record_ids:
        raise ReconstructionMismatch("Ordered record identity changed")
    if not np.array_equal(reference.edge_indices, candidate.edge_indices):
        raise ReconstructionMismatch("Exact graph topology changed")
    dense_available = reference.dense_probabilities is not None and candidate.dense_probabilities is not None
    if reference.dense_probabilities is not None and candidate.dense_probabilities is None:
        raise ReconstructionMismatch("Candidate dropped available dense scores")
    if mode == "exact_archival" and (not dense_available or reference.neighbor_offsets is None or candidate.neighbor_offsets is None):
        raise ReconstructionMismatch("Exact archival mode requires complete dense arrays and neighbor order")
    order_equal = (reference.neighbor_offsets is not None and candidate.neighbor_offsets is not None
                   and np.array_equal(reference.neighbor_offsets, candidate.neighbor_offsets)
                   and np.array_equal(reference.neighbor_indices, candidate.neighbor_indices))
    atol, rtol = (0.0, 0.0) if mode == "exact_archival" else (ATOL, RTOL)
    report = {"mode": mode, "identity_exact": True, "topology_exact": True,
              "atol": atol, "rtol": rtol,
              "tolerance_rule": "abs(candidate-reference) <= atol + rtol*abs(reference)",
              "edge_probabilities": _differences(reference.edge_probabilities, candidate.edge_probabilities, atol=atol, rtol=rtol),
              "dense_probabilities": _differences(reference.dense_probabilities, candidate.dense_probabilities, atol=atol, rtol=rtol) if dense_available else None,
              "dense_comparison_scope": "all_pairs" if dense_available else "unavailable_historical_reference; edges_only",
              "neighbor_order_equal": bool(order_equal), "selector_equivalence_asserted": False}
    checked = [report["edge_probabilities"]] + ([report["dense_probabilities"]] if dense_available else [])
    accepted = (all(item["exact_bytes_equal"] for item in checked) and order_equal
                if mode == "exact_archival" else all(item["above_tolerance_count"] == 0 for item in checked))
    report["accepted"] = bool(accepted)
    if not accepted:
        raise ReconstructionMismatch("Reconstruction differs under the explicit mode", report)
    return report


def save_archive(folder: str | Path, arrays: ScoredGraphArrays) -> dict:
    """Create fresh label-free artifacts. Keep returned manifest hash externally."""
    if arrays.dense_probabilities is None or arrays.neighbor_offsets is None:
        raise ValueError("Archive requires full dense scores and neighbor order")
    restore_graph(arrays)  # Validate replayability before writing anything.
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    (folder/"record_ids.json").write_bytes(_json_bytes(list(arrays.record_ids)))
    for field, name in ARRAY_FILES.items():
        with (folder/name).open("xb") as stream:
            np.save(stream, getattr(arrays, field), allow_pickle=False)
    files = {name: {"sha256": digest(folder/name), "bytes": (folder/name).stat().st_size}
             for name in ("record_ids.json", *ARRAY_FILES.values())}
    manifest = {"schema": SCHEMA, "identity": dict(arrays.identity), "files": files,
                "nodes": len(arrays.record_ids), "edges": len(arrays.edge_indices),
                "float_storage": "little_endian_float64; no rounding", "contains_gold_labels": False,
                "selector_equivalence_asserted": False}
    (folder/"manifest.json").write_bytes(_json_bytes(manifest))
    return {"manifest_sha256": digest(folder/"manifest.json"), "files": files}


def load_archive(folder: str | Path, *, expected_manifest_sha256: str,
                 expected_identity: Mapping[str, str], mode: str) -> ScoredGraphArrays:
    """Exact artifact load only. Numerical compatibility never relaxes file hashes."""
    if mode != "exact_archival":
        raise ValueError("Archive loading requires explicit exact_archival mode")
    folder = Path(folder)
    expected_files = {"manifest.json", "record_ids.json", *ARRAY_FILES.values()}
    if folder.is_symlink() or (hasattr(folder, "is_junction") and folder.is_junction()):
        raise ValueError("Aliased archive directory rejected")
    if {p.name for p in folder.iterdir()} != expected_files:
        raise ValueError("Unexpected/missing archive files")
    if any(not p.is_file() or p.is_symlink() for p in folder.iterdir()):
        raise ValueError("Only regular archive files are allowed")
    if digest(folder/"manifest.json") != expected_manifest_sha256:
        raise ReconstructionMismatch("Pinned archive manifest hash changed")
    manifest = json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    expected_keys = {"schema", "identity", "files", "nodes", "edges", "float_storage",
                     "contains_gold_labels", "selector_equivalence_asserted"}
    if set(manifest) != expected_keys or manifest["schema"] != SCHEMA or set(manifest["files"]) != expected_files - {"manifest.json"}:
        raise ValueError("Unexpected archive schema")
    if _identity(manifest["identity"]) != _identity(expected_identity):
        raise ReconstructionMismatch("Pinned archive identity changed")
    if manifest["contains_gold_labels"] is not False or manifest["selector_equivalence_asserted"] is not False:
        raise ValueError("Invalid archive claim fields")
    n = manifest["nodes"]
    if type(n) is not int or not 0 <= n <= 1500:
        raise ValueError("Archive exceeds existing graph-size limit")
    for name, entry in manifest["files"].items():
        path = folder/name
        if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            raise ReconstructionMismatch("Archived array hash or size changed: " + name)
        if path.stat().st_size > 20*1024*1024:
            raise ValueError("Archive payload unexpectedly large")
    ids = json.loads((folder/"record_ids.json").read_text(encoding="utf-8"))
    values = {field: np.load(folder/name, allow_pickle=False) for field, name in ARRAY_FILES.items()}
    arrays = ScoredGraphArrays(tuple(ids), identity=manifest["identity"], **values)
    if len(ids) != n or len(arrays.edge_indices) != manifest["edges"]:
        raise ValueError("Manifest graph counts disagree with arrays")
    restore_graph(arrays)
    return arrays
