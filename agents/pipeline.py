"""Dispatcher for compound orchestrator commands (contracts / generate / all)."""
from __future__ import annotations

from pathlib import Path

from agents.contract_agent import ContractAgent, validate_spec

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = ROOT / "generated" / "contracts"


def contracts(orch) -> dict[str, dict]:
    analysis = orch.load_analysis()
    decomposition = orch.load_decomposition()
    agent = ContractAgent(analysis)
    specs = agent.generate_all(decomposition.services, CONTRACTS_DIR)
    print(f"[contracts] generated {len(specs)} OpenAPI 3.1 spec(s) in "
          f"{CONTRACTS_DIR.relative_to(ROOT)}:")
    ok = True
    for name, spec in specs.items():
        errors = validate_spec(spec)
        status = "valid" if not errors else "INVALID: " + "; ".join(errors)
        n_paths = len(spec.get("paths", {}))
        n_schemas = len(spec.get("components", {}).get("schemas", {}))
        print(f"    - {name:14s} paths={n_paths} schemas={n_schemas} [{status}]")
        ok = ok and not errors
    if not ok:
        raise SystemExit("[contracts] one or more specs failed validation")
    return specs


def generate(orch) -> None:
    from agents import codegen  # imported here: only needed for `generate`

    codegen.run(orch)


def dispatch(orch, command: str) -> None:
    if command == "contracts":
        contracts(orch)
    elif command == "generate":
        generate(orch)
    elif command == "all":
        orch.analyze()
        orch.decompose()
        contracts(orch)
        print("[all] analyze -> decompose -> contracts complete. "
              "Next: `review`/`approve`, then `generate`.")
