"""Platform: application configuration (shared kernel)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """Central configuration object shared by every module."""

    env: str = os.environ.get("APP_ENV", "dev")
    currency: str = "USD"
    tax_rate: float = 0.08
    free_shipping_threshold: float = 50.0
    payment_provider: str = os.environ.get("PAYMENT_PROVIDER", "stripe-sandbox")
    notification_channels: list[str] = field(default_factory=lambda: ["email", "sms"])
    session_ttl_seconds: int = 3600


CONFIG = Config()
