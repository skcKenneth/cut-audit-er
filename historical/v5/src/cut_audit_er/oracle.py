"""Budgeted offline label oracle, not a claim to have recruited human annotators."""
from __future__ import annotations
import hashlib
from collections.abc import Mapping
from .graph import Edge, edge_key

class BudgetedOracle:
    def __init__(self, truth: Mapping[str, str], budget: int, noise: float = 0.0, seed: int = 0):
        if not isinstance(budget, int) or budget < 0 or not 0 <= noise <= 1:
            raise ValueError("Invalid budget/noise")
        self.__truth = dict(truth)
        self.budget, self.noise, self.seed = budget, noise, seed
        self.spent = 0
        self.observed: dict[Edge, bool] = {}

    @property
    def remaining(self):
        return self.budget - self.spent

    def query(self, u: str, v: str) -> bool:
        e = edge_key(u, v)
        if e in self.observed:
            raise ValueError("Repeated queries are forbidden in this protocol")
        if self.remaining < 1:
            raise RuntimeError("Label budget exhausted")
        if u not in self.__truth or v not in self.__truth:
            raise KeyError("Unknown record ID")
        answer = self.__truth[u] == self.__truth[v]
        # Common random numbers across policies; independent of query ordering.
        digest = hashlib.sha256(f"{self.seed}|{e[0]}|{e[1]}".encode()).digest()
        flip = int.from_bytes(digest[:8], "big") / 2**64 < self.noise
        answer = bool(answer != flip)
        self.observed[e] = answer
        self.spent += 1
        return answer
