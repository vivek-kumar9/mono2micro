"""Decomposition quality and determinism."""
from __future__ import annotations

from core.graph import build_digraph
from core.metrics import evaluate


def test_every_module_assigned(decomposition, analysis):
    assigned = {m for svc in decomposition.services for m in svc.modules}
    assert assigned == {p.module for p in analysis.packs}


def test_no_module_in_two_services(decomposition):
    seen: set[str] = set()
    for svc in decomposition.services:
        for m in svc.modules:
            assert m not in seen, f"{m} assigned twice"
            seen.add(m)


def test_shared_kernel_is_platform(decomposition):
    assignment = decomposition.assignment()
    for kernel in ("config", "db", "models", "app"):
        assert assignment[kernel] == "Platform"


def test_refinement_beats_algorithmic_baseline(decomposition, analysis, ground_truth):
    dg = build_digraph(analysis.packs)
    refined = evaluate("refined", decomposition.assignment(), ground_truth, dg)
    algo_assign = {
        m: f"C{i}"
        for i, c in enumerate(decomposition.algorithmic_clusters)
        for m in c
    }
    algo = evaluate("algo", algo_assign, ground_truth, dg)
    # the semantic layer must add value over structural clustering alone
    assert refined.pair.adjusted_rand_index > algo.pair.adjusted_rand_index
    assert refined.labelled.macro_f1 >= 0.8


def test_refinement_is_strong_but_not_a_perfect_oracle(decomposition, analysis, ground_truth):
    """The sample monolith contains domain-neutral names + one genuinely
    straddling module, so the honest score is strong but < 1.0 (no filename
    leakage / no manufactured perfection)."""
    dg = build_digraph(analysis.packs)
    refined = evaluate("refined", decomposition.assignment(), ground_truth, dg)
    ari = refined.pair.adjusted_rand_index
    assert 0.75 <= ari < 1.0, f"expected a believable, imperfect ARI, got {ari}"


def test_neutral_named_modules_still_classified_by_content(decomposition, ground_truth):
    """Renamed modules (discovery/rating/basket) must land in their true context —
    proving the classifier reads behaviour, not the filename."""
    assignment = decomposition.assignment()
    assert assignment["discovery"] == ground_truth["discovery"]  # Catalog
    assert assignment["rating"] == ground_truth["rating"]        # Catalog
    assert assignment["basket"] == ground_truth["basket"]        # Orders


def test_decomposition_deterministic(analysis, llm):
    from agents.decomposition import DecompositionEngine

    a = DecompositionEngine(analysis, llm).run().assignment()
    b = DecompositionEngine(analysis, llm).run().assignment()
    assert a == b


def test_extraction_target_orders_present(decomposition):
    names = {svc.name for svc in decomposition.services}
    assert "Orders" in names
