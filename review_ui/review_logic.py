"""Pure logic behind the HITL review UI (kept separate so it is unit-testable).

The Streamlit app is a thin shell over these functions: it loads the proposed
decomposition, lets a human reassign modules / rename services, and on approval
persists an ``ApprovedDecomposition`` — the file that gates code generation.
"""
from __future__ import annotations

from pathlib import Path

from core.context_pack import (
    ApprovedDecomposition,
    Decomposition,
    GraphArtifact,
    ServiceProposal,
)

# a stable, colour-blind-friendly palette for the graph view
_PALETTE = [
    "#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2",
    "#EECA3B", "#B279A2", "#FF9DA6", "#9D755D", "#BAB0AC",
]


def apply_reassignments(
    services: list[ServiceProposal], module_to_service: dict[str, str]
) -> list[ServiceProposal]:
    """Rebuild the service list from an (edited) module→service mapping.

    Preserves service metadata (description/rationale/kind) by name, drops empty
    services, and creates a new service for any name introduced by the editor.
    """
    meta = {s.name: s for s in services}
    grouped: dict[str, list[str]] = {}
    for module, service in module_to_service.items():
        grouped.setdefault(service, []).append(module)

    rebuilt: list[ServiceProposal] = []
    for name in sorted(grouped, key=lambda n: (n == "Platform", n)):
        template = meta.get(name)
        rebuilt.append(ServiceProposal(
            name=name,
            modules=sorted(grouped[name]),
            description=template.description if template else "",
            rationale=template.rationale if template else "Human-edited grouping.",
            kind=template.kind if template else ("shared-kernel" if name == "Platform" else "microservice"),
        ))
    return rebuilt


def rename_service(
    module_to_service: dict[str, str], old: str, new: str
) -> dict[str, str]:
    return {m: (new if s == old else s) for m, s in module_to_service.items()}


def build_approved(
    services: list[ServiceProposal], extraction_target: str, approver: str,
    notes: str = "",
) -> ApprovedDecomposition:
    return ApprovedDecomposition(
        approved=True,
        approved_by=approver,
        services=services,
        extraction_target=extraction_target,
        notes=notes or "Approved via Streamlit HITL review.",
    )


def save_approved(approved: ApprovedDecomposition, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(approved.model_dump_json(indent=2), encoding="utf-8")


def initial_mapping(decomposition: Decomposition) -> dict[str, str]:
    return decomposition.assignment()


def graph_to_dot(
    graph: GraphArtifact, assignment: dict[str, str], extraction_target: str = ""
) -> str:
    """Render the dependency graph as Graphviz DOT, coloured by proposed service.
    Cross-service edges are dashed to highlight the seams a migration must cut."""
    services = sorted({assignment.get(n, "?") for n in graph.nodes})
    colour = {s: _PALETTE[i % len(_PALETTE)] for i, s in enumerate(services)}

    lines = ["digraph deps {", "  rankdir=LR;", '  node [style=filled, fontname="Helvetica"];']
    for node in graph.nodes:
        svc = assignment.get(node, "?")
        border = ' penwidth=3 color="#111111"' if svc == extraction_target else ""
        lines.append(f'  "{node}" [fillcolor="{colour[svc]}"{border}];')
    for edge in graph.edges:
        same = assignment.get(edge.source) == assignment.get(edge.target)
        style = "solid" if same else "dashed"
        lines.append(
            f'  "{edge.source}" -> "{edge.target}" '
            f'[label="{edge.weight}" style={style} color="#888888"];'
        )
    lines.append("}")
    return "\n".join(lines)
