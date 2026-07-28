"""Platform: shared domain entities (the shared kernel of the monolith).

Every bounded context imports from here, which makes ``models`` a natural
hub in the dependency graph — exactly the kind of shared-kernel coupling a
real decomposition has to reason about.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class User:
    id: int
    email: str
    name: str
    password_hash: str = ""
    address: str = ""


@dataclass
class Product:
    id: int
    sku: str
    name: str
    category: str
    base_price: float


@dataclass
class PriceRule:
    product_id: int
    discount_pct: float
    reason: str = "promo"


@dataclass
class InventoryItem:
    product_id: int
    quantity: int
    reserved: int = 0


@dataclass
class CartItem:
    product_id: int
    quantity: int


@dataclass
class Cart:
    user_id: int
    items: list[CartItem] = field(default_factory=list)


@dataclass
class OrderLine:
    product_id: int
    quantity: int
    unit_price: float


@dataclass
class Order:
    id: int
    user_id: int
    lines: list[OrderLine]
    total: float
    status: str = "created"
    payment_id: int | None = None


@dataclass
class Payment:
    id: int
    order_id: int
    user_id: int
    amount: float
    status: str = "pending"
    provider_ref: str = ""


@dataclass
class Notification:
    id: int
    user_id: int
    channel: str
    subject: str
    body: str
    sent: bool = False


def to_dict(entity: Any) -> dict[str, Any]:
    """Serialise any dataclass entity to a plain dict (used by all routes)."""
    return asdict(entity)
