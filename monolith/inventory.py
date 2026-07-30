"""Inventory: stock levels and reservations."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from monolith import db
from monolith.models import InventoryItem

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def available(product_id: int) -> int:
    item = db.inventory.get(product_id)
    if item is None:
        return 0
    return max(0, item.quantity - item.reserved)


def reserve(product_id: int, quantity: int) -> bool:
    item = db.inventory.get(product_id)
    if item is None or available(product_id) < quantity:
        return False
    item.reserved += quantity
    return True


@bp.get("/<int:product_id>")
def stock(product_id: int):
    item: InventoryItem | None = db.inventory.get(product_id)
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"product_id": product_id, "available": available(product_id),
                    "reserved": item.reserved})


@bp.post("/reserve")
def reserve_route():
    payload = request.get_json(force=True)
    ok = reserve(payload["product_id"], payload["quantity"])
    return jsonify({"reserved": ok}), (200 if ok else 409)
