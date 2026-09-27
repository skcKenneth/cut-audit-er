"""Pair scores contain observed/model quantities only, never hidden truth."""
from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Sequence
import numpy as np
from .graph import Edge, separated_blocks
import networkx as nx

@dataclass
class PairScores:
    ids: tuple[str, ...]
    matrix: np.ndarray
    calls: int = 0
    index: dict[str, int] = field(init=False, repr=False)

    def __post_init__(self):
        self.ids = tuple(str(x) for x in self.ids)
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("Duplicate record IDs")
        self.matrix = np.asarray(self.matrix, dtype=float).copy()
        n = len(self.ids)
        if self.matrix.shape != (n, n) or not np.isfinite(self.matrix).all():
            raise ValueError("Invalid probability matrix shape or values")
        if (self.matrix < 0).any() or (self.matrix > 1).any():
            raise ValueError("Scores must be in [0,1]")
        if not np.allclose(self.matrix, self.matrix.T):
            raise ValueError("Scores must be symmetric")
        self.matrix.setflags(write=False)
        self.index = {x: i for i, x in enumerate(self.ids)}

    def p(self, u: str, v: str) -> float:
        self.calls += 1
        return float(self.matrix[self.index[u], self.index[v]])

    def cross_sum(self, a: Sequence[str], b: Sequence[str]) -> float:
        self.calls += len(a) * len(b)
        ai, bi = [self.index[x] for x in a], [self.index[x] for x in b]
        return float(self.matrix[np.ix_(ai, bi)].sum())

    def copy(self):
        return PairScores(self.ids, self.matrix)

def proxy_loss_reduction(g: nx.Graph, deletions: Sequence[Edge], scores: PairScores,
                         fn_weight: float) -> float:
    """Plug-in score, NOT a certified conditional expected loss reduction.

    Unconditional cross-pair marginals need not remain calibrated after adaptive
    selection or conditioning on queried labels. Gold is not accessed here.
    """
    if fn_weight < 0:
        raise ValueError("FN weight must be nonnegative")
    gain = 0.0
    for a, b in separated_blocks(g, deletions):
        gain += len(a) * len(b) - (1 + fn_weight) * scores.cross_sum(a, b)
    return gain
