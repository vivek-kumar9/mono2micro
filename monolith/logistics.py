"""Warehouse logistics: reserve and release stock, pick and pack, record shipments."""
from __future__ import annotations

from flask import Blueprint, jsonify

from monolith import db, inventory

bp = Blueprint("logistics", __name__, url_prefix="/logistics")

_shipments: dict[int, str] = {}


def reserve_stock(ref: int) -> bool:
    record = db.orders.get(ref)
    if record is None:
        return False
    ok = True
    for line in record.lines:
        on_hand = inventory.available(line.product_id)
        if on_hand < line.quantity or not inventory.reserve(line.product_id, line.quantity):
            ok = False
    return ok


def release_stock(product_id: int, quantity: int) -> None:
    item = db.inventory.get(product_id)
    if item is not None:
        item.reserved = max(0, item.reserved - quantity)


def pick_and_pack(ref: int) -> str:
    _shipments[ref] = "shipped" if reserve_stock(ref) else "backordered"
    return _shipments[ref]


@bp.post("/<int:ref>/ship")
def ship(ref: int):
    if db.orders.get(ref) is None:
        return jsonify({"error": "unknown reference"}), 404
    return jsonify({"ref": ref, "shipment": pick_and_pack(ref)}), 201


@bp.get("/<int:ref>")
def shipment_status(ref: int):
    status = _shipments.get(ref)
    if status is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ref": ref, "shipment": status})
