"""Docker-free strangler-fig demo.

Boots the three tiers in-process (monolith WSGI + extracted service ASGI +
generated gateway) and drives a handful of requests through the gateway,
printing which backend actually served each one. This is the same topology
`docker compose up` brings up, minus the containers — handy when Docker isn't
available. Run:  python scripts/local_demo.py
"""
from __future__ import annotations

import functools
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORDERS_DIR = ROOT / "generated" / "services" / "orders"
GATEWAY_DIR = ROOT / "generated" / "gateway"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if not (ORDERS_DIR / "main.py").exists() or not (GATEWAY_DIR / "routing.py").exists():
        print("Generated topology missing — run `make generate` first.")
        return 1

    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ORDERS_DIR))

    import httpx
    import yaml
    from fastapi.testclient import TestClient

    orders_main = _load("orders_service_main", ORDERS_DIR / "main.py")
    routing = _load("gateway_routing", GATEWAY_DIR / "routing.py")

    from monolith import db
    from monolith.app import create_app

    db.reset()
    monolith_app = create_app()

    class WsgiSender:
        def __init__(self, app):
            self.client = httpx.Client(transport=httpx.WSGITransport(app=app),
                                       base_url="http://monolith")

        async def request(self, method, url, params=None, content=None, headers=None):
            import anyio
            call = functools.partial(self.client.request, method, url,
                                     params=params, content=content, headers=headers)
            return await anyio.to_thread.run_sync(call)

        async def aclose(self):
            self.client.close()

    senders = {
        "orders-service": httpx.AsyncClient(
            transport=httpx.ASGITransport(app=orders_main.app),
            base_url="http://orders-service"),
        "monolith": WsgiSender(monolith_app),
    }
    table = yaml.safe_load((GATEWAY_DIR / "routes.yaml").read_text())
    gateway = routing.build_gateway_app(table=table, senders=senders)

    print("\nStrangler-fig routing through the gateway")
    print("=" * 68)
    print(f"  route table: {[r['prefix'] for r in table['routes']]} -> orders-service")
    print("               everything else            -> monolith")
    print("-" * 68)
    print(f"  {'REQUEST':30s} {'BACKEND':16s} {'STATUS':6s} SERVED-BY")
    print("-" * 68)

    calls = [
        ("GET", "/catalog/products", None),
        ("GET", "/orders/1", None),
        ("POST", "/orders", {"user_id": 1}),
        ("GET", "/orders", None),
        ("GET", "/users/1", None),
        ("POST", "/auth/register", {"email": "grace@example.com", "name": "Grace", "password": "pw"}),
    ]
    with TestClient(gateway) as tc:
        for method, path, body in calls:
            resp = tc.request(method, path, json=body)
            backend = resp.headers.get("X-Gateway-Backend", "?")
            served = resp.headers.get("X-Served-By", "-")
            tag = "  <- extracted" if backend == "orders-service" else ""
            print(f"  {method + ' ' + path:30s} {backend:16s} {resp.status_code:<6d} {served}{tag}")

    print("=" * 68)
    print("  Orders/Cart traffic is served by the extracted service;")
    print("  every other route still falls through to the monolith.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
