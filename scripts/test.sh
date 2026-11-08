#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
run_id="$(cat /proc/sys/kernel/random/uuid)"
export TDL_TEST_IMAGE_PREFIX="tdl-check-$run_id"
projects=()
cleanup() {
  for project in "${projects[@]}"; do
    docker compose -p "$project" -f deploy/docker/compose.test.yml down --volumes --remove-orphans
  done
}
trap cleanup EXIT
export RQ_QUEUE_NAME="tdl-$run_id-downloads" AUTHENTIK_ENABLED=false
compose=(docker compose -p "tdl-check-$run_id-local" -f deploy/docker/compose.test.yml)
projects+=("tdl-check-$run_id-local")
"${compose[@]}" build backend-tests frontend-tests playwright web
"${compose[@]}" run --rm backend-tests
"${compose[@]}" run --rm frontend-tests
"${compose[@]}" up -d --no-build --wait postgres redis migrate bootstrap api worker web auth-control
"${compose[@]}" run --rm playwright
export AUTHENTIK_ENABLED=true
export RQ_QUEUE_NAME="tdl-$(cat /proc/sys/kernel/random/uuid)-downloads"
projects+=("tdl-check-$run_id-oidc")
compose=(docker compose -p "tdl-check-$run_id-oidc" -f deploy/docker/compose.test.yml)
"${compose[@]}" up -d --no-build --wait postgres redis oidc migrate bootstrap api worker web auth-control
"${compose[@]}" run --rm playwright
