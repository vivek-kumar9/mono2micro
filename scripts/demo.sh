#!/usr/bin/env bash
# Strangler-fig demo. Ensures the pipeline has run through Phase 3 (non-interactive
# approval), then brings up the topology with Docker if available, otherwise runs
# the equivalent in-process demo.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="$([ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)"

echo "==> Phase 1-3 (mock LLM, non-interactive approval)"
$PY -m agents.orchestrator analyze
$PY -m agents.orchestrator decompose
$PY -m agents.orchestrator approve
$PY -m agents.orchestrator generate

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  echo ""
  echo "==> Docker detected — bringing up monolith + orders-service + gateway"
  docker compose -f docker/docker-compose.yml up --build -d
  echo "    waiting for the gateway to become healthy..."
  for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/__gateway/health >/dev/null 2>&1; then break; fi
    sleep 2
  done
  echo ""
  echo "==> Strangler routing through the gateway (http://localhost:8080)"
  echo "--- Orders route -> NEW orders-service ---"
  curl -s -D - http://localhost:8080/orders/1 -o /dev/null | grep -i "x-gateway-backend\|x-served-by\|HTTP/" || true
  echo "--- Catalog route -> monolith (unextracted) ---"
  curl -s -D - http://localhost:8080/catalog/products -o /dev/null | grep -i "x-gateway-backend\|HTTP/" || true
  echo ""
  echo "Bring it down with:  docker compose -f docker/docker-compose.yml down"
else
  echo ""
  echo "==> Docker not available — proving the exact container CMDs over real HTTP instead"
  echo "    (this runs the same processes the Dockerfiles run, on localhost)"
  if ! ./scripts/verify_runtime.sh; then
    echo ""
    echo "==> real-process check unavailable — falling back to the in-process demo"
    $PY scripts/local_demo.py
  fi
fi
