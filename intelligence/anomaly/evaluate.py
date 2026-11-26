"""Evaluation helpers for M10/M14. Inputs must come from real or recorded experiment runs;
never report numbers from these functions without saving the run that produced them."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Scores:
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int

    @property
    def precision(self) -> float:
        d = self.true_positives + self.false_positives
        return self.true_positives / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.true_positives + self.false_negatives
        return self.true_positives / d if d else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def confusion(predicted: list[bool], actual: list[bool]) -> Scores:
    if len(predicted) != len(actual):
        raise ValueError("predicted and actual must be the same length")
    pairs = list(zip(predicted, actual))
    return Scores(
        true_positives=sum(p and a for p, a in pairs),
        false_positives=sum(p and not a for p, a in pairs),
        false_negatives=sum(a and not p for p, a in pairs),
        true_negatives=sum(not p and not a for p, a in pairs),
    )
