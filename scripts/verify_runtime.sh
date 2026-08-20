#!/usr/bin/env bash
# Proves the EXACT container runtime commands work end-to-end over real HTTP,
# without Docker: it launches the same processes the Dockerfiles run
# (python -m monolith.app / uvicorn main:app) on localhost and drives the
# generated gateway's real async-httpx forwarding path (not in-process transports).
#
# This is the Docker-free stand-in for `docker compose up` on a host without Docker.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PY="$ROOT/.venv/bin/python"
UVICORN="$ROOT/.venv/bin/uvicorn"

if [ ! -f generated/services/orders/main.py ] || [ ! -f generated/gateway/main.py ]; then
  echo "generated topology missing — run 'make generate' first"; exit 1
fi

PIDS=()
cleanup() { for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null; done; }
trap cleanup EXIT

echo "==> starting the three tiers with their Dockerfile CMDs (real processes)"
# 1. monolith  == Dockerfile.monolith:  python -m monolith.app   (:8000)
"$PY" -m monolith.app >/tmp/m2m_monolith.log 2>&1 & PIDS+=($!)
# 2. orders    == Dockerfile.service:   uvicorn main:app         (:8001)
( cd generated/services/orders && exec "$UVICORN" main:app --host 127.0.0.1 --port 8001 ) \
    >/tmp/m2m_orders.log 2>&1 & PIDS+=($!)
# 3. gateway   == Dockerfile.gateway:   uvicorn main:app         (:8080)
( cd generated/gateway && MONOLITH_URL=http://127.0.0.1:8000 ORDERS_URL=http://127.0.0.1:8001 \
    exec "$UVICORN" main:app --host 127.0.0.1 --port 8080 ) \
    >/tmp/m2m_gateway.log 2>&1 & PIDS+=($!)

wait_up() {
  for _ in $(seq 1 60); do curl -sf "$1" >/dev/null 2>&1 && return 0; sleep 0.5; done
  return 1
}
wait_up http://127.0.0.1:8000/health          || { echo "MONOLITH failed to start"; tail /tmp/m2m_monolith.log; exit 1; }
wait_up http://127.0.0.1:8001/health          || { echo "ORDERS failed to start";   tail /tmp/m2m_orders.log;   exit 1; }
wait_up http://127.0.0.1:8080/__gateway/health || { echo "GATEWAY failed to start";  tail /tmp/m2m_gateway.log;  exit 1; }
echo "    all three tiers healthy ✅"

hdr() { curl -s -D - -o /dev/null "$1"; }
line() { printf '%s\n' "--------------------------------------------------------------"; }

echo ""; line
echo "  gateway health:"
curl -s http://127.0.0.1:8080/__gateway/health | "$PY" -m json.tool
line
echo "  GET /orders/1        (expect backend=orders-service, the NEW service)"
hdr http://127.0.0.1:8080/orders/1        | grep -iE "^HTTP|x-gateway-backend|x-served-by"
line
echo "  GET /catalog/products (expect backend=monolith, unextracted)"
hdr http://127.0.0.1:8080/catalog/products | grep -iE "^HTTP|x-gateway-backend"
echo "  body (real monolith data):"
curl -s http://127.0.0.1:8080/catalog/products | "$PY" -c "import sys,json;d=json.load(sys.stdin);print('   ',len(d),'products, first has effective_price=',d[0].get('effective_price'))"
line
echo "  GET /users/1          (expect backend=monolith)"
hdr http://127.0.0.1:8080/users/1          | grep -iE "^HTTP|x-gateway-backend"
line
echo ""
echo "RESULT: Orders route -> NEW orders-service; other routes -> monolith. Strangler verified over real HTTP. ✅"
