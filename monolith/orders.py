"""Orders: checkout orchestration (the most cross-cutting module).

Checkout touches Catalog, Inventory, Payments, Users and Notifications —
which is precisely why Orders is the natural first service to extract with
the strangler-fig pattern.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from monolith import basket, db, inventory, notifications, payments, rating, users
from monolith.models import Order, OrderLine, to_dict

bp = Blueprint("orders", __name__, url_prefix="/orders")


def _build_lines(user_id: int) -> list[OrderLine]:
    active_cart = basket.get_cart(user_id)
    lines: list[OrderLine] = []
    for item in active_cart.items:
        product = db.products.get(item.product_id)
        if product is None:
            continue
        lines.append(OrderLine(product_id=item.product_id, quantity=item.quantity,
                               unit_price=rating.effective_price(product)))
    return lines


def checkout(user_id: int) -> Order:
    if users.get_user(user_id) is None:
        raise KeyError(user_id)
    lines = _build_lines(user_id)
    for line in lines:
        inventory.reserve(line.product_id, line.quantity)
    total = round(sum(l.unit_price * l.quantity for l in lines), 2)

    order = Order(id=db.next_order_id(), user_id=user_id, lines=lines, total=total)
    db.orders[order.id] = order

    payment = payments.charge(order.id, user_id, total)
    order.payment_id = payment.id
    order.status = "confirmed"

    notifications.enqueue(user_id, "email", "Order confirmed",
                          f"Order {order.id} total {total}")
    db.carts.pop(user_id, None)
    return order


@bp.post("")
def create_order():
    payload = request.get_json(force=True)
    try:
        order = checkout(payload["user_id"])
    except KeyError:
        return jsonify({"error": "unknown user"}), 404
    return jsonify(_serialize(order)), 201


@bp.get("")
def list_orders():
    return jsonify([_serialize(o) for o in db.orders.values()])


@bp.get("/<int:order_id>")
def get_order(order_id: int):
    order = db.orders.get(order_id)
    if order is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(order))


def _serialize(order: Order) -> dict:
    data = to_dict(order)
    data["lines"] = [to_dict(l) for l in order.lines]
    return data
