"""Platform: in-memory "database" with seed data (shared kernel).

Uses plain dicts as tables so the monolith runs with a single dependency
(Flask) while still declaring the persistent entities/tables that the repo
analyzer treats as DB signal.
"""
from __future__ import annotations

from itertools import count
from typing import Any

from monolith.models import (
    Cart,
    InventoryItem,
    Notification,
    Order,
    Payment,
    PriceRule,
    Product,
    User,
)

# --- Declared tables (analyzer reads these as the persistence schema) --------
TABLES: tuple[str, ...] = (
    "users",
    "products",
    "price_rules",
    "inventory",
    "carts",
    "orders",
    "payments",
    "notifications",
)

# --- In-memory stores --------------------------------------------------------
users: dict[int, User] = {}
products: dict[int, Product] = {}
price_rules: dict[int, PriceRule] = {}
inventory: dict[int, InventoryItem] = {}
carts: dict[int, Cart] = {}
orders: dict[int, Order] = {}
payments: dict[int, Payment] = {}
notifications: dict[int, Notification] = {}

_user_ids = count(1)
_order_ids = count(1)
_payment_ids = count(1)
_notification_ids = count(1)


def next_user_id() -> int:
    return next(_user_ids)


def next_order_id() -> int:
    return next(_order_ids)


def next_payment_id() -> int:
    return next(_payment_ids)


def next_notification_id() -> int:
    return next(_notification_ids)


def seed() -> None:
    """Populate the stores with deterministic demo data."""
    if products:
        return
    demo_users = [
        User(id=next_user_id(), email="ada@example.com", name="Ada Lovelace",
             password_hash="hash:secret", address="1 Analytical Ave"),
        User(id=next_user_id(), email="alan@example.com", name="Alan Turing",
             password_hash="hash:enigma", address="2 Bletchley Rd"),
    ]
    for u in demo_users:
        users[u.id] = u

    demo_products = [
        Product(id=1, sku="BK-001", name="Distributed Systems", category="books", base_price=42.0),
        Product(id=2, sku="BK-002", name="Clean Architecture", category="books", base_price=30.0),
        Product(id=3, sku="EL-010", name="Mechanical Keyboard", category="electronics", base_price=89.0),
    ]
    for p in demo_products:
        products[p.id] = p
        inventory[p.id] = InventoryItem(product_id=p.id, quantity=25)

    price_rules[2] = PriceRule(product_id=2, discount_pct=0.10, reason="launch")


def reset() -> None:
    """Clear every store *and* restart the id counters (used by tests/demos)."""
    global _user_ids, _order_ids, _payment_ids, _notification_ids
    for store in (users, products, price_rules, inventory, carts,
                  orders, payments, notifications):
        store.clear()
    _user_ids = count(1)
    _order_ids = count(1)
    _payment_ids = count(1)
    _notification_ids = count(1)


def snapshot() -> dict[str, Any]:
    """Row counts per table — handy for a health/debug endpoint."""
    return {
        "users": len(users),
        "products": len(products),
        "orders": len(orders),
        "payments": len(payments),
        "notifications": len(notifications),
    }
