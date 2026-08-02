"""Dependency-graph construction and community detection.

The dependency graph is the shared substrate for both the *algorithmic*
signal (community detection here) and the *evaluation* (modularity /
cohesion / coupling in ``core.metrics``).
"""
from __future__ import annotations

import math

import networkx as nx

from core.context_pack import ContextPack, DependencyEdge, GraphArtifact


def build_digraph(packs: list[ContextPack]) -> nx.DiGraph:
    """Directed, weighted dependency graph: an edge u->v means *u imports/uses v*."""
    g = nx.DiGraph()
    for pack in packs:
        g.add_node(pack.module)
    for pack in packs:
        for dep in pack.imports_internal:
            if dep.target == pack.module:
                continue
            if g.has_edge(pack.module, dep.target):
                g[pack.module][dep.target]["weight"] += dep.weight
                g[pack.module][dep.target]["kinds"] = sorted(
                    set(g[pack.module][dep.target]["kinds"]) | {dep.kind}
                )
            else:
                g.add_edge(pack.module, dep.target, weight=dep.weight, kinds=[dep.kind])
    return g


def to_undirected_weighted(digraph: nx.DiGraph) -> nx.Graph:
    """Collapse direction, summing weights of reciprocal edges.

    Community detection operates on the undirected coupling graph: two modules
    are "close" if there is heavy traffic between them in either direction.
    """
    ug = nx.Graph()
    ug.add_nodes_from(digraph.nodes())
    for u, v, data in digraph.edges(data=True):
        w = data.get("weight", 1)
        if ug.has_edge(u, v):
            ug[u][v]["weight"] += w
        else:
            ug.add_edge(u, v, weight=w)
    return ug


def idf_weighted_graph(digraph: nx.DiGraph) -> nx.Graph:
    """Undirected coupling graph with **inverse-dependency-frequency** weights.

    A dependency edge onto a module that *everyone* imports (a shared kernel such
    as ``models``/``db``) carries almost no clustering signal — it is the graph
    analogue of a stop-word. We scale each directed edge ``u -> v`` by
    ``idf(v) = log(N / (1 + indeg(v)))`` so ubiquitous targets are damped and
    discriminating dependencies dominate community detection.
    """
    n = digraph.number_of_nodes()
    indeg = dict(digraph.in_degree())
    ug = nx.Graph()
    ug.add_nodes_from(digraph.nodes())
    for u, v, data in digraph.edges(data=True):
        idf = math.log((n + 1) / (1 + indeg.get(v, 0))) + 0.1
        w = data.get("weight", 1) * max(idf, 0.0)
        if ug.has_edge(u, v):
            ug[u][v]["weight"] += w
        else:
            ug.add_edge(u, v, weight=w)
    return ug


def infrastructure_hubs(
    digraph: nx.DiGraph, source_frac: float = 0.6, sink_frac: float = 0.5
) -> set[str]:
    """Automatically flag composition roots and shared-utility modules.

    * A **source hub** imports a large fraction of all modules *and is imported
      by (almost) none* — a composition root / app factory. The in-degree guard
      is what separates a real composition root from a merely well-connected
      domain module such as ``orders`` (which imports many collaborators but is
      itself imported by the composition root).
    * A **sink hub** is imported by a large fraction of all modules (a shared
      kernel: models, db, ...).

    Both are factored out before community detection and later consolidated into
    a Platform/shared-kernel service — a standard "remove utility nodes" step
    that keeps them from smearing the domain clusters together.
    """
    n = digraph.number_of_nodes()
    if n <= 2:
        return set()
    denom = n - 1
    hubs: set[str] = set()
    for node in digraph.nodes():
        out_frac = digraph.out_degree(node) / denom
        in_frac = digraph.in_degree(node) / denom
        if out_frac >= source_frac and digraph.in_degree(node) == 0:
            hubs.add(node)  # composition root: imports many, imported by none
        if in_frac >= sink_frac:
            hubs.add(node)  # shared kernel
    return hubs


def graph_artifact(digraph: nx.DiGraph) -> GraphArtifact:
    edges = [
        DependencyEdge(
            source=u, target=v, weight=data.get("weight", 1),
            kinds=data.get("kinds", []),
        )
        for u, v, data in digraph.edges(data=True)
    ]
    return GraphArtifact(nodes=sorted(digraph.nodes()), edges=edges)


def detect_communities(
    undirected: nx.Graph, resolution: float = 1.0
) -> list[list[str]]:
    """Greedy modularity community detection (Clauset-Newman-Moore).

    Deterministic and dependency-free (networkx only). Returns communities as
    sorted lists of module names, ordered by descending size.
    """
    if undirected.number_of_nodes() == 0:
        return []
    if undirected.number_of_edges() == 0:
        return [[n] for n in sorted(undirected.nodes())]
    communities = nx.community.greedy_modularity_communities(
        undirected, weight="weight", resolution=resolution
    )
    result = [sorted(c) for c in communities]
    result.sort(key=lambda c: (-len(c), c))
    return result


def louvain_communities(undirected: nx.Graph, seed: int = 7) -> list[list[str]]:
    """Louvain community detection — reported alongside greedy for comparison."""
    if undirected.number_of_edges() == 0:
        return [[n] for n in sorted(undirected.nodes())]
    communities = nx.community.louvain_communities(
        undirected, weight="weight", seed=seed
    )
    result = [sorted(c) for c in communities]
    result.sort(key=lambda c: (-len(c), c))
    return result


def modularity(undirected: nx.Graph, communities: list[list[str]]) -> float:
    """Newman modularity Q of a partition on the weighted graph."""
    if undirected.number_of_edges() == 0 or not communities:
        return 0.0
    return float(
        nx.community.modularity(
            undirected, [set(c) for c in communities], weight="weight"
        )
    )
