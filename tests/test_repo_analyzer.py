"""Static-analysis correctness."""
from __future__ import annotations


def test_module_discovery(analysis):
    modules = {p.module for p in analysis.packs}
    assert modules == {
        "app", "auth", "basket", "config", "db", "discovery", "inventory",
        "logistics", "models", "notifications", "orders", "payments", "rating",
        "users",
    }


def test_orders_is_most_coupled(analysis):
    packs = analysis.pack_by_module()
    orders_deps = {d.target for d in packs["orders"].imports_internal}
    # checkout orchestration reaches across contexts
    assert {"basket", "inventory", "payments", "users", "notifications"} <= orders_deps


def test_import_weights_counted(analysis):
    packs = analysis.pack_by_module()
    # orders references models many times -> weight > 1
    models_edge = next(d for d in packs["orders"].imports_internal if d.target == "models")
    assert models_edge.weight > 1


def test_routes_extracted(analysis):
    packs = analysis.pack_by_module()
    orders_routes = {(r.method, r.path) for r in packs["orders"].routes}
    assert ("POST", "/orders") in orders_routes
    assert ("GET", "/orders/<int:order_id>") in orders_routes


def test_entities_typed(analysis):
    packs = analysis.pack_by_module()
    order = next(e for e in packs["models"].entities if e.name == "Order")
    assert order.annotations["id"] == "int"
    assert order.annotations["lines"].startswith("list[")
    assert "None" in order.annotations["payment_id"]


def test_external_imports_flask(analysis):
    packs = analysis.pack_by_module()
    assert "flask" in packs["orders"].imports_external


def test_db_tables_detected(analysis):
    packs = analysis.pack_by_module()
    tables = next(e for e in packs["db"].entities if e.name == "TABLES")
    assert "orders" in tables.fields and "payments" in tables.fields


def test_llm_enrichment_present(analysis):
    for pack in analysis.packs:
        assert pack.responsibility  # every module gets a responsibility summary
        assert pack.suggested_domain
