"""Contract-test agent — generates pytest that checks the live service against
its OpenAPI contract (status codes + response-body schema conformance).

The generated tests drive the service via ``fastapi.testclient.TestClient`` (so
``pytest generated/tests`` runs offline) and validate each response body against
the contract's response schema using ``jsonschema`` (OpenAPI 3.1 == JSON Schema
2020-12), with ``#/components/schemas`` refs rewritten to local ``$defs``.
"""
from __future__ import annotations

import json
import re


class ContractTestAgent:
    def __init__(self, spec: dict, service_slug: str, contract_filename: str) -> None:
        self.spec = spec
        self.slug = service_slug
        self.contract_filename = contract_filename

    def generate(self) -> dict[str, str]:
        return {
            "conftest.py": self._conftest(),
            f"test_{self.slug}_contract.py": self._test_file(),
        }

    def _cases(self) -> list[tuple[str, str, str, int]]:
        """(method, path_template, concrete_path, expected_status)."""
        cases: list[tuple[str, str, str, int]] = []
        for path, item in self.spec.get("paths", {}).items():
            concrete = _concretise(path)
            for method, op in item.items():
                success = min(
                    (int(c) for c in op.get("responses", {}) if str(c).startswith("2")),
                    default=200,
                )
                cases.append((method.upper(), path, concrete, success))
        return cases

    def _conftest(self) -> str:
        return _CONFTEST_TEMPLATE.replace("%SLUG%", self.slug).replace(
            "%CONTRACT%", self.contract_filename
        )

    def _test_file(self) -> str:
        cases_src = json.dumps(self._cases(), indent=4)
        return _TEST_TEMPLATE.replace("%SLUG%", self.slug).replace("%CASES%", cases_src)


def _concretise(path: str) -> str:
    """Replace `{param}` path templates with a sample id of 1."""
    return re.sub(r"\{[^}]+\}", "1", path)


# --------------------------------------------------------------------------- #
# Emitted test source — plain templates (no f-strings) so literal braces in the
# generated code need no escaping.
# --------------------------------------------------------------------------- #
_CONFTEST_TEMPLATE = '''"""Fixtures for the generated contract tests. AUTO-GENERATED."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

GENERATED = Path(__file__).resolve().parents[1]
SERVICE_DIR = GENERATED / "services" / "%SLUG%"
CONTRACT = GENERATED / "contracts" / "%CONTRACT%"
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
'''

_TEST_TEMPLATE = '''"""Contract tests for the %SLUG% service. AUTO-GENERATED.

Each case exercises one operation and asserts (1) the status code matches the
contract and (2) the response body conforms to the contract's response schema.
"""
from __future__ import annotations

import pytest

# (method, path_template, concrete_path, expected_status)
CASES = %CASES%


@pytest.mark.parametrize("method,template,concrete,status", CASES)
def test_status_and_schema(client, spec, validate_body, method, template, concrete, status):
    kwargs = {"json": {}} if method in {"POST", "PUT", "PATCH"} else {}
    resp = client.request(method, concrete, **kwargs)
    assert resp.status_code == status, method + " " + concrete + " -> " + str(resp.status_code) + ": " + resp.text
    validate_body(spec, template, method, status, resp.json())


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"].endswith("-service")


def test_served_by_header(client):
    resp = client.get("/health")
    assert resp.headers.get("X-Served-By", "").endswith("-service")
'''
