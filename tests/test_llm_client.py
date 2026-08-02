"""LLM client: mock determinism, JSON extraction, real-mode guardrails."""
from __future__ import annotations

import pytest

from agents.llm_client import LLMClient, LLMConfig, _extract_json, vote_domain


def test_mock_is_deterministic():
    c1 = LLMClient(LLMConfig(mode="mock"))
    c2 = LLMClient(LLMConfig(mode="mock"))
    ctx = {"module": "payments", "keywords": ["charge", "payment", "capture"],
           "routes": ["POST /payments/charge"], "entities": ["Payment"], "depends_on": ["db"]}
    a = c1.complete(task="summarize_module", system="s", user="u", context=ctx)
    b = c2.complete(task="summarize_module", system="s", user="u", context=ctx)
    assert a == b


def test_vote_domain_content():
    assert vote_domain(["charge", "capture", "provider"], "payments") == "Payments"
    assert vote_domain(["stock", "reserve", "available"], "inventory") == "Inventory"
    assert vote_domain([], "db") == "Platform"  # shared kernel by structure


def test_extract_json_from_fence():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('noise {"a": 2} trailing') == {"a": 2}


def test_config_rejects_bad_mode():
    with pytest.raises(ValueError):
        LLMConfig(mode="banana")


def test_real_mode_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = LLMClient(LLMConfig(mode="real", api_key=None))
    with pytest.raises(RuntimeError):
        client.complete(task="summarize_module", system="s", user="u", context={})


def test_unknown_task_raises():
    client = LLMClient(LLMConfig(mode="mock"))
    with pytest.raises(KeyError):
        client.complete(task="does_not_exist", system="s", user="u", context={})


def test_model_never_hardcoded_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test-model-xyz")
    cfg = LLMConfig()
    assert cfg.model == "claude-test-model-xyz"


def test_real_mode_wiring_with_fake_sdk(monkeypatch):
    """Exercise the real code path with a faked Anthropic SDK: the client must
    pass the env-configured model through and parse the JSON text response."""
    import sys
    import types

    captured = {}

    class _Block:
        type = "text"
        text = '{"responsibility": "does X", "suggested_domain": "Orders"}'

    class _Message:
        content = [_Block()]

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Message()

    class _Anthropic:
        def __init__(self, api_key=None):
            captured["api_key"] = api_key
            self.messages = _Messages()

    fake = types.ModuleType("anthropic")
    fake.Anthropic = _Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake)

    client = LLMClient(LLMConfig(mode="real", model="claude-configured-xyz", api_key="sk-test"))
    result = client.complete_json(
        task="summarize_module", system="s", user="u", context={"module": "orders"}
    )
    assert result["suggested_domain"] == "Orders"
    assert captured["model"] == "claude-configured-xyz"  # env model flows through
    assert captured["api_key"] == "sk-test"
