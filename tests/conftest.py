"""Shared pytest fixtures. Ensures the project root is importable and provides
cached analysis artifacts for the tooling tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.llm_client import LLMClient, LLMConfig  # noqa: E402
from agents.repo_analyzer import RepoAnalyzer  # noqa: E402


@pytest.fixture(scope="session")
def llm() -> LLMClient:
    return LLMClient(LLMConfig(mode="mock"))


@pytest.fixture(scope="session")
def analysis(llm):
    return RepoAnalyzer(ROOT / "monolith", "monolith", llm).analyze()


@pytest.fixture(scope="session")
def ground_truth() -> dict[str, str]:
    data = json.loads((ROOT / "eval" / "ground_truth.json").read_text())
    return data["assignments"]
