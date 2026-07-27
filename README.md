# mono2micro — AI-Driven Monolith → Microservice Migration Assistant

A multi-agent system that migrates a monolith to microservices with a
**human-in-the-loop** review gate. It statically analyses a codebase, proposes
service boundaries by combining **graph community detection** with **LLM domain
reasoning**, **quantitatively scores** the proposal against a ground-truth
partition, gates the result behind a review step, and then generates a runnable
**strangler-fig** topology (extracted FastAPI service + gateway + contract tests
+ Docker).

Everything is designed to run **offline** with a deterministic **mock LLM** (no
API key) and identically with a real Anthropic key. There is **no LangChain /
LlamaIndex / CrewAI / AutoGen** — a small custom orchestrator keeps every step
inspectable.

> Built as a Data-Science / ML portfolio project: the emphasis is on
> **algorithmic depth** (a from-scratch clustering-evaluation harness) and
> **quantitative rigour** (a calibrated metric battery), not just a working demo.

---

## Status

Early scaffolding. See [`PLAN.md`](PLAN.md) for the architecture, the key design
decisions, and the phased task list.

| Phase | Scope |
|---|---|
| 0 | Synthetic Flask monolith + ground-truth labels |
| 1 | Repo analysis → context packs + dependency graph |
| 2 | Decomposition + evaluation harness + OpenAPI contracts + HITL review |
| 3 | Strangler-fig codegen: FastAPI service, gateway, contract tests, Docker |

## Requirements

Python 3.11+. Install with `pip install -r requirements.txt`.

Copy `.env.example` to `.env` to configure the LLM backend. The default
(`LLM_MODE=mock`) requires no credentials.
