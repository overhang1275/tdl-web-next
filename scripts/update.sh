#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/native-common.sh"
[[ -f "$ENV_FILE" ]] || { echo 'Ejecuta primero scripts/install.sh.' >&2; exit 1; }
[[ -L "$APP_ROOT/current" && -x "$APP_ROOT/node/bin/node" ]] || { echo 'Migra primero con scripts/install.sh para crear los servicios Next.js y FastAPI.' >&2; exit 1; }
# Run from the updated source checkout; previous releases and their venvs stay intact.
build_release
activate_release
echo 'Actualización nativa terminada; las descargas y la sesión se conservaron.'
