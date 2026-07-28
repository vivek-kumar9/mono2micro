"""Users/Auth: authentication and session issuance."""
from __future__ import annotations

import hashlib
import secrets

from flask import Blueprint, jsonify, request

from monolith import db, users
from monolith.config import CONFIG

bp = Blueprint("auth", __name__, url_prefix="/auth")

_sessions: dict[str, int] = {}


def hash_password(raw: str) -> str:
    return "hash:" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def issue_session(user_id: int) -> str:
    token = secrets.token_hex(8)
    _sessions[token] = user_id
    return token


@bp.post("/register")
def register():
    payload = request.get_json(force=True)
    # cross-context call into Users
    user = users.create_user(
        email=payload["email"],
        name=payload["name"],
        password_hash=hash_password(payload["password"]),
        address=payload.get("address", ""),
    )
    return jsonify({"user_id": user.id, "session_ttl": CONFIG.session_ttl_seconds}), 201


@bp.post("/login")
def login():
    payload = request.get_json(force=True)
    for user in db.users.values():
        if user.email == payload["email"] and user.password_hash == hash_password(payload["password"]):
            return jsonify({"token": issue_session(user.id), "user_id": user.id})
    return jsonify({"error": "invalid credentials"}), 401
