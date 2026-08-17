"""Phase 3 driver: enforce the HITL gate, then generate the strangler topology.

Consumes the *approved* decomposition (never the raw proposal) and emits, for
the approved extraction target:
    generated/services/<slug>/   FastAPI microservice skeleton
    generated/gateway/           strangler-fig gateway + route table
    generated/tests/             pytest contract tests
Nothing here runs unless ``eval/approved_decomposition.json`` says approved.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from agents.codegen_agent import CodegenAgent
from agents.contract_agent import ContractAgent
from agents.contract_test_agent import ContractTestAgent
from agents.routing_agent import RoutingAgent
from core.context_pack import ApprovedDecomposition

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "generated"
EVAL = ROOT / "eval"


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def _write_tree(base: Path, files: dict[str, str]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        (base / rel).write_text(content, encoding="utf-8")


def run(orch) -> None:
    approved_path = EVAL / "approved_decomposition.json"
    if not approved_path.exists():
        raise SystemExit(
            "[generate] BLOCKED: no approved decomposition. "
            "Run the Streamlit review UI or `python -m agents.orchestrator approve` first."
        )
    approved = ApprovedDecomposition.model_validate_json(approved_path.read_text())
    if not approved.approved:
        raise SystemExit("[generate] BLOCKED: decomposition exists but is not approved.")

    analysis = orch.load_analysis()
    target = approved.extraction_target
    slug = _slug(target).lower()

    # (Re)generate contracts from the *approved* services so codegen matches HITL edits.
    contract_agent = ContractAgent(analysis)
    contracts_dir = GENERATED / "contracts"
    specs = contract_agent.generate_all(approved.services, contracts_dir)
    if target not in specs:
        raise SystemExit(f"[generate] extraction target {target!r} has no HTTP surface to extract")
    spec = specs[target]
    contract_filename = _slug(target) + ".yaml"

    # 1. service skeleton
    service_files = CodegenAgent(spec, slug).generate()
    _write_tree(GENERATED / "services" / slug, service_files)

    # 2. strangler gateway
    gateway_files = RoutingAgent(analysis, approved).generate()
    _write_tree(GENERATED / "gateway", gateway_files)

    # 3. contract tests
    test_files = ContractTestAgent(spec, slug, contract_filename).generate()
    _write_tree(GENERATED / "tests", test_files)

    table = yaml.safe_load(gateway_files["routes.yaml"])
    print(f"[generate] extraction target: {target} (slug={slug})")
    print(f"[generate] service  -> {(GENERATED / 'services' / slug).relative_to(ROOT)} "
          f"({len(spec['paths'])} routes, {len(spec.get('components', {}).get('schemas', {}))} models)")
    print(f"[generate] gateway  -> {(GENERATED / 'gateway').relative_to(ROOT)} "
          f"routes={[r['prefix'] for r in table['routes']]} -> {slug}-service, "
          f"default -> monolith")
    print(f"[generate] tests    -> {(GENERATED / 'tests').relative_to(ROOT)} "
          f"({len(ContractTestAgent(spec, slug, contract_filename)._cases())} contract cases)")
    print("[generate] strangler topology generated. Run: pytest generated/tests  |  make demo")
