#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
compose=(docker compose -f deploy/docker/compose.test.yml)
trap '"${compose[@]}" down --volumes --remove-orphans' EXIT
"${compose[@]}" build backend-tests frontend-tests playwright api worker web oidc
"${compose[@]}" run --rm backend-tests
"${compose[@]}" run --rm frontend-tests
"${compose[@]}" up -d --wait redis oidc api worker web
"${compose[@]}" run --rm playwright
