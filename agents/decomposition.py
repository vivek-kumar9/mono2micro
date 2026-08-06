"""Decomposition agent.

Proposes service boundaries by combining two *separately inspectable* signals:

1. **Structural** — community detection on the module dependency graph
   (greedy modularity on an IDF-weighted graph with infrastructure hubs
   factored out; see ``core.graph``).
2. **Semantic** — an LLM (or the deterministic mock) refines and *names* those
   clusters into domain-driven bounded contexts, splitting clusters the graph
   over-merged when the module-content domain signal is decisive.

Both the raw algorithmic clusters and the refined services are returned so a
reviewer can see exactly what each signal contributed.
"""
from __future__ import annotations

import json

from agents.llm_client import LLMClient
from core.context_pack import Decomposition, RepoAnalysis, ServiceProposal
from core.graph import (
    build_digraph,
    detect_communities,
    idf_weighted_graph,
    infrastructure_hubs,
    modularity,
    to_undirected_weighted,
)


# resolution grid searched when no explicit resolution is supplied
_RESOLUTION_GRID = (0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.2)


class DecompositionEngine:
    def __init__(
        self, analysis: RepoAnalysis, llm: LLMClient, resolution: float | None = None
    ) -> None:
        self.analysis = analysis
        self.llm = llm
        self.resolution = resolution
        self.selected_resolution: float | None = None

    def run(self) -> Decomposition:
        packs = self.analysis.packs
        digraph = build_digraph(packs)

        hubs = infrastructure_hubs(digraph)
        domain_nodes = [n for n in digraph.nodes() if n not in hubs]
        subgraph = digraph.subgraph(domain_nodes).copy()

        idf_graph = idf_weighted_graph(subgraph)
        resolution = (
            self.resolution
            if self.resolution is not None
            else self._select_resolution(idf_graph)
        )
        self.selected_resolution = resolution
        communities = detect_communities(idf_graph, resolution=resolution)

        algorithmic_clusters = [list(c) for c in communities]
        if hubs:
            algorithmic_clusters.append(sorted(hubs))

        # modularity of the algorithmic partition on the *plain* full graph
        full_undirected = to_undirected_weighted(digraph)
        algo_mod = modularity(full_undirected, algorithmic_clusters)

        services = self._refine(algorithmic_clusters)

        return Decomposition(
            algorithmic_clusters=algorithmic_clusters,
            algorithmic_modularity=algo_mod,
            services=services,
            method=f"idf-greedy-modularity(hub-aware, res={resolution:g}) + llm-refine",
            llm_mode=self.llm.mode,
            model=self.llm.model if self.llm.mode == "real" else "mock",
        )

    # ------------------------------------------------------------------ #
    def _select_resolution(self, idf_graph) -> float:
        """Pick the resolution that maximises modularity — an *unsupervised*
        choice that never consults the ground truth."""
        best_res, best_q = 1.0, float("-inf")
        for res in _RESOLUTION_GRID:
            comms = detect_communities(idf_graph, resolution=res)
            q = modularity(idf_graph, comms)
            if q > best_q + 1e-9:
                best_q, best_res = q, res
        return best_res

    # ------------------------------------------------------------------ #
    def _refine(self, clusters: list[list[str]]) -> list[ServiceProposal]:
        module_tokens = {p.module: p.keywords for p in self.analysis.packs}
        summaries = {
            p.module: p.responsibility for p in self.analysis.packs if p.responsibility
        }
        context = {"clusters": clusters, "module_tokens": module_tokens}

        system = (
            "You are a domain-driven-design expert refining a monolith "
            "decomposition. You are given dependency-derived clusters of modules "
            "and a one-line responsibility for each module. Group the modules into "
            "named bounded-context microservices, consolidating shared-kernel "
            "modules into a single 'Platform' service. Respect the clusters unless "
            "a module's responsibility clearly places it elsewhere. Respond ONLY as "
            'JSON: {"services": [{"name","modules","description","rationale","kind"}]} '
            "where kind is 'microservice' or 'shared-kernel'."
        )
        user = (
            "Dependency clusters:\n"
            + json.dumps(clusters, indent=2)
            + "\n\nModule responsibilities:\n"
            + json.dumps(summaries, indent=2)
        )

        result = self.llm.complete_json(
            task="refine_decomposition", system=system, user=user, context=context
        )
        services = [ServiceProposal(**svc) for svc in result.get("services", [])]
        return self._backfill_unassigned(services)

    def _backfill_unassigned(self, services: list[ServiceProposal]) -> list[ServiceProposal]:
        """Guarantee every module ends up in exactly one service."""
        assigned = {m for svc in services for m in svc.modules}
        missing = [p.module for p in self.analysis.packs if p.module not in assigned]
        if missing:
            platform = next((s for s in services if s.kind == "shared-kernel"), None)
            if platform is None:
                platform = ServiceProposal(
                    name="Platform", modules=[], kind="shared-kernel",
                    description="Shared kernel (backfilled).",
                )
                services.append(platform)
            platform.modules = sorted(set(platform.modules) | set(missing))
        return services
