"""Shared pytest fixtures. Ensures the project root is importable and exposes
the ground-truth partition used by the monolith tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def ground_truth() -> dict[str, str]:
    data = json.loads((ROOT / "eval" / "ground_truth.json").read_text())
    return data["assignments"]
