"""Evaluation-harness correctness, pinned to hand-computed values."""
from __future__ import annotations

import math

from core.metrics import (
    hungarian_min,
    info_metrics,
    labelled_metrics,
    pair_metrics,
)


def test_ari_perfect_agreement():
    p = {"a": "X", "b": "X", "c": "Y", "d": "Y"}
    t = {"a": "1", "b": "1", "c": "2", "d": "2"}
    m = pair_metrics(p, t)
    assert m.adjusted_rand_index == 1.0
    assert m.f1 == 1.0


def test_ari_relabel_invariant():
    # ARI must be invariant to cluster relabelling
    p = {"a": "Z", "b": "Z", "c": "Q", "d": "Q"}
    t = {"a": "1", "b": "1", "c": "2", "d": "2"}
    assert pair_metrics(p, t).adjusted_rand_index == 1.0


def test_ari_worse_than_random_is_negative():
    p = {"a": "X", "b": "Y", "c": "X", "d": "Y"}
    t = {"a": "1", "b": "1", "c": "2", "d": "2"}
    assert pair_metrics(p, t).adjusted_rand_index < 0


def test_nmi_bounds():
    p = {"a": "X", "b": "X", "c": "Y", "d": "Y"}
    t = {"a": "1", "b": "1", "c": "2", "d": "2"}
    im = info_metrics(p, t)
    assert math.isclose(im.normalized_mutual_information, 1.0, abs_tol=1e-9)
    assert im.homogeneity == 1.0 and im.completeness == 1.0


def test_hungarian_optimal():
    cost = [[1, 2, 3], [3, 3, 3], [3, 3, 2]]
    match = hungarian_min(cost)
    total = sum(cost[r][c] for r, c in match.items())
    assert total == 6  # optimal assignment 0->0,1->1,2->2


def test_hungarian_rectangular():
    # more columns than rows: every row assigned to a distinct column
    cost = [[4, 1, 3, 9], [2, 0, 5, 7]]
    match = hungarian_min(cost)
    assert len(match) == 2
    assert len(set(match.values())) == 2


def test_labelled_prf_with_error():
    pred = {"a": "S1", "b": "S1", "c": "S2", "d": "S2", "e": "S2"}
    truth = {"a": "A", "b": "A", "c": "B", "d": "B", "e": "A"}
    lm = labelled_metrics(pred, truth)
    assert lm.mapping == {"A": "S1", "B": "S2"}
    scores = {s.truth_service: s for s in lm.per_service}
    assert math.isclose(scores["A"].precision, 1.0)
    assert math.isclose(scores["A"].recall, 2 / 3)


def test_single_cluster_ari_zero():
    p = {"a": "X", "b": "X", "c": "X", "d": "X"}
    t = {"a": "1", "b": "1", "c": "2", "d": "2"}
    # putting everything in one cluster: no better than chance
    assert pair_metrics(p, t).adjusted_rand_index == 0.0
