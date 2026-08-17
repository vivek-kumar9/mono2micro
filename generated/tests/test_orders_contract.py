"""Contract tests for the orders service. AUTO-GENERATED.

Each case exercises one operation and asserts (1) the status code matches the
contract and (2) the response body conforms to the contract's response schema.
"""
from __future__ import annotations

import pytest

# (method, path_template, concrete_path, expected_status)
CASES = [
    [
        "GET",
        "/cart/{user_id}",
        "/cart/1",
        200
    ],
    [
        "POST",
        "/cart/{user_id}/items",
        "/cart/1/items",
        201
    ],
    [
        "POST",
        "/orders",
        "/orders",
        201
    ],
    [
        "GET",
        "/orders",
        "/orders",
        200
    ],
    [
        "GET",
        "/orders/{order_id}",
        "/orders/1",
        200
    ]
]


@pytest.mark.parametrize("method,template,concrete,status", CASES)
def test_status_and_schema(client, spec, validate_body, method, template, concrete, status):
    kwargs = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
    resp = client.request(method, concrete, **kwargs)
    assert resp.status_code == status, method + " " + concrete + " -> " + str(resp.status_code) + ": " + resp.text
    validate_body(spec, template, method, status, resp.json())


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"].endswith("-service")


def test_served_by_header(client):
    resp = client.get("/health")
    assert resp.headers.get("X-Served-By", "").endswith("-service")
