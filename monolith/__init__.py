"""Synthetic e-commerce Flask monolith used as the migration subject.

Bounded contexts (see ``eval/ground_truth.json``):
    Platform (shared kernel) : config, db, models, app
    Users/Auth               : auth, users
    Catalog                  : discovery, rating
    Inventory                : inventory
    Orders                   : orders, basket, logistics
    Payments                 : payments
    Notifications            : notifications

Modules import across context boundaries — Orders reaches most of them — so
community detection on the dependency graph is non-trivial.
"""
