"""OpenAPI contract generation."""
from __future__ import annotations

from agents.contract_agent import ContractAgent, _convert_path, validate_spec


def test_path_conversion():
    path, params = _convert_path("/orders/<int:order_id>")
    assert path == "/orders/{order_id}"
    assert params == [("order_id", "int")]


def test_orders_spec_structure(analysis, decomposition):
    agent = ContractAgent(analysis)
    orders = next(s for s in decomposition.services if s.name == "Orders")
    spec = agent.generate_for_service(orders)
    assert spec["openapi"] == "3.1.0"
    assert "/orders" in spec["paths"]
    assert "/orders/{order_id}" in spec["paths"]
    # response schema references the Order component
    order_get = spec["paths"]["/orders/{order_id}"]["get"]
    ref = order_get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert ref.endswith("/Order")


def test_order_schema_typed(analysis, decomposition):
    agent = ContractAgent(analysis)
    orders = next(s for s in decomposition.services if s.name == "Orders")
    spec = agent.generate_for_service(orders)
    order = spec["components"]["schemas"]["Order"]
    assert order["properties"]["id"] == {"type": "integer"}
    assert order["properties"]["total"] == {"type": "number"}
    assert order["properties"]["lines"]["type"] == "array"
    # nested entity resolved
    assert "OrderLine" in spec["components"]["schemas"]
    # nullable field expressed via anyOf null
    assert {"type": "null"} in order["properties"]["payment_id"]["anyOf"]


def test_all_specs_validate(analysis, decomposition):
    agent = ContractAgent(analysis)
    for svc in decomposition.services:
        if not any(agent._routes(m) for m in svc.modules):
            continue
        spec = agent.generate_for_service(svc)
        assert validate_spec(spec) == []


def test_unresolved_ref_detected():
    bad = {
        "openapi": "3.1.0",
        "paths": {"/x": {"get": {"responses": {"200": {
            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Ghost"}}}}}}}},
        "components": {"schemas": {}},
    }
    errors = validate_spec(bad)
    assert any("Ghost" in e for e in errors)
