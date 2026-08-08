"""Custom multi-agent orchestrator + human-in-the-loop gate.

A deliberately small, framework-free coordinator: each phase is an explicit
method that reads/writes inspectable JSON artifacts, so the whole migration is
reproducible and auditable. Run ``python -m agents.orchestrator --help``.

Phases / commands:
    analyze    Phase 1  static analysis -> context packs + dependency graph
    decompose  Phase 2  clustering + LLM refine + full evaluation harness
    contracts  Phase 2  OpenAPI 3.1 spec per proposed service
    review     Phase 2  print the HITL review payload (Streamlit is the UI)
    approve    Phase 2  non-interactive approval gate (mirrors the Streamlit write)
    generate   Phase 3  codegen service skeleton + strangler gateway + tests
    all        run analyze -> decompose -> contracts end to end
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agents.decomposition import DecompositionEngine
from agents.llm_client import LLMClient, LLMConfig
from agents.repo_analyzer import RepoAnalyzer
from core import metrics
from core.context_pack import (
    ApprovedDecomposition,
    Decomposition,
    RepoAnalysis,
    ServiceProposal,
)
from core.graph import (
    build_digraph,
    detect_communities,
    louvain_communities,
    to_undirected_weighted,
)

ROOT = Path(__file__).resolve().parent.parent
MONOLITH_DIR = ROOT / "monolith"
GENERATED = ROOT / "generated"
EVAL = ROOT / "eval"


class Paths:
    analysis = GENERATED / "analysis.json"
    context_packs = GENERATED / "context_packs.json"
    dep_graph = GENERATED / "dep_graph.json"
    decomposition = GENERATED / "decomposition.json"
    llm_trace = GENERATED / "llm_trace.jsonl"
    ground_truth = EVAL / "ground_truth.json"
    metrics_json = EVAL / "metrics.json"
    report_md = EVAL / "report.md"
    approved = EVAL / "approved_decomposition.json"


class Orchestrator:
    def __init__(self, llm_mode: str | None = None) -> None:
        cfg = LLMConfig(trace_path=Paths.llm_trace)
        if llm_mode:
            cfg.mode = llm_mode
        self.llm = LLMClient(cfg)

    # ------------------------------------------------------------------ #
    # Phase 1
    # ------------------------------------------------------------------ #
    def analyze(self) -> RepoAnalysis:
        analysis = RepoAnalyzer(MONOLITH_DIR, "monolith", self.llm).analyze()
        GENERATED.mkdir(parents=True, exist_ok=True)
        Paths.analysis.write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        Paths.context_packs.write_text(
            json.dumps([p.model_dump() for p in analysis.packs], indent=2), encoding="utf-8"
        )
        Paths.dep_graph.write_text(analysis.graph.model_dump_json(indent=2), encoding="utf-8")
        print(f"[analyze] llm_mode={self.llm.mode} model={analysis.model}")
        print(f"[analyze] modules={len(analysis.packs)} "
              f"edges={analysis.graph.edge_count()} "
              f"routes={sum(len(p.routes) for p in analysis.packs)} "
              f"entities={sum(len(p.entities) for p in analysis.packs)}")
        print(f"[analyze] wrote {Paths.context_packs.relative_to(ROOT)}, "
              f"{Paths.dep_graph.relative_to(ROOT)}")
        return analysis

    def load_analysis(self) -> RepoAnalysis:
        if not Paths.analysis.exists():
            return self.analyze()
        return RepoAnalysis.model_validate_json(Paths.analysis.read_text())

    # ------------------------------------------------------------------ #
    # Phase 2
    # ------------------------------------------------------------------ #
    def decompose(self) -> Decomposition:
        analysis = self.load_analysis()
        engine = DecompositionEngine(analysis, self.llm)
        decomposition = engine.run()
        Paths.decomposition.write_text(
            decomposition.model_dump_json(indent=2), encoding="utf-8"
        )
        print(f"[decompose] method={decomposition.method}")
        print(f"[decompose] algorithmic clusters={len(decomposition.algorithmic_clusters)} "
              f"(modularity={decomposition.algorithmic_modularity:.3f})")
        print(f"[decompose] refined services={len(decomposition.services)}:")
        for svc in decomposition.services:
            print(f"    - {svc.name:14s} [{svc.kind}] {svc.modules}")

        self._run_eval(analysis, decomposition)
        return decomposition

    def load_decomposition(self) -> Decomposition:
        if not Paths.decomposition.exists():
            return self.decompose()
        return Decomposition.model_validate_json(Paths.decomposition.read_text())

    def _run_eval(self, analysis: RepoAnalysis, decomposition: Decomposition) -> None:
        truth = json.loads(Paths.ground_truth.read_text())["assignments"]
        digraph = build_digraph(analysis.packs)
        modules = sorted(p.module for p in analysis.packs)
        undirected = to_undirected_weighted(digraph)

        partitions: dict[str, dict[str, str]] = {
            "refined": decomposition.assignment(),
            "algorithmic": {
                m: f"C{i}"
                for i, cluster in enumerate(decomposition.algorithmic_clusters)
                for m in cluster
            },
            "louvain": _communities_to_assignment(louvain_communities(undirected)),
            "greedy_raw": _communities_to_assignment(detect_communities(undirected)),
            "ground_truth": truth,
            "single_service": metrics.single_service_partition(modules),
            "per_module": metrics.per_module_partition(modules),
        }
        reports = metrics.evaluate_many(partitions, truth, digraph)
        k = len(set(truth.values()))
        random_summary = metrics.mean_random_report(modules, k, truth, digraph, trials=50)
        meta = {
            "llm_mode": self.llm.mode,
            "model": analysis.model,
            "modules": len(analysis.packs),
            "edges": analysis.graph.edge_count(),
            "method": decomposition.method,
        }
        metrics.write_metrics_json(reports, meta, Paths.metrics_json, random_summary)
        Paths.report_md.write_text(
            metrics.render_report_md(reports, meta, primary="refined",
                                     random_summary=random_summary),
            encoding="utf-8",
        )
        r = reports["refined"]
        a = reports["algorithmic"]
        print(f"[eval] REFINED     ARI={r.pair.adjusted_rand_index:.3f} "
              f"NMI={r.info.normalized_mutual_information:.3f} "
              f"macroF1={r.labelled.macro_f1:.3f} Q={r.structure.modularity:.3f}")
        print(f"[eval] algorithmic ARI={a.pair.adjusted_rand_index:.3f} "
              f"(semantic lift Δ={r.pair.adjusted_rand_index - a.pair.adjusted_rand_index:+.3f})")
        print(f"[eval] wrote {Paths.metrics_json.relative_to(ROOT)}, "
              f"{Paths.report_md.relative_to(ROOT)}")

    # ------------------------------------------------------------------ #
    # HITL gate
    # ------------------------------------------------------------------ #
    def review_payload(self) -> dict:
        decomposition = self.load_decomposition()
        return {
            "services": [s.model_dump() for s in decomposition.services],
            "algorithmic_clusters": decomposition.algorithmic_clusters,
            "method": decomposition.method,
        }

    def approve(self, approver: str = "cli") -> ApprovedDecomposition:
        """Non-interactive approval — persists the Phase-3 gate file.
        (The Streamlit app writes the same file after human edits.)"""
        decomposition = self.load_decomposition()
        gt = json.loads(Paths.ground_truth.read_text())
        approved = ApprovedDecomposition(
            approved=True,
            approved_by=approver,
            services=decomposition.services,
            extraction_target=gt.get("extraction_target", "Orders"),
            notes="Auto-approved via CLI (non-interactive path).",
        )
        EVAL.mkdir(parents=True, exist_ok=True)
        Paths.approved.write_text(approved.model_dump_json(indent=2), encoding="utf-8")
        print(f"[approve] extraction_target={approved.extraction_target}")
        print(f"[approve] wrote {Paths.approved.relative_to(ROOT)} (Phase-3 gate OPEN)")
        return approved


def _communities_to_assignment(communities: list[list[str]]) -> dict[str, str]:
    return {m: f"K{i}" for i, c in enumerate(communities) for m in c}


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator", description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command",
                        choices=["analyze", "decompose", "contracts", "review",
                                 "approve", "generate", "all"])
    parser.add_argument("--llm-mode", choices=["mock", "real"], default=None,
                        help="override LLM_MODE env var")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    orch = Orchestrator(llm_mode=args.llm_mode)

    if args.command == "analyze":
        orch.analyze()
    elif args.command == "decompose":
        orch.decompose()
    elif args.command == "review":
        print(json.dumps(orch.review_payload(), indent=2))
    elif args.command == "approve":
        orch.approve()
    elif args.command in {"contracts", "generate", "all"}:
        # wired up once the Phase-2 contract agent / Phase-3 codegen agents land
        from agents import pipeline

        pipeline.dispatch(orch, args.command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
