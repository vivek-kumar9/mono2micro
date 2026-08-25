"""Product discovery: browse the catalogue with live stock and effective price."""
from __future__ import annotations

from flask import Blueprint, jsonify

from monolith import db, inventory, rating
from monolith.models import Product, to_dict

bp = Blueprint("catalog", __name__, url_prefix="/catalog")


def enrich(product: Product) -> dict:
    data = to_dict(product)
    data["effective_price"] = rating.effective_price(product)
    data["in_stock"] = inventory.available(product.id)
    return data


@bp.get("/products")
def list_products():
    return jsonify([enrich(p) for p in db.products.values()])


@bp.get("/products/<int:product_id>")
def get_product(product_id: int):
    product = db.products.get(product_id)
    if product is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(enrich(product))
