"""Pydantic data models shared across every agent and phase.

These are the *inspectable* contracts between phases: each is serialised to
JSON on disk so a human (or a test) can read exactly what one agent handed to
the next.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# Static analysis
# --------------------------------------------------------------------------- #


class Route(BaseModel):
    """An HTTP route discovered from a Flask blueprint decorator."""

    method: str
    path: str
    handler: str


class Entity(BaseModel):
    """A persistent/domain entity (a dataclass or model class)."""

    name: str
    fields: list[str] = Field(default_factory=list)
    annotations: dict[str, str] = Field(default_factory=dict)  # field -> python type


class FunctionInfo(BaseModel):
    name: str
    args: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    is_public: bool = True


class ClassInfo(BaseModel):
    name: str
    bases: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)


class Dependency(BaseModel):
    """A resolved dependency from this module onto another *internal* module."""

    target: str
    kind: Literal["import", "call", "attr"] = "import"
    weight: int = 1


class ContextPack(BaseModel):
    """Everything one agent needs to reason about a single module.

    ``responsibility`` is the natural-language field enriched by the LLM (or
    the deterministic mock); every other field is derived by static analysis.
    """

    module: str
    path: str
    loc: int = 0
    url_prefix: str | None = None

    imports_internal: list[Dependency] = Field(default_factory=list)
    imports_external: list[str] = Field(default_factory=list)

    functions: list[FunctionInfo] = Field(default_factory=list)
    classes: list[ClassInfo] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)

    keywords: list[str] = Field(default_factory=list)
    public_interface: list[str] = Field(default_factory=list)

    # LLM-enriched fields
    responsibility: str = ""
    suggested_domain: str = ""

    def fan_out(self) -> list[str]:
        return [d.target for d in self.imports_internal]


class DependencyEdge(BaseModel):
    source: str
    target: str
    weight: int = 1
    kinds: list[str] = Field(default_factory=list)


class GraphArtifact(BaseModel):
    """Serialisable dependency-graph snapshot (nodes + weighted edges)."""

    nodes: list[str]
    edges: list[DependencyEdge]

    def edge_count(self) -> int:
        return len(self.edges)


class RepoAnalysis(BaseModel):
    """Result of static analysis: the context packs plus the dependency graph."""

    root: str
    packs: list[ContextPack]
    graph: GraphArtifact
    llm_mode: str = "mock"
    model: str = ""

    def pack_by_module(self) -> dict[str, ContextPack]:
        return {p.module: p for p in self.packs}


# --------------------------------------------------------------------------- #
# Decomposition
# --------------------------------------------------------------------------- #


class ServiceProposal(BaseModel):
    """A proposed microservice: a named cluster of modules."""

    name: str
    modules: list[str]
    description: str = ""
    rationale: str = ""
    kind: Literal["microservice", "shared-kernel"] = "microservice"


class Decomposition(BaseModel):
    """Result of decomposition. Keeps the *algorithmic* clusters and the
    *LLM-refined* services separate so both signals stay inspectable."""

    algorithmic_clusters: list[list[str]]
    algorithmic_modularity: float = 0.0
    services: list[ServiceProposal]
    method: str = "greedy-modularity + llm-refine"
    llm_mode: str = "mock"
    model: str = ""

    def assignment(self) -> dict[str, str]:
        """module -> service-name mapping from the refined services."""
        out: dict[str, str] = {}
        for svc in self.services:
            for m in svc.modules:
                out[m] = svc.name
        return out


class ApprovedDecomposition(BaseModel):
    """What the reviewer approves; gates code generation."""

    approved: bool = False
    approved_by: str = ""
    services: list[ServiceProposal]
    extraction_target: str = ""
    notes: str = ""

    def assignment(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for svc in self.services:
            for m in svc.modules:
                out[m] = svc.name
        return out
