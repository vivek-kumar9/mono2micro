"""Users/Auth: user profile management."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from monolith import db, notifications
from monolith.models import User, to_dict

bp = Blueprint("users", __name__, url_prefix="/users")


def get_user(user_id: int) -> User | None:
    return db.users.get(user_id)


def create_user(email: str, name: str, password_hash: str, address: str = "") -> User:
    user = User(id=db.next_user_id(), email=email, name=name,
                password_hash=password_hash, address=address)
    db.users[user.id] = user
    # cross-context call: welcome notification
    notifications.enqueue(user.id, "email", "Welcome", f"Hi {name}, welcome!")
    return user


@bp.get("")
def list_users():
    return jsonify([to_dict(u) for u in db.users.values()])


@bp.get("/<int:user_id>")
def fetch_user(user_id: int):
    user = get_user(user_id)
    if user is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(to_dict(user))


@bp.post("")
def add_user():
    payload = request.get_json(force=True)
    user = create_user(payload["email"], payload["name"],
                       payload.get("password_hash", ""), payload.get("address", ""))
    return jsonify(to_dict(user)), 201
