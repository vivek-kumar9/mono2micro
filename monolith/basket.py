"""Orders: shopping cart (pre-checkout state).

(Domain-neutral module name on purpose — the word "basket"/"cart" only appears
in behaviour, not the filename.)
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from monolith import db, discovery, rating
from monolith.models import Cart, CartItem, to_dict

bp = Blueprint("cart", __name__, url_prefix="/cart")


def get_cart(user_id: int) -> Cart:
    cart = db.carts.get(user_id)
    if cart is None:
        cart = Cart(user_id=user_id)
        db.carts[user_id] = cart
    return cart


def add_item(user_id: int, product_id: int, quantity: int) -> Cart:
    product = db.products.get(product_id)
    if product is None:
        raise KeyError(product_id)
    cart = get_cart(user_id)
    cart.items.append(CartItem(product_id=product_id, quantity=quantity))
    return cart


def cart_total(cart: Cart) -> float:
    total = 0.0
    for item in cart.items:
        product = db.products.get(item.product_id)
        if product is not None:
            total += rating.effective_price(product) * item.quantity
    return round(total, 2)


@bp.get("/<int:user_id>")
def view_cart(user_id: int):
    cart = get_cart(user_id)
    return jsonify({"user_id": user_id, "items": [to_dict(i) for i in cart.items],
                    "total": cart_total(cart)})


@bp.post("/<int:user_id>/items")
def add_to_cart(user_id: int):
    payload = request.get_json(force=True)
    try:
        cart = add_item(user_id, payload["product_id"], payload["quantity"])
    except KeyError:
        return jsonify({"error": "unknown product"}), 404
    _ = discovery.enrich(db.products[payload["product_id"]])
    return jsonify({"user_id": user_id, "items": [to_dict(i) for i in cart.items]}), 201
