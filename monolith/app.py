"""Platform: Flask application factory (the composition root).

Registers every bounded-context blueprint. In the dependency graph this
module is the fan-out hub that imports all others.
"""
from __future__ import annotations

from flask import Flask, jsonify

from monolith import (
    auth,
    basket,
    db,
    discovery,
    logistics,
    inventory,
    notifications,
    orders,
    payments,
    rating,
    users,
)
from monolith.config import CONFIG

BLUEPRINTS = (
    auth.bp,
    users.bp,
    discovery.bp,
    rating.bp,
    inventory.bp,
    basket.bp,
    orders.bp,
    logistics.bp,
    payments.bp,
    notifications.bp,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["ENV"] = CONFIG.env
    db.seed()
    for bp in BLUEPRINTS:
        app.register_blueprint(bp)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "monolith", "tables": db.snapshot()})

    @app.get("/")
    def index():
        return jsonify({"service": "ecommerce-monolith", "contexts": len(BLUEPRINTS)})

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
