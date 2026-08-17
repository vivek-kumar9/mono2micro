"""End-to-end strangler-fig proof WITHOUT Docker.

Boots the three tiers in-process and drives the generated gateway:
* the extracted Orders service (FastAPI/ASGI) via an httpx ASGI sender,
* the still-running monolith (Flask/WSGI) via a threaded WSGI sender,
* the generated gateway routing between them.

Asserts that an Orders request is served by the NEW service and a Catalog
request falls through to the monolith — the whole point of the pattern.
"""
from __future__ import annotations

import functools
import sys
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
ORDERS_DIR = ROOT / "generated" / "services" / "orders"
GATEWAY_DIR = ROOT / "generated" / "gateway"

pytestmark = pytest.mark.integration


class WsgiSender:
    """Adapts the sync Flask/WSGI monolith to the gateway's async sender API."""

    def __init__(self, app) -> None:
        self.client = httpx.Client(
            transport=httpx.WSGITransport(app=app), base_url="http://monolith"
        )

    async def request(self, method, url, params=None, content=None, headers=None):
        import anyio

        call = functools.partial(
            self.client.request, method, url,
            params=params, content=content, headers=headers,
        )
        return await anyio.to_thread.run_sync(call)

    async def aclose(self):
        self.client.close()


def _load(module_name: str, path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gateway_client():
    # ensure generated code is present + importable
    if not (ORDERS_DIR / "main.py").exists() or not (GATEWAY_DIR / "routing.py").exists():
        pytest.skip("run `make generate` first (generated topology missing)")
    # ORDERS_DIR must be importable for the service's internal `from models import ...`.
    # Both services ship a `main.py`, so load each from its explicit path under a
    # unique module name to avoid a name collision.
    sys.path.insert(0, str(ORDERS_DIR))
    orders_main = _load("orders_service_main", ORDERS_DIR / "main.py")
    routing = _load("gateway_routing", GATEWAY_DIR / "routing.py")

    from monolith import db
    from monolith.app import create_app

    db.reset()
    monolith_app = create_app()

    orders_sender = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=orders_main.app),
        base_url="http://orders-service",
    )
    senders = {"orders-service": orders_sender, "monolith": WsgiSender(monolith_app)}

    table = yaml.safe_load((GATEWAY_DIR / "routes.yaml").read_text())
    gateway = routing.build_gateway_app(table=table, senders=senders)
    with TestClient(gateway) as tc:
        yield tc


def test_gateway_health_lists_routes(gateway_client):
    body = gateway_client.get("/__gateway/health").json()
    assert body["service"] == "gateway"
    prefixes = {r["prefix"] for r in body["routes"]}
    assert "/orders" in prefixes


def test_orders_route_hits_new_service(gateway_client):
    resp = gateway_client.get("/orders/1")
    assert resp.status_code == 200
    assert resp.headers["X-Gateway-Backend"] == "orders-service"
    assert resp.headers["X-Served-By"] == "orders-service"


def test_orders_collection_hits_new_service(gateway_client):
    resp = gateway_client.get("/orders")
    assert resp.status_code == 200
    assert resp.headers["X-Gateway-Backend"] == "orders-service"
    assert isinstance(resp.json(), list)


def test_post_order_hits_new_service(gateway_client):
    resp = gateway_client.post("/orders", json={"user_id": 1})
    assert resp.status_code == 201
    assert resp.headers["X-Served-By"] == "orders-service"


def test_catalog_route_falls_through_to_monolith(gateway_client):
    resp = gateway_client.get("/catalog/products")
    assert resp.status_code == 200
    assert resp.headers["X-Gateway-Backend"] == "monolith"
    # real monolith data (not a stub) — products carry an effective_price
    products = resp.json()
    assert products and "effective_price" in products[0]


def test_unextracted_route_uses_monolith(gateway_client):
    # /catalog is NOT in the route table -> default backend (monolith)
    resp = gateway_client.get("/health")
    assert resp.json()["service"] == "monolith"
    assert resp.headers["X-Gateway-Backend"] == "monolith"
