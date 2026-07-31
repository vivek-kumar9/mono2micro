"""Payments: charge capture against orders."""
from __future__ import annotations

import secrets

from flask import Blueprint, jsonify, request

from monolith import db, notifications
from monolith.config import CONFIG
from monolith.models import Payment, to_dict

bp = Blueprint("payments", __name__, url_prefix="/payments")


def charge(order_id: int, user_id: int, amount: float) -> Payment:
    payment = Payment(
        id=db.next_payment_id(),
        order_id=order_id,
        user_id=user_id,
        amount=round(amount, 2),
        status="captured",
        provider_ref=f"{CONFIG.payment_provider}:{secrets.token_hex(4)}",
    )
    db.payments[payment.id] = payment
    # cross-context receipt notification
    notifications.enqueue(user_id, "email", "Payment receipt",
                          f"Charged {amount} {CONFIG.currency} for order {order_id}")
    return payment


@bp.post("/charge")
def charge_route():
    payload = request.get_json(force=True)
    payment = charge(payload["order_id"], payload["user_id"], payload["amount"])
    return jsonify(to_dict(payment)), 201


@bp.get("/<int:payment_id>")
def get_payment(payment_id: int):
    payment = db.payments.get(payment_id)
    if payment is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(to_dict(payment))
