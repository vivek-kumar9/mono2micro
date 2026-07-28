"""Synthetic e-commerce Flask monolith used as the migration subject.

Bounded contexts (see ``eval/ground_truth.json``):
    Platform (shared kernel) : config, db, models, app
    Users/Auth               : auth, users
    Catalog                  : catalog, pricing
    Inventory                : inventory
    Orders                   : orders, cart
    Payments                 : payments
    Notifications            : notifications

The modules deliberately import across contexts (Orders touches nearly
everything) so that community detection on the dependency graph is a
non-trivial problem with a meaningful ground-truth partition.
"""
