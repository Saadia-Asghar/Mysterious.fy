"""M14 evaluation metrics. Pure functions over ground truth vs. predictions.

Numbers produced from these functions are results only when they come from a recorded run
(scripts/run_evaluation.py writes every input, parameter and output to experiments/runs/).
"""
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class PairScores:
    precision: float | None  # None: nothing was grouped, so precision is undefined
    recall: float | None     # None: nothing should have been grouped
    f1: float | None


def _same_group_pairs(groups: Iterable[Iterable[str]]) -> set[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for g in groups:
        for a, b in combinations(sorted(set(g)), 2):
            pairs.add(frozenset((a, b)))
    return pairs


def grouping_scores(truth: list[list[str]], predicted: list[list[str]]) -> PairScores:
    """Pairwise clustering quality: for every pair of events, should they share an incident?
    Precision: grouped pairs that truly belong together. Recall: true pairs that were grouped."""
    t, p = _same_group_pairs(truth), _same_group_pairs(predicted)
    precision = round(len(t & p) / len(p), 4) if p else None
    recall = round(len(t & p) / len(t), 4) if t else None
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0
    return PairScores(precision, recall, f1)


def top_k_hit(ranked: list[str], true_cause: str, k: int) -> bool:
    return true_cause in ranked[:k]


def alert_reduction(raw_alerts: int, incidents: int) -> float:
    """Percentage of raw alerts an operator no longer handles individually."""
    return round(100 * (1 - incidents / raw_alerts), 2) if raw_alerts else 0.0


def rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None
