#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
compose=(docker compose --env-file "${ENV_FILE:-$ROOT/.env}" -f deploy/docker/compose.yml)
"${compose[@]}" exec -T authentik-worker ak apply_blueprint /blueprints/custom/tdl-console.yaml
"${compose[@]}" exec -T authentik-worker ak shell -c '
from authentik.core.models import Group, User
group = Group.objects.get(name="tdl-admin")
User.objects.get(username="akadmin").ak_groups.add(group)
print("TDL Console OIDC configured; akadmin belongs to tdl-admin")
'
