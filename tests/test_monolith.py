"""The synthetic monolith runs and its cross-context checkout works."""
from __future__ import annotations

import pytest


@pytest.fixture()
def client():
    from monolith import db
    from monolith.app import create_app

    db.reset()
    app = create_app()
    return app.test_client()


def test_health(client):
    assert client.get("/health").get_json()["status"] == "ok"


def test_catalog_lists_products(client):
    products = client.get("/catalog/products").get_json()
    assert len(products) >= 1
    assert "effective_price" in products[0]


def test_checkout_orchestrates_contexts(client):
    user = client.post("/users", json={"email": "x@y.z", "name": "X"}).get_json()
    client.post(f"/cart/{user['id']}/items", json={"product_id": 1, "quantity": 2})
    order = client.post("/orders", json={"user_id": user["id"]}).get_json()
    assert order["status"] == "confirmed"
    assert order["payment_id"] is not None
    # payment + notifications were created as a side effect (cross-context)
    payment = client.get(f"/payments/{order['payment_id']}").get_json()
    assert payment["status"] == "captured"


def test_order_not_found(client):
    assert client.get("/orders/9999").status_code == 404
