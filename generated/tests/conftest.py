"""Fixtures for the generated contract tests. AUTO-GENERATED."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

GENERATED = Path(__file__).resolve().parents[1]
SERVICE_DIR = GENERATED / "services" / "orders"
CONTRACT = GENERATED / "contracts" / "Orders.yaml"
sys.path.insert(0, str(SERVICE_DIR))


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    import main  # generated service entrypoint

    return TestClient(main.app)


@pytest.fixture(scope="session")
def spec() -> dict:
    return yaml.safe_load(CONTRACT.read_text())


def _rewrite_refs(node):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            node["$ref"] = ref.replace("#/components/schemas/", "#/$defs/")
        for value in node.values():
            _rewrite_refs(value)
    elif isinstance(node, list):
        for value in node:
            _rewrite_refs(value)


def response_schema(spec, path, method, status):
    op = spec["paths"][path][method.lower()]
    content = op["responses"][str(status)].get("content")
    if not content:
        return None
    schema = copy.deepcopy(content["application/json"]["schema"])
    _rewrite_refs(schema)
    defs = copy.deepcopy(spec.get("components", {}).get("schemas", {}))
    for d in defs.values():
        _rewrite_refs(d)
    schema["$defs"] = defs
    return schema


@pytest.fixture(scope="session")
def validate_body():
    def _validate(spec, path, method, status, body):
        schema = response_schema(spec, path, method, status)
        if schema is None:
            return
        Draft202012Validator(schema).validate(body)

    return _validate
