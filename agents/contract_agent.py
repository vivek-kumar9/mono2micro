"""Contract agent — derives an OpenAPI 3.1 spec for each proposed service.

Endpoints come from the Flask routes owned by the service's modules; schemas
are reconstructed from the monolith's dataclass entities (typed from their real
annotations). The Orders spec is the source of truth for code generation:
``codegen_agent`` builds the FastAPI service from it and ``contract_test_agent``
validates the live service against it.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from core.context_pack import Entity, RepoAnalysis, ServiceProposal

# resource-name -> entity-name aliases where naive singularisation fails
_ENTITY_ALIASES = {"inventory": "InventoryItem", "item": "CartItem"}


class ContractAgent:
    def __init__(self, analysis: RepoAnalysis) -> None:
        self.analysis = analysis
        self.by_module = analysis.pack_by_module()
        # global entity registry (entities live in the shared kernel / models.py)
        self.entities: dict[str, Entity] = {}
        for pack in analysis.packs:
            for ent in pack.entities:
                if ent.name != "TABLES":
                    self.entities[ent.name] = ent

    # ------------------------------------------------------------------ #
    def generate_all(self, services: list[ServiceProposal], out_dir: Path) -> dict[str, dict]:
        out_dir.mkdir(parents=True, exist_ok=True)
        specs: dict[str, dict] = {}
        for svc in services:
            routes = [r for m in svc.modules for r in self._routes(m)]
            if not routes:
                continue  # e.g. Platform / shared kernel has no HTTP surface
            spec = self.generate_for_service(svc)
            fname = _slug(svc.name) + ".yaml"
            (out_dir / fname).write_text(
                yaml.safe_dump(spec, sort_keys=False), encoding="utf-8"
            )
            specs[svc.name] = spec
        return specs

    def _routes(self, module: str):
        pack = self.by_module.get(module)
        return pack.routes if pack else []

    # ------------------------------------------------------------------ #
    def generate_for_service(self, svc: ServiceProposal) -> dict:
        paths: dict[str, dict] = {}
        needed: set[str] = set()

        for module in svc.modules:
            for route in self._routes(module):
                oapi_path, params = _convert_path(route.path)
                resource = self._resource_entity(route.path)
                if resource:
                    needed.add(resource)
                operation = self._operation(svc, route, oapi_path, params, resource)
                paths.setdefault(oapi_path, {})[route.method.lower()] = operation

        schemas = self._collect_schemas(needed)
        return {
            "openapi": "3.1.0",
            "info": {
                "title": f"{svc.name} Service API",
                "version": "1.0.0",
                "description": svc.description or f"Extracted {svc.name} microservice.",
            },
            "servers": [{"url": f"http://{_slug(svc.name).lower()}:8000"}],
            "paths": paths,
            "components": {"schemas": schemas} if schemas else {"schemas": {}},
        }

    # ------------------------------------------------------------------ #
    def _operation(self, svc, route, oapi_path, params, resource) -> dict:
        op: dict = {
            "operationId": _operation_id(route.method, oapi_path),
            "summary": f"{route.method} {route.path}",
            "tags": [svc.name],
        }
        if params:
            op["parameters"] = [
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer" if typ == "int" else "string"},
                }
                for name, typ in params
            ]

        ref = {"$ref": f"#/components/schemas/{resource}"} if resource else {"type": "object"}
        method = route.method.upper()

        if method in {"POST", "PUT", "PATCH"}:
            op["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": {"type": "object"}}},
            }
            op["responses"] = {
                "201": {"description": "Created", "content": {"application/json": {"schema": ref}}},
                "400": {"description": "Invalid request"},
            }
        elif method == "GET" and params:
            op["responses"] = {
                "200": {"description": "OK", "content": {"application/json": {"schema": ref}}},
                "404": {"description": "Not found"},
            }
        else:  # GET collection
            op["responses"] = {
                "200": {
                    "description": "OK",
                    "content": {"application/json": {"schema": {"type": "array", "items": ref}}},
                }
            }
        return op

    # ------------------------------------------------------------------ #
    def _resource_entity(self, path: str) -> str | None:
        segments = [s for s in path.split("/") if s and not s.startswith("<")]
        for seg in reversed(segments):
            name = _singular(seg)
            if name in _ENTITY_ALIASES and _ENTITY_ALIASES[name] in self.entities:
                return _ENTITY_ALIASES[name]
            cand = name.capitalize()
            for ename in self.entities:
                if ename.lower() == name:
                    return ename
            if cand in self.entities:
                return cand
        return None

    def _collect_schemas(self, roots: set[str]) -> dict:
        # Set iteration order depends on PYTHONHASHSEED, which Python
        # randomises per process. Seeding the stack from a bare set — and
        # extending it with a bare set difference — made the emitted schema
        # order vary from run to run, so `make contracts` produced a spurious
        # diff on roughly three runs in four. Sort the traversal, and sort the
        # result, so the generated specs are byte-stable.
        schemas: dict[str, dict] = {}
        stack = sorted(roots, reverse=True)   # reverse: pop() takes the last
        while stack:
            name = stack.pop()
            if name in schemas or name not in self.entities:
                continue
            schema, refs = self._entity_schema(self.entities[name])
            schemas[name] = schema
            stack.extend(sorted(refs - set(schemas), reverse=True))
        return {name: schemas[name] for name in sorted(schemas)}

    def _entity_schema(self, entity: Entity) -> tuple[dict, set[str]]:
        properties: dict[str, dict] = {}
        required: list[str] = []
        refs: set[str] = set()
        for field in entity.fields:
            annotation = entity.annotations.get(field, "str")
            schema, nested, nullable = self._type_schema(annotation)
            properties[field] = schema
            refs |= nested
            if not nullable:
                required.append(field)
        return (
            {"type": "object", "properties": properties, "required": required},
            refs,
        )

    def _type_schema(self, annotation: str) -> tuple[dict, set[str], bool]:
        t = annotation.strip()
        # Optional / X | None
        for suffix in ("| None", "|None"):
            if t.endswith(suffix):
                inner, refs, _ = self._type_schema(t[: -len(suffix)].strip())
                return {"anyOf": [inner, {"type": "null"}]}, refs, True
        if t.startswith("Optional[") and t.endswith("]"):
            inner, refs, _ = self._type_schema(t[9:-1])
            return {"anyOf": [inner, {"type": "null"}]}, refs, True
        # list[X]
        m = re.match(r"^(?:list|List)\[(.+)\]$", t)
        if m:
            item, refs, _ = self._type_schema(m.group(1))
            return {"type": "array", "items": item}, refs, False
        primitive = {"int": "integer", "float": "number", "str": "string",
                     "bool": "boolean"}.get(t)
        if primitive:
            return {"type": primitive}, set(), False
        if t in self.entities:
            return {"$ref": f"#/components/schemas/{t}"}, {t}, False
        return {"type": "string"}, set(), False


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_spec(spec: dict) -> list[str]:
    """Lightweight structural validation of an OpenAPI 3.1 document.

    Uses ``openapi-spec-validator`` if it happens to be installed, otherwise
    falls back to dependency-free structural checks (version, non-empty paths,
    every operation has responses, every ``$ref`` resolves).
    """
    try:  # optional stronger validation
        from openapi_spec_validator import validate as _validate  # type: ignore

        _validate(spec)
    except ImportError:
        pass
    except Exception as exc:  # pragma: no cover - surfaced to caller
        return [f"openapi-spec-validator: {exc}"]

    errors: list[str] = []
    if not str(spec.get("openapi", "")).startswith("3.1"):
        errors.append("openapi version must be 3.1.x")
    if not spec.get("paths"):
        errors.append("no paths defined")
    defined = set((spec.get("components", {}).get("schemas", {}) or {}).keys())
    for path, item in (spec.get("paths") or {}).items():
        for method, op in item.items():
            if "responses" not in op:
                errors.append(f"{method.upper()} {path}: missing responses")
    for ref in _iter_refs(spec):
        name = ref.split("/")[-1]
        if name not in defined:
            errors.append(f"unresolved $ref: {ref}")
    return errors


def _iter_refs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from _iter_refs(v)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_refs(item)


# --------------------------------------------------------------------------- #
def _convert_path(flask_path: str) -> tuple[str, list[tuple[str, str]]]:
    """`/orders/<int:order_id>` -> (`/orders/{order_id}`, [("order_id","int")])."""
    params: list[tuple[str, str]] = []

    def repl(match: re.Match) -> str:
        conv, name = match.group(1), match.group(2)
        params.append((name, conv or "str"))
        return "{" + name + "}"

    path = re.sub(r"<(?:(\w+):)?(\w+)>", repl, flask_path)
    return path or "/", params


def _operation_id(method: str, path: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_") or "root"
    return f"{method.lower()}_{slug}"


def _singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
