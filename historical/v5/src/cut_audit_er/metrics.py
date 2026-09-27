"""Gold-label access is restricted to evaluation, never policy selection."""
from __future__ import annotations
from collections import Counter
from collections.abc import Mapping
import networkx as nx

def choose2(n: int) -> int:
    return n * (n-1) // 2

def evaluate(g: nx.Graph, truth: Mapping[str, str], fn_weight: float = 1.0) -> dict:
    if set(g.nodes) != set(truth):
        raise ValueError("Every record, including isolates, must have a gold label")
    if fn_weight < 0 or len(truth) < 2:
        raise ValueError("Need >=2 records and nonnegative FN weight")
    gold_counts = Counter(truth.values())
    gold_pairs = sum(choose2(x) for x in gold_counts.values())
    tp = predicted = 0
    bp = br = 0.0
    largest_impure = 0
    for comp in nx.connected_components(g):
        c = Counter(truth[v] for v in comp)
        predicted += choose2(len(comp))
        tp += sum(choose2(x) for x in c.values())
        bp += sum(x*x/len(comp) for x in c.values())
        br += sum(x*x/gold_counts[y] for y, x in c.items())
        if len(c) > 1:
            largest_impure = max(largest_impure, len(comp))
    fp, fn = predicted - tp, gold_pairs - tp
    precision = tp/predicted if predicted else 1.0
    recall = tp/gold_pairs if gold_pairs else 1.0
    f1 = 2*precision*recall/(precision+recall) if precision+recall else 0.0
    bp, br = bp/len(truth), br/len(truth)
    return {"tp":tp, "fp":fp, "fn":fn, "precision":precision, "recall":recall,
            "pair_f1":f1, "b3_precision":bp, "b3_recall":br,
            "b3_f1":2*bp*br/(bp+br) if bp+br else 0.0,
            "loss":fp+fn_weight*fn, "normalized_loss":(fp+fn_weight*fn)/choose2(len(truth)),
            "largest_impure_component":largest_impure, "n_records":len(truth),
            "n_edges":g.number_of_edges(), "n_components":nx.number_connected_components(g)}
