"""LLM client: a thin Anthropic wrapper with a deterministic mock mode.

Two modes, selected by the ``LLM_MODE`` env var (or the constructor):

* ``mock`` (default) — no network, no key. Deterministic, task-aware responses
  generated from the structured ``context`` passed by the caller. Makes the
  whole pipeline reproducible and testable offline.
* ``real`` — calls the Anthropic Messages API. The model is read from
  ``ANTHROPIC_MODEL`` (never hardcoded); the key from ``ANTHROPIC_API_KEY``.

Every call — in either mode — is appended to a JSONL trace so the reasoning
of each agent step is inspectable after the fact.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# A conservative default model *identifier* (string is only a fallback; the
# real value is expected to come from the ANTHROPIC_MODEL env var).
_DEFAULT_MODEL_ENV_FALLBACK = "claude-sonnet-5"

MockHandler = Callable[[dict[str, Any]], dict[str, Any]]
_MOCK_HANDLERS: dict[str, MockHandler] = {}


def mock_task(name: str) -> Callable[[MockHandler], MockHandler]:
    """Register a deterministic mock handler for a named task."""

    def deco(fn: MockHandler) -> MockHandler:
        _MOCK_HANDLERS[name] = fn
        return fn

    return deco


@dataclass
class LLMConfig:
    mode: str = field(default_factory=lambda: os.environ.get("LLM_MODE", "mock").lower())
    model: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL_ENV_FALLBACK))
    api_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY"))
    max_tokens: int = 2048
    trace_path: Path | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"mock", "real"}:
            raise ValueError(f"LLM_MODE must be 'mock' or 'real', got {self.mode!r}")


class LLMClient:
    """Task-oriented client. Callers pass a rendered ``system``/``user`` prompt
    (used by real mode) *and* a structured ``context`` dict (used by mock mode),
    so the same call site works identically in both modes."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig()
        self._anthropic = None  # lazy
        self.calls: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    @property
    def mode(self) -> str:
        return self.config.mode

    @property
    def model(self) -> str:
        return self.config.model

    def complete_json(
        self,
        *,
        task: str,
        system: str,
        user: str,
        context: dict[str, Any],
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Return a parsed JSON object from the model (or mock)."""
        raw = self.complete(
            task=task, system=system, user=user, context=context, max_tokens=max_tokens
        )
        return _extract_json(raw)

    def complete(
        self,
        *,
        task: str,
        system: str,
        user: str,
        context: dict[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        started = time.time()
        if self.config.mode == "mock":
            response = self._mock(task, context)
        else:
            response = self._real(system, user, max_tokens or self.config.max_tokens)
        self._trace(task, system, user, context, response, time.time() - started)
        return response

    # ------------------------------------------------------------------ #
    def _mock(self, task: str, context: dict[str, Any]) -> str:
        handler = _MOCK_HANDLERS.get(task)
        if handler is None:
            raise KeyError(f"no mock handler registered for task {task!r}")
        return json.dumps(handler(context))

    def _real(self, system: str, user: str, max_tokens: int) -> str:
        if not self.config.api_key:
            raise RuntimeError(
                "LLM_MODE=real requires ANTHROPIC_API_KEY to be set in the environment"
            )
        if self._anthropic is None:
            import anthropic  # lazy import: mock mode needs no dependency

            self._anthropic = anthropic.Anthropic(api_key=self.config.api_key)
        message = self._anthropic.messages.create(
            model=self.config.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in message.content if block.type == "text")

    def _trace(
        self,
        task: str,
        system: str,
        user: str,
        context: dict[str, Any],
        response: str,
        elapsed: float,
    ) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": self.config.mode,
            "model": self.config.model if self.config.mode == "real" else "mock",
            "task": task,
            "elapsed_s": round(elapsed, 4),
            "system": system[:400],
            "user": user[:800],
            "context_keys": sorted(context.keys()),
            "response": response[:2000],
        }
        self.calls.append(record)
        if self.config.trace_path is not None:
            self.config.trace_path.parent.mkdir(parents=True, exist_ok=True)
            with self.config.trace_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")


# --------------------------------------------------------------------------- #
# JSON extraction (tolerant of fenced code blocks / prose around the object)
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


# --------------------------------------------------------------------------- #
# Deterministic mock knowledge base + handlers
# --------------------------------------------------------------------------- #

# keyword -> domain lexicon. This is the *only* domain knowledge the mock has;
# it votes over module *content* (routes, entity/field names, function names,
# docstring words) — not privileged access to the ground truth.
DOMAIN_LEXICON: dict[str, list[str]] = {
    "Users/Auth": ["auth", "login", "logout", "session", "password", "register",
                    "token", "credential", "user", "profile", "account", "identity"],
    "Catalog": ["catalog", "product", "sku", "browse", "listing", "price",
                "pricing", "discount", "tax", "quote", "promo"],
    "Inventory": ["inventory", "stock", "reserve", "reserved", "quantity",
                  "warehouse", "availability", "available"],
    "Orders": ["order", "orders", "checkout", "cart", "purchase", "basket",
               "line", "fulfil", "fulfill"],
    "Payments": ["payment", "payments", "charge", "refund", "billing",
                 "provider", "capture", "invoice", "transaction"],
    "Notifications": ["notification", "notifications", "email", "sms", "notify",
                      "dispatch", "message", "receipt", "alert", "send"],
    "Platform": ["config", "settings", "db", "database", "model", "models",
                 "schema", "table", "app", "factory", "blueprint", "kernel",
                 "seed", "snapshot"],
}

# Modules that are structurally shared kernel regardless of keyword noise.
_SHARED_KERNEL = {"config", "db", "models", "app"}


def _domain_scores(tokens: list[str]) -> dict[str, int]:
    scores = {d: 0 for d in DOMAIN_LEXICON}
    joined = " ".join(tokens).lower()
    for domain, kws in DOMAIN_LEXICON.items():
        for kw in kws:
            scores[domain] += joined.count(kw)
    return scores


def vote_domain(tokens: list[str], module: str = "") -> str:
    """Pick the best-matching domain for a bag of content tokens."""
    if module in _SHARED_KERNEL:
        return "Platform"
    scores = _domain_scores(tokens + [module])
    best = max(scores.items(), key=lambda kv: (kv[1], kv[0]))
    return best[0] if best[1] > 0 else "Platform"


@mock_task("summarize_module")
def _mock_summarize_module(ctx: dict[str, Any]) -> dict[str, Any]:
    module = ctx.get("module", "?")
    tokens = ctx.get("keywords", [])
    routes = ctx.get("routes", [])
    entities = ctx.get("entities", [])
    deps = ctx.get("depends_on", [])
    domain = vote_domain(list(tokens), module)

    bits: list[str] = []
    if entities:
        bits.append("owns the " + ", ".join(entities[:4]) + " entity/entities")
    if routes:
        bits.append(f"exposes {len(routes)} HTTP route(s)")
    if deps:
        bits.append("collaborates with " + ", ".join(sorted(deps)[:4]))
    body = "; ".join(bits) if bits else "provides shared, cross-cutting utilities"
    responsibility = (
        f"The `{module}` module belongs to the {domain} context: it {body}."
    )
    return {"responsibility": responsibility, "suggested_domain": domain}


@mock_task("refine_decomposition")
def _mock_refine_decomposition(ctx: dict[str, Any]) -> dict[str, Any]:
    """Refine the algorithmic clusters into named bounded contexts.

    This is where the two signals are *fused*, deterministically:

    * **Structural prior** — each module starts in its dependency cluster, and
      that cluster's majority domain vote is its default label.
    * **Domain reasoning** — a module is re-labelled to its own top content
      domain only when that vote is *confident* (a strict margin over the
      runner-up). Ambiguous modules stay with their structural cluster.
    * Shared-kernel modules are consolidated into a Platform service.

    So confidently-domain modules follow content (splitting coupled clusters
    the graph merged), while ambiguous modules defer to graph structure.
    """
    clusters: list[list[str]] = ctx.get("clusters", [])
    module_tokens: dict[str, list[str]] = ctx.get("module_tokens", {})
    descriptions: dict[str, str] = {
        "Users/Auth": "Identity, authentication and user profiles.",
        "Catalog": "Product catalogue browsing and pricing.",
        "Inventory": "Stock levels and reservations.",
        "Orders": "Cart and checkout orchestration.",
        "Payments": "Charge capture and payment records.",
        "Notifications": "Transactional email/SMS dispatch.",
        "Platform": "Shared kernel: configuration, persistence and models.",
    }

    # structural prior: majority domain per cluster (Platform ignored unless pure)
    cluster_label: dict[str, str] = {}
    for cluster in clusters:
        votes: dict[str, int] = {}
        for m in cluster:
            d = vote_domain(module_tokens.get(m, []), m)
            votes[d] = votes.get(d, 0) + 1
        non_platform = {d: c for d, c in votes.items() if d != "Platform"}
        label = (
            max(non_platform.items(), key=lambda kv: (kv[1], kv[0]))[0]
            if non_platform
            else "Platform"
        )
        for m in cluster:
            cluster_label[m] = label

    grouped: dict[str, list[str]] = {}
    for cluster in clusters:
        for m in cluster:
            if m in _SHARED_KERNEL:
                grouped.setdefault("Platform", []).append(m)
                continue
            scores = _domain_scores(module_tokens.get(m, []) + [m])
            ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
            top, second = ranked[0], ranked[1]
            confident = top[1] > 0 and top[1] > second[1]
            target = top[0] if confident else cluster_label.get(m, "Platform")
            grouped.setdefault(target, []).append(m)

    services = []
    for name in sorted(grouped, key=lambda n: (n == "Platform", n)):
        services.append(
            {
                "name": name,
                "modules": sorted(grouped[name]),
                "description": descriptions.get(name, ""),
                "rationale": "Seeded from dependency-cluster membership, then "
                "re-labelled where module-content domain signal is decisive.",
                "kind": "shared-kernel" if name == "Platform" else "microservice",
            }
        )
    return {"services": services}
