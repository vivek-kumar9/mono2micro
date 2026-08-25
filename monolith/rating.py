"""Effective-price computation: discounts, tax and quotes for products."""
from __future__ import annotations

from flask import Blueprint, jsonify

from monolith import db
from monolith.config import CONFIG
from monolith.models import Product

bp = Blueprint("pricing", __name__, url_prefix="/pricing")


def effective_price(product: Product) -> float:
    rule = db.price_rules.get(product.id)
    price = product.base_price
    if rule is not None:
        price = round(price * (1.0 - rule.discount_pct), 2)
    return price


def with_tax(amount: float) -> float:
    return round(amount * (1.0 + CONFIG.tax_rate), 2)


@bp.get("/<int:product_id>")
def quote(product_id: int):
    product = db.products.get(product_id)
    if product is None:
        return jsonify({"error": "not found"}), 404
    net = effective_price(product)
    return jsonify({
        "product_id": product_id,
        "base_price": product.base_price,
        "effective_price": net,
        "price_with_tax": with_tax(net),
        "currency": CONFIG.currency,
    })
