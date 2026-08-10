"""HITL review logic + approval gate."""
from __future__ import annotations

import json

from core.context_pack import ApprovedDecomposition, ServiceProposal
from review_ui import review_logic as rl


def test_reassignment_moves_module(decomposition):
    mapping = rl.initial_mapping(decomposition)
    # a reviewer corrects the known ambiguous module: logistics -> Orders
    mapping["logistics"] = "Orders"
    services = rl.apply_reassignments(decomposition.services, mapping)
    assignment = {m: s.name for s in services for m in s.modules}
    assert assignment["logistics"] == "Orders"


def test_reassignment_can_create_new_service(decomposition):
    mapping = rl.initial_mapping(decomposition)
    mapping["notifications"] = "Messaging"
    services = rl.apply_reassignments(decomposition.services, mapping)
    names = {s.name for s in services}
    assert "Messaging" in names


def test_empty_services_dropped(decomposition):
    mapping = rl.initial_mapping(decomposition)
    # collapse everything into one service -> others disappear
    mapping = {m: "Mono" for m in mapping}
    services = rl.apply_reassignments(decomposition.services, mapping)
    assert len(services) == 1 and services[0].name == "Mono"


def test_rename_service(decomposition):
    mapping = rl.initial_mapping(decomposition)
    renamed = rl.rename_service(mapping, "Orders", "OrderMgmt")
    assert "Orders" not in set(renamed.values())
    assert "OrderMgmt" in set(renamed.values())


def test_build_and_persist_approval(decomposition, tmp_path):
    services = decomposition.services
    approved = rl.build_approved(services, "Orders", "tester", "looks good")
    path = tmp_path / "approved_decomposition.json"
    rl.save_approved(approved, path)

    loaded = ApprovedDecomposition.model_validate_json(path.read_text())
    assert loaded.approved is True
    assert loaded.extraction_target == "Orders"
    assert loaded.approved_by == "tester"
    assert "Orders" in {s.name for s in loaded.services}


def test_graph_dot_renders(decomposition, analysis):
    mapping = rl.initial_mapping(decomposition)
    dot = rl.graph_to_dot(analysis.graph, mapping, extraction_target="Orders")
    assert dot.startswith("digraph deps")
    assert '"orders" -> ' in dot or '"orders"' in dot
    # cross-service edges are dashed
    assert "style=dashed" in dot
