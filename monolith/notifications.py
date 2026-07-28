"""Notifications: transactional email/SMS dispatch."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from monolith import db
from monolith.config import CONFIG
from monolith.models import Notification, to_dict

bp = Blueprint("notifications", __name__, url_prefix="/notifications")


def enqueue(user_id: int, channel: str, subject: str, body: str) -> Notification:
    if channel not in CONFIG.notification_channels:
        channel = CONFIG.notification_channels[0]
    note = Notification(id=db.next_notification_id(), user_id=user_id,
                        channel=channel, subject=subject, body=body)
    db.notifications[note.id] = note
    return note


def dispatch(note: Notification) -> Notification:
    # recipient contact lookup crosses into the Users context
    user = db.users.get(note.user_id)
    if user is not None:
        note.sent = True
    return note


@bp.post("/send")
def send():
    payload = request.get_json(force=True)
    note = enqueue(payload["user_id"], payload.get("channel", "email"),
                   payload["subject"], payload["body"])
    dispatch(note)
    return jsonify(to_dict(note)), 201
