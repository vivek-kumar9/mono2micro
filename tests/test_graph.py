"""Dependency-graph and community-detection behaviour."""
from __future__ import annotations

from core.graph import (
    build_digraph,
    detect_communities,
    idf_weighted_graph,
    infrastructure_hubs,
    to_undirected_weighted,
)


def test_hub_detection(analysis):
    dg = build_digraph(analysis.packs)
    hubs = infrastructure_hubs(dg)
    # composition root + shared kernel are flagged; orders (coupled domain) is not
    assert {"app", "db", "models"} <= hubs
    assert "orders" not in hubs


def test_composition_root_has_zero_in_degree(analysis):
    dg = build_digraph(analysis.packs)
    assert dg.in_degree("app") == 0
    assert dg.out_degree("app") >= 9


def test_idf_damps_hub_edges(analysis):
    dg = build_digraph(analysis.packs)
    ug_plain = to_undirected_weighted(dg)
    ug_idf = idf_weighted_graph(dg)
    # an edge onto the ubiquitous `models` hub is damped relative to plain weight
    if ug_plain.has_edge("orders", "models"):
        assert ug_idf["orders"]["models"]["weight"] < ug_plain["orders"]["models"]["weight"]


def test_community_detection_deterministic(analysis):
    dg = build_digraph(analysis.packs)
    sub = dg.subgraph([n for n in dg.nodes() if n not in infrastructure_hubs(dg)]).copy()
    ug = idf_weighted_graph(sub)
    a = detect_communities(ug, resolution=1.0)
    b = detect_communities(ug, resolution=1.0)
    assert a == b


def test_auth_users_cluster_together(analysis):
    dg = build_digraph(analysis.packs)
    sub = dg.subgraph([n for n in dg.nodes() if n not in infrastructure_hubs(dg)]).copy()
    ug = idf_weighted_graph(sub)
    comms = detect_communities(ug, resolution=1.0)
    for c in comms:
        if "auth" in c:
            assert "users" in c  # identity context stays intact
