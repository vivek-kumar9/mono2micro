"""Streamlit human-in-the-loop review app.

Run with:  streamlit run review_ui/app.py   (or `make review`)

Shows the proposed service boundaries, the dependency graph coloured by service,
and the evaluation metrics. The reviewer can reassign modules, rename services,
pick the extraction target, and APPROVE — which writes
``eval/approved_decomposition.json`` and unlocks Phase 3.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from core.context_pack import Decomposition, GraphArtifact, RepoAnalysis  # noqa: E402
from review_ui import review_logic as rl  # noqa: E402

GENERATED = ROOT / "generated"
EVAL = ROOT / "eval"


def _load():
    decomposition = Decomposition.model_validate_json((GENERATED / "decomposition.json").read_text())
    analysis = RepoAnalysis.model_validate_json((GENERATED / "analysis.json").read_text())
    metrics = json.loads((EVAL / "metrics.json").read_text())
    ground_truth = json.loads((EVAL / "ground_truth.json").read_text())
    return decomposition, analysis, metrics, ground_truth


def main() -> None:
    st.set_page_config(page_title="mono2micro — HITL review", layout="wide")
    st.title("🧩 mono2micro — Decomposition Review (Human-in-the-Loop)")

    if not (GENERATED / "decomposition.json").exists():
        st.error("No decomposition found. Run `make analyze decompose` first.")
        st.stop()

    decomposition, analysis, metrics, ground_truth = _load()
    refined = metrics["partitions"]["refined"]

    # --- metrics header ---
    st.subheader("Evaluation of the proposed decomposition")
    ca = refined["clustering_agreement"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Adjusted Rand Index", f"{ca['adjusted_rand_index']:.3f}")
    c2.metric("Macro F1", f"{refined['labelled_summary']['macro_f1']:.3f}")
    c3.metric("V-measure", f"{ca['v_measure']:.3f}")
    c4.metric("Cut ratio", f"{refined['structure']['cut_ratio']:.3f}")

    # --- editable assignment ---
    st.subheader("Proposed service boundaries — edit as needed")
    if "mapping" not in st.session_state:
        st.session_state.mapping = rl.initial_mapping(decomposition)
    mapping = st.session_state.mapping

    pack_by_module = {p.module: p for p in analysis.packs}
    service_names = sorted(set(mapping.values()))
    extra = st.text_input("Add a new service name (optional)", "")
    options = service_names + ([extra] if extra else [])

    left, right = st.columns([2, 3])
    with left:
        st.markdown("**Reassign modules**")
        for module in sorted(mapping):
            current = mapping[module]
            resp = pack_by_module[module].responsibility if module in pack_by_module else ""
            choice = st.selectbox(
                f"`{module}` — {resp[:60]}",
                options,
                index=options.index(current) if current in options else 0,
                key=f"sel_{module}",
            )
            mapping[module] = choice

    services = rl.apply_reassignments(decomposition.services, mapping)

    with right:
        st.markdown("**Dependency graph (coloured by proposed service)**")
        target = st.selectbox(
            "Extraction target (first service to strangle out)",
            sorted({s.name for s in services if s.kind == "microservice"}),
            index=0,
        )
        dot = rl.graph_to_dot(analysis.graph, mapping, extraction_target=target)
        st.graphviz_chart(dot, use_container_width=True)

    st.subheader("Resulting services")
    for svc in services:
        st.write(f"- **{svc.name}** [{svc.kind}] — `{', '.join(svc.modules)}`")

    # --- approval gate ---
    st.subheader("Approval gate (Phase 3 is blocked until you approve)")
    approver = st.text_input("Your name / handle", "reviewer")
    notes = st.text_area("Notes (optional)", "")
    if st.button("✅ APPROVE this decomposition", type="primary"):
        approved = rl.build_approved(services, target, approver, notes)
        rl.save_approved(approved, EVAL / "approved_decomposition.json")
        st.success(
            f"Approved. Wrote eval/approved_decomposition.json (target = {target}). "
            "You can now run `make generate` and `make demo`."
        )
        st.json(json.loads(approved.model_dump_json()))


if __name__ == "__main__":
    main()
else:
    # `streamlit run` executes the module as __main__; when imported for tests we
    # deliberately do nothing so importing this file has no side effects.
    pass
