"""Repo Analyzer agent — static analysis of the monolith via the ``ast`` module.

Extracts, per module: imports (internal vs external, weighted by usage),
functions, classes, Flask routes, and persistent entities. Then hands off to
``core.graph`` to build the dependency graph and to the LLM (or mock) to
enrich each context pack with a natural-language responsibility summary.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from agents.llm_client import LLMClient
from core.context_pack import (
    ClassInfo,
    ContextPack,
    Dependency,
    Entity,
    FunctionInfo,
    RepoAnalysis,
    Route,
)
from core.graph import build_digraph, graph_artifact

_HTTP_DECORATORS = {"get", "post", "put", "delete", "patch"}
_STOPWORDS = {
    "self", "cls", "the", "and", "for", "from", "with", "into", "this", "that",
    "import", "return", "none", "true", "false", "def", "class", "int", "str",
    "list", "dict", "get", "post", "json", "request", "jsonify", "blueprint",
    "flask", "bp", "app", "data", "payload", "value", "item", "items",
}


class RepoAnalyzer:
    def __init__(self, root: Path, package: str, llm: LLMClient) -> None:
        self.root = Path(root)
        self.package = package
        self.llm = llm

    # ------------------------------------------------------------------ #
    def analyze(self) -> RepoAnalysis:
        packs = [self._analyze_module(p) for p in self._module_files()]
        packs.sort(key=lambda pk: pk.module)
        self._resolve_internal_imports(packs)
        for pack in packs:
            self._enrich(pack)
        digraph = build_digraph(packs)
        analysis = RepoAnalysis(
            # Repo-relative, matching ContextPack.path ("monolith/orders.py").
            # An absolute path would leak the local directory layout and make
            # generated/analysis.json irreproducible on any other machine.
            root=self.root.name,
            packs=packs,
            graph=graph_artifact(digraph),
            llm_mode=self.llm.mode,
            model=self.llm.model if self.llm.mode == "real" else "mock",
        )
        return analysis

    # ------------------------------------------------------------------ #
    def _module_files(self) -> list[Path]:
        return sorted(
            p for p in self.root.glob("*.py") if p.name != "__init__.py"
        )

    def _analyze_module(self, path: Path) -> ContextPack:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        module = path.stem

        module_alias, name_from_module = self._collect_imports(tree)
        external = self._collect_external(tree)
        usage = self._count_usage(tree, module_alias, name_from_module)

        deps: list[Dependency] = []
        for target, info in sorted(usage.items()):
            deps.append(Dependency(target=target, kind=info["kind"], weight=info["weight"]))

        functions = self._collect_functions(tree)
        classes = self._collect_classes(tree)
        url_prefix = self._blueprint_prefix(tree)
        routes = self._collect_routes(tree, url_prefix)
        entities = self._collect_entities(tree, module)

        keywords = self._keywords(module, tree, functions, classes, routes, entities)
        public = [f.name for f in functions if f.is_public] + [c.name for c in classes]

        return ContextPack(
            module=module,
            path=str(path.relative_to(self.root.parent)),
            loc=source.count("\n") + 1,
            url_prefix=url_prefix,
            imports_internal=deps,
            imports_external=sorted(external),
            functions=functions,
            classes=classes,
            routes=routes,
            entities=entities,
            keywords=keywords,
            public_interface=sorted(set(public)),
        )

    # ---- imports ----------------------------------------------------- #
    def _collect_imports(self, tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
        """Return (alias->module, imported_name->module) for internal imports."""
        module_alias: dict[str, str] = {}
        name_from_module: dict[str, str] = {}
        pkg = self.package
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == pkg:
                    # from monolith import catalog, db
                    for alias in node.names:
                        module_alias[alias.asname or alias.name] = alias.name
                elif mod.startswith(pkg + "."):
                    # from monolith.models import User, to_dict
                    target = mod.split(".", 1)[1].split(".")[0]
                    for alias in node.names:
                        name_from_module[alias.asname or alias.name] = target
                elif node.level and mod:
                    # relative: from .models import X
                    target = mod.split(".")[0]
                    for alias in node.names:
                        name_from_module[alias.asname or alias.name] = target
                elif node.level and not mod:
                    # from . import catalog, db
                    for alias in node.names:
                        module_alias[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(pkg + "."):
                        target = alias.name.split(".", 1)[1].split(".")[0]
                        module_alias[alias.asname or target] = target
        return module_alias, name_from_module

    def _collect_external(self, tree: ast.AST) -> set[str]:
        external: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod and not mod.startswith(self.package) and not node.level:
                    external.add(mod.split(".")[0])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if not alias.name.startswith(self.package):
                        external.add(alias.name.split(".")[0])
        return external

    def _count_usage(
        self, tree: ast.AST, module_alias: dict[str, str], name_from_module: dict[str, str]
    ) -> dict[str, dict]:
        """Weight each internal target by import(+1) plus every referencing use."""
        usage: dict[str, dict] = {}

        def bump(target: str, kind: str) -> None:
            entry = usage.setdefault(target, {"weight": 0, "kinds": set()})
            entry["weight"] += 1
            entry["kinds"].add(kind)

        for target in set(module_alias.values()) | set(name_from_module.values()):
            bump(target, "import")

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id in module_alias:
                    bump(module_alias[node.value.id], "attr")
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id in name_from_module:
                    bump(name_from_module[node.id], "call")

        return {
            t: {"weight": e["weight"], "kind": _dominant_kind(e["kinds"])}
            for t, e in usage.items()
        }

    # ---- functions / classes ---------------------------------------- #
    def _collect_functions(self, tree: ast.AST) -> list[FunctionInfo]:
        funcs: list[FunctionInfo] = []
        for node in tree.body if isinstance(tree, ast.Module) else []:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = sorted({
                    _call_name(c) for c in ast.walk(node)
                    if isinstance(c, ast.Call) and _call_name(c)
                })
                funcs.append(FunctionInfo(
                    name=node.name,
                    args=[a.arg for a in node.args.args if a.arg not in {"self", "cls"}],
                    calls=calls,
                    is_public=not node.name.startswith("_"),
                ))
        return funcs

    def _collect_classes(self, tree: ast.AST) -> list[ClassInfo]:
        classes: list[ClassInfo] = []
        for node in tree.body if isinstance(tree, ast.Module) else []:
            if isinstance(node, ast.ClassDef):
                methods = [n.name for n in node.body
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                classes.append(ClassInfo(
                    name=node.name,
                    bases=[_expr_name(b) for b in node.bases if _expr_name(b)],
                    methods=methods,
                ))
        return classes

    # ---- routes ------------------------------------------------------ #
    def _blueprint_prefix(self, tree: ast.AST) -> str | None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                if _call_name(node.value) == "Blueprint":
                    for kw in node.value.keywords:
                        if kw.arg == "url_prefix" and isinstance(kw.value, ast.Constant):
                            return str(kw.value.value)
        return None

    def _collect_routes(self, tree: ast.AST, url_prefix: str | None) -> list[Route]:
        routes: list[Route] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                route = self._route_from_decorator(dec, node.name, url_prefix)
                if route:
                    routes.append(route)
        return routes

    def _route_from_decorator(
        self, dec: ast.AST, handler: str, url_prefix: str | None
    ) -> Route | None:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
            return None
        verb = dec.func.attr
        path = ""
        if dec.args and isinstance(dec.args[0], ast.Constant):
            path = str(dec.args[0].value)
        full = (url_prefix or "") + path
        full = full or "/"
        if verb in _HTTP_DECORATORS:
            return Route(method=verb.upper(), path=full, handler=handler)
        if verb == "route":
            method = "GET"
            for kw in dec.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    elts = [e.value for e in kw.value.elts if isinstance(e, ast.Constant)]
                    if elts:
                        method = str(elts[0]).upper()
            return Route(method=method, path=full, handler=handler)
        return None

    # ---- entities ---------------------------------------------------- #
    def _collect_entities(self, tree: ast.AST, module: str) -> list[Entity]:
        entities: list[Entity] = []
        for node in tree.body if isinstance(tree, ast.Module) else []:
            if isinstance(node, ast.ClassDef) and _is_dataclass(node):
                fields: list[str] = []
                annotations: dict[str, str] = {}
                for n in node.body:
                    if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                        fields.append(n.target.id)
                        annotations[n.target.id] = ast.unparse(n.annotation)
                entities.append(Entity(name=node.name, fields=fields, annotations=annotations))
            # db.py declares tables as a module-level (possibly annotated) tuple
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if any(isinstance(t, ast.Name) and t.id == "TABLES" for t in targets):
                if isinstance(value, (ast.Tuple, ast.List)):
                    names = [e.value for e in value.elts if isinstance(e, ast.Constant)]
                    entities.append(Entity(name="TABLES", fields=names))
        return entities

    # ---- keywords ---------------------------------------------------- #
    def _keywords(self, module, tree, functions, classes, routes, entities) -> list[str]:
        tokens: list[str] = [module]
        doc = ast.get_docstring(tree) or ""
        tokens += _tokenize(doc)
        for f in functions:
            tokens += _tokenize(f.name)
        for c in classes:
            tokens += _tokenize(c.name)
        for r in routes:
            tokens += _tokenize(r.path)
        for e in entities:
            tokens += _tokenize(e.name) + [t for fld in e.fields for t in _tokenize(fld)]
        seen: list[str] = []
        for t in tokens:
            if t and t not in _STOPWORDS and len(t) > 2 and t not in seen:
                seen.append(t)
        return seen

    # ------------------------------------------------------------------ #
    def _resolve_internal_imports(self, packs: list[ContextPack]) -> None:
        """Drop dependency edges to targets that are not real modules."""
        known = {p.module for p in packs}
        for pack in packs:
            pack.imports_internal = [
                d for d in pack.imports_internal if d.target in known
            ]

    def _enrich(self, pack: ContextPack) -> None:
        """Add the LLM (or mock) natural-language responsibility summary."""
        context = {
            "module": pack.module,
            "keywords": pack.keywords,
            "routes": [f"{r.method} {r.path}" for r in pack.routes],
            "entities": [e.name for e in pack.entities],
            "depends_on": pack.fan_out(),
        }
        system = (
            "You are a senior software architect performing static analysis of a "
            "monolith. Given structured facts about ONE module, write a concise "
            "one-sentence responsibility summary and name the most likely bounded "
            'context. Respond ONLY as JSON: {"responsibility": str, "suggested_domain": str}.'
        )
        user = (
            f"Module `{pack.module}` facts:\n"
            f"- keywords: {', '.join(pack.keywords[:20])}\n"
            f"- routes: {context['routes']}\n"
            f"- entities: {context['entities']}\n"
            f"- imports internal modules: {context['depends_on']}\n"
        )
        result = self.llm.complete_json(
            task="summarize_module", system=system, user=user, context=context
        )
        pack.responsibility = result.get("responsibility", "")
        pack.suggested_domain = result.get("suggested_domain", "")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _dominant_kind(kinds: set[str]) -> str:
    for k in ("call", "attr", "import"):
        if k in kinds:
            return k
    return "import"


def _call_name(call: ast.Call) -> str:
    return _expr_name(call.func)


def _expr_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_dataclass(node: ast.ClassDef) -> bool:
    for dec in node.decorator_list:
        if _expr_name(dec) == "dataclass" or (
            isinstance(dec, ast.Call) and _call_name(dec) == "dataclass"
        ):
            return True
    return False


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in re.split(r"[^A-Za-z]+", text) if t]
