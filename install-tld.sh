#!/usr/bin/env bash
# Native LXC entry point: install, update or repair the application.
set -euo pipefail

SCRIPT_DIR=''
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi
WORK=''
DEFAULT_KEYS=(APP_ROOT APP_PORT API_PORT APP_USER CREATE_USER INSTALL_REDIS APP_REF
              INSTALL_METHOD SOURCE_REPO PUBLIC_URL AUTH_URL SAVE_DEFAULTS SERVICE_WEB
              SERVICE_API SERVICE_WORKER)

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

env_read() {
    local file=$1 wanted=$2 key value
    [[ -f "$file" ]] || return 0
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
        [[ "$key" == "$wanted" ]] || continue
        value="${value%$'\r'}"
        if [[ "$value" == \"*\" || "$value" == \'*\' ]]; then value="${value:1:${#value}-2}"; fi
        printf '%s' "$value"
        return
    done < "$file"
}

pick_value() {
    local name=$1 fallback=$2 value
    if [[ -v "$name" ]]; then printf '%s' "${!name}"; return; fi
    value="$(env_read "$ENV_FILE" "$name")"
    [[ -n "$value" ]] || value="$(env_read "$INSTALL_CONF" "$name")"
    printf '%s' "${value:-$fallback}"
}

init_input() {
    INPUT_FD=0
    if [[ -t 0 ]]; then
        exec {INPUT_FD}<&0
    elif { exec {INPUT_FD}</dev/tty; } 2>/dev/null; then
        :
    else
        INPUT_FD=0
    fi
}

can_prompt() { [[ -t "${INPUT_FD:-0}" && "${ASSUME_YES:-0}" != 1 ]]; }

prompt_default() {
    local label=$1 default=$2 value=''
    if can_prompt; then
        read -r -u "${INPUT_FD:-0}" -p "$label [$default]: " value || true
    fi
    printf '%s' "${value:-$default}"
}

yes_no() {
    case "${1,,}" in s|si|sí|y|yes|1|true) printf 1 ;; n|no|0|false) printf 0 ;; *) die 'Responde S o n.' ;; esac
}

discover_files() {
    CONFIG_DIR="${CONFIG_DIR:-/etc/tld-web}"
    INSTALL_CONF="${INSTALL_CONF:-$CONFIG_DIR/install.conf}"
    SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
    if [[ ! -v ENV_FILE ]]; then
        ENV_FILE="$CONFIG_DIR/tld-web.env"
        if [[ ! -f "$ENV_FILE" && "$CONFIG_DIR" == /etc/tld-web && -f /etc/telegram-downloader/telegram-downloader.env ]]; then
            ENV_FILE=/etc/telegram-downloader/telegram-downloader.env
        fi
    fi
}

collect_options() {
    discover_files
    local legacy=0 old_root old_port=8080
    [[ -f "$SYSTEMD_DIR/telegram-downloader-web.service" ]] && legacy=1
    old_root="$(env_read "$ENV_FILE" APP_ROOT)"
    if [[ -z "$old_root" && "$legacy" == 1 ]]; then
        old_root="$(sed -n 's|^WorkingDirectory=\(.*\)/current/.*|\1|p' "$SYSTEMD_DIR/telegram-downloader-web.service" | head -1)"
        old_port="$(sed -n 's/.* PORT=\([0-9]*\).*/\1/p' "$SYSTEMD_DIR/telegram-downloader-web.service" | head -1)"
        old_port="${old_port:-3000}"
    fi
    APP_ROOT="$(prompt_default 'Ruta de instalación' "$(pick_value APP_ROOT "${old_root:-/opt/tld-web}")")"
    [[ -z "$old_root" || "$old_root" == "$APP_ROOT" ]] || die 'Cambiar APP_ROOT de una instalación existente requiere migración manual.'
    APP_REF="$(prompt_default 'Versión, tag o commit' "$(pick_value APP_REF latest)")"
    INSTALL_METHOD="$(prompt_default 'Método (auto/release/source)' "$(pick_value INSTALL_METHOD auto)")"
    SOURCE_REPO="$(pick_value SOURCE_REPO https://github.com/overhang1275/tdl-web-next.git)"
    SOURCE_DIR="${SOURCE_DIR:-}"
    APP_HOST="$(pick_value APP_HOST 127.0.0.1)"
    APP_PORT="$(prompt_default 'Puerto web local' "$(pick_value APP_PORT "$old_port")")"
    local api_default
    api_default="$(env_read "$ENV_FILE" API_INTERNAL_URL)"
    API_PORT="$(pick_value API_PORT "${api_default##*:}")"
    API_PORT="${API_PORT:-8000}"
    INSTALL_REDIS="$(yes_no "$(prompt_default '¿Instalar Redis localmente? S/n' "$(pick_value INSTALL_REDIS S)")")"
    REDIS_URL="$(pick_value REDIS_URL redis://127.0.0.1:6379/0)"
    if [[ "$INSTALL_REDIS" == 0 ]] && can_prompt; then
        local redis_input=''
        read -r -s -u "${INPUT_FD:-0}" -p 'URL de Redis externo (Enter conserva el valor actual): ' redis_input || true
        printf '\n' >&2
        REDIS_URL="${redis_input:-$REDIS_URL}"
    fi
    CREATE_USER="$(yes_no "$(prompt_default '¿Crear usuario de servicio dedicado? S/n' "$(pick_value CREATE_USER S)")")"
    local default_user=tld-web
    [[ "$legacy" == 0 ]] || default_user="$(sed -n 's/^User=//p' "$SYSTEMD_DIR/telegram-downloader-web.service" | head -1)"
    default_user="${default_user:-telegramdl}"
    APP_USER="$(prompt_default 'Usuario del servicio' "$(pick_value APP_USER "$default_user")")"
    PUBLIC_URL="$(prompt_default 'URL del túnel (solo referencia; vacío para desactivar)' "$(pick_value PUBLIC_URL '')")"
    PUBLIC_URL="${PUBLIC_URL%/}"
    AUTH_URL="$(prompt_default 'URL canónica de acceso OIDC' "$(pick_value AUTH_URL "http://localhost:$APP_PORT")")"
    AUTH_URL="${AUTH_URL%/}"
    SAVE_DEFAULTS="$(yes_no "$(prompt_default '¿Guardar estas opciones como defaults? S/n' "$(pick_value SAVE_DEFAULTS S)")")"
    local web=tld-web api=tld-web-api worker=tld-web-worker
    if [[ "$legacy" == 1 ]]; then web=telegram-downloader-web; api=telegram-downloader-api; worker=telegram-downloader-worker; fi
    SERVICE_WEB="$(pick_value SERVICE_WEB "$web")"
    SERVICE_API="$(pick_value SERVICE_API "$api")"
    SERVICE_WORKER="$(pick_value SERVICE_WORKER "$worker")"
    SERVICES=("$SERVICE_API" "$SERVICE_WORKER" "$SERVICE_WEB")
    BACKUPS_DIR="$APP_ROOT/backups"
    export APP_ROOT APP_HOST APP_PORT API_PORT APP_USER INSTALL_REDIS CREATE_USER PUBLIC_URL
    export AUTH_URL APP_REF INSTALL_METHOD SOURCE_REPO SERVICE_WEB SERVICE_API SERVICE_WORKER BACKUPS_DIR REDIS_URL
}

valid_path() { [[ "$1" =~ ^/[A-Za-z0-9_./-]+$ && "$1" != / && "$1" != *'/../'* && "$1" != */.. && "$1" != *'/./'* ]]; }

validate_options() {
    valid_path "$APP_ROOT" && valid_path "$CONFIG_DIR" && valid_path "$ENV_FILE" && valid_path "$SYSTEMD_DIR" || die 'Usa rutas absolutas sin espacios ni segmentos . o ...'
    [[ "$APP_ROOT" != /etc && "$APP_ROOT" != /usr && "$APP_ROOT" != /var && "$APP_ROOT" != /home && "$APP_ROOT" != /opt ]] || die 'Elige una carpeta exclusiva para la aplicación.'
    [[ "$APP_HOST" == 127.0.0.1 ]] || die 'APP_HOST debe ser 127.0.0.1.'
    local port service
    for port in "$APP_PORT" "$API_PORT"; do
        [[ "$port" =~ ^[0-9]{1,5}$ ]] && ((10#$port > 0 && 10#$port <= 65535)) || die 'Puerto inválido (1–65535).'
    done
    APP_PORT=$((10#$APP_PORT)); API_PORT=$((10#$API_PORT))
    [[ "$APP_PORT" != "$API_PORT" ]] || die 'Los puertos de web y API deben ser distintos.'
    [[ "$APP_USER" =~ ^[a-z_][a-z0-9_-]*$ && "$APP_USER" != root ]] || die 'El servicio requiere un usuario válido distinto de root.'
    [[ "$APP_REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && "$APP_REF" != *..* ]] || die 'Versión/ref inválida.'
    [[ "$INSTALL_METHOD" == auto || "$INSTALL_METHOD" == source || "$INSTALL_METHOD" == release ]] || die 'Método inválido.'
    [[ "$SOURCE_REPO" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?$ || "$SOURCE_REPO" =~ ^git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?$ ]] || die 'Usa una URL GitHub HTTPS sin credenciales o SSH.'
    [[ -z "$PUBLIC_URL" || "$PUBLIC_URL" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ ]] || die 'PUBLIC_URL debe ser un origen HTTPS, sin ruta ni credenciales.'
    [[ "$AUTH_URL" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?$ || "$AUTH_URL" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?$ ]] || die 'AUTH_URL debe ser HTTPS o HTTP local.'
    [[ "$REDIS_URL" =~ ^rediss?://[^[:space:]]+$ ]] || die 'REDIS_URL inválida.'
    for service in "${SERVICES[@]}"; do [[ "$service" =~ ^[a-zA-Z0-9_.@-]+$ ]] || die 'Nombre de servicio inválido.'; done
    local directory
    for directory in "$APP_ROOT" "$CONFIG_DIR" "$SYSTEMD_DIR"; do
        while [[ "$directory" != / ]]; do
            [[ ! -L "$directory" ]] || die 'Las rutas de instalación no pueden contener enlaces simbólicos.'
            directory="${directory%/*}"; directory="${directory:-/}"
        done
    done
}

print_summary() {
    printf '%s\n' "APP_ROOT=$APP_ROOT" "APP_HOST=$APP_HOST" "APP_PORT=$APP_PORT" "API_PORT=$API_PORT" \
        "APP_USER=$APP_USER" "APP_REF=$APP_REF" "INSTALL_METHOD=$INSTALL_METHOD" \
        "INSTALL_REDIS=$INSTALL_REDIS" "PUBLIC_URL=$PUBLIC_URL" "AUTH_URL=$AUTH_URL" "ENV_FILE=$ENV_FILE"
}

options_json() {
    export CONFIG_DIR NODE_BINARY="${NODE_BINARY:-}" RESOLVED_VERSION="${RESOLVED_VERSION:-local}" RESOLVED_METHOD="${RESOLVED_METHOD:-source}"
    python3 -c 'import json,os; names="APP_ROOT APP_HOST APP_PORT API_PORT APP_USER INSTALL_REDIS PUBLIC_URL AUTH_URL REDIS_URL CONFIG_DIR BACKUPS_DIR SERVICE_WEB SERVICE_API SERVICE_WORKER NODE_BINARY RESOLVED_VERSION RESOLVED_METHOD".split(); result={k:os.environ.get(k, "") for k in names}; result.update({"TDL_BINARY":os.environ["TDL_BINARY"]} if os.environ.get("TDL_BINARY") else {}); print(json.dumps(result))'
}

write_defaults() {
    local destination=$1 temporary name
    mkdir -p -- "$(dirname -- "$destination")"
    temporary="$(mktemp "$(dirname -- "$destination")/.install.conf.XXXXXX")"
    for name in "${DEFAULT_KEYS[@]}"; do printf '%s=%s\n' "$name" "${!name}" >> "$temporary"; done
    chmod 640 "$temporary"
    mv -f -- "$temporary" "$destination"
}

write_environment() {
    local destination=$1 options
    options="$(mktemp)"
    options_json > "$options"
    python3 "${SOURCE_DIR:-$SCRIPT_DIR}/scripts/configure-env.py" --deployment native --domain localhost \
        --root "$APP_ROOT" --output "$destination" --legacy "$ENV_FILE" --native-options "$options"
    rm -f -- "$options"
}

prepare_environment() {
    if [[ ! -e "$APP_ROOT/current" ]]; then NEW_ENV=1; fi
    [[ ! -f "$ENV_FILE" ]] || return 0
    mkdir -p -- "$(dirname "$ENV_FILE")"
    write_environment "$ENV_FILE"
    chgrp "$APP_GROUP" "$ENV_FILE"
    chmod 640 "$ENV_FILE"
    if [[ "$SAVE_DEFAULTS" == 1 ]]; then write_defaults "$INSTALL_CONF"; fi
    link_layout_aliases
    printf 'Configuración básica creada en %s (acceso: %s/.env).\n' "$ENV_FILE" "$APP_ROOT"
    NEW_ENV=1
}

check_port() {
    python3 - "$1" <<'PY'
import socket, sys
try:
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', int(sys.argv[1])))
except OSError:
    raise SystemExit(f'El puerto {sys.argv[1]} está ocupado o no se puede utilizar.')
PY
}

extract_release() {
    python3 - "$1" "$2" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1]) as archive:
    archive.extractall(sys.argv[2], filter='data')
PY
}

render_units() {
    local directory=$1
    mkdir -p -- "$directory"
    cat > "$directory/$SERVICE_WEB.service" <<EOF
# Managed by install-tld.sh: $APP_ROOT
[Unit]
Description=TLD Web frontend
After=network-online.target $SERVICE_API.service
Wants=network-online.target $SERVICE_API.service
[Service]
User=$APP_USER
Group=${APP_GROUP:-$APP_USER}
WorkingDirectory=$APP_ROOT/current/frontend/.next/standalone
EnvironmentFile=$ENV_FILE
Environment=NODE_ENV=production HOSTNAME=127.0.0.1 PORT=$APP_PORT
ExecStart=$NODE_BINARY $APP_ROOT/current/frontend/.next/standalone/server.js
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
    cat > "$directory/$SERVICE_API.service" <<EOF
# Managed by install-tld.sh: $APP_ROOT
[Unit]
Description=TLD Web API
After=network-online.target
Wants=network-online.target
[Service]
User=$APP_USER
Group=${APP_GROUP:-$APP_USER}
WorkingDirectory=$APP_ROOT/current/backend
EnvironmentFile=$ENV_FILE
ExecStart=$APP_ROOT/current/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $API_PORT --workers 1
ExecStartPost=/usr/bin/curl --fail --silent --retry 15 --retry-delay 1 --retry-connrefused http://127.0.0.1:$API_PORT/health
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
    sed "s/Description=TLD Web API/Description=TLD Web worker/;s|^ExecStart=.*|ExecStart=$APP_ROOT/current/venv/bin/python -m app.rq_worker|;/^ExecStartPost=/d;s/^After=network-online.target$/After=network-online.target $SERVICE_API.service/" \
        "$directory/$SERVICE_API.service" > "$directory/$SERVICE_WORKER.service"
}

configure_redis() {
    [[ "$INSTALL_REDIS" == 1 ]] || return 0
    local config="${REDIS_CONFIG:-/etc/redis/redis.conf}"
    [[ -f "$config" ]] || die 'No se encontró la configuración de Redis local.'
    python3 - "$config" <<'PY'
import re,sys
from pathlib import Path
path=Path(sys.argv[1]); content=path.read_text()
for key,value in [('bind','127.0.0.1'),('protected-mode','yes')]:
    line=f'{key} {value}'
    content=re.sub(rf'(?m)^{key}\s+.*$',line,content) if re.search(rf'(?m)^{key}\s+',content) else content+'\n'+line+'\n'
path.write_text(content)
PY
    systemctl enable redis-server
    systemctl restart redis-server
}

preflight() {
    [[ -d /run/systemd/system ]] || die 'Se requiere systemd dentro del LXC.'
    # This is a trusted operating-system file, never installer input.
    local ID VERSION_ID
    source /etc/os-release
    case "$ID:$VERSION_ID" in debian:13*|ubuntu:24.*|ubuntu:26.*) ;; *) die 'Se requiere Debian 13 o Ubuntu 24.04/26.04.' ;; esac
    if command -v python3 >/dev/null; then python3 -c 'import sys; assert sys.version_info >= (3,12), "Se requiere Python 3.12+"'; fi
    case "$(uname -m)" in x86_64) NODE_ARCH=x64; TDL_ARCH=64bit ;; aarch64) NODE_ARCH=arm64; TDL_ARCH=arm64 ;; *) die 'Arquitectura no compatible.' ;; esac
    for tool in systemctl curl git rsync runuser; do command -v "$tool" >/dev/null || {
        [[ "$ACTION" != repair && "$ACTION" != configure ]] || die "Falta $tool; repara las dependencias del sistema primero."
    }; done
}

prepare_layout() {
    # Never adopt an application-writable root as trusted rollback storage.
    python3 - "$APP_ROOT" "$CONFIG_DIR" "$SYSTEMD_DIR" "$(dirname "$ENV_FILE")" <<'PY'
import os, sys
from pathlib import Path
for raw in sys.argv[1:]:
    path = Path(raw)
    for item in (path, *path.parents):
        if item.exists() and (item.stat().st_uid != 0 or item.stat().st_mode & 0o022):
            # /tmp is acceptable only as a sticky ancestor, never as the target.
            if item != path and item.stat().st_mode & 0o1000:
                continue
            raise SystemExit(f'Ruta no confiable para instalación root: {item}; corrige propietario/permisos primero.')
PY
    install -d -m 755 "$APP_ROOT" "$APP_ROOT/releases" "$APP_ROOT/tools"
    install -d -m 700 "$BACKUPS_DIR" "$CONFIG_DIR"
    WORK="$(mktemp -d "$APP_ROOT/.install.XXXXXXXX")"
    trap '[[ -z "$WORK" ]] || rm -rf -- "$WORK"' EXIT
    if ! id "$APP_USER" >/dev/null 2>&1; then
        [[ "$CREATE_USER" == 1 ]] || die 'El usuario seleccionado no existe.'
        useradd --system --user-group --home-dir "$APP_ROOT/data" --no-create-home --shell /usr/sbin/nologin "$APP_USER"
    fi
    [[ "$(id -u "$APP_USER")" != 0 ]] || die 'El usuario del servicio no puede tener UID 0.'
    APP_GROUP="$(id -gn "$APP_USER")"
    chgrp "$APP_GROUP" "$CONFIG_DIR" "$(dirname "$ENV_FILE")"
    chmod 750 "$CONFIG_DIR" "$(dirname "$ENV_FILE")"
    export APP_GROUP
}

owned_service() {
    local unit="$SYSTEMD_DIR/$1.service"
    [[ -f "$unit" ]] && { grep -Fxq "# Managed by install-tld.sh: $APP_ROOT" "$unit" ||
        grep -Fq "WorkingDirectory=$APP_ROOT/current/" "$unit"; }
}

check_service_ports() {
    local unit port pair
    for pair in "$SERVICE_WEB:$APP_PORT" "$SERVICE_API:$API_PORT"; do
        unit=${pair%:*}; port=${pair##*:}
        if [[ -f "$SYSTEMD_DIR/$unit.service" ]] && ! owned_service "$unit"; then die "La unidad $unit pertenece a otra instalación."; fi
        if owned_service "$unit" && systemctl is-active --quiet "$unit"; then
            # A changed port is not covered by the existing service.
            if grep -Eq "(PORT=|--port )$port([[:space:]]|$)" "$SYSTEMD_DIR/$unit.service"; then continue; fi
        fi
        check_port "$port"
    done
    [[ ! -f "$SYSTEMD_DIR/$SERVICE_WORKER.service" ]] || owned_service "$SERVICE_WORKER" || die 'La unidad worker pertenece a otra instalación.'
}

fetch() { curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$1" -o "$2"; }

fetch_asset() {
    [[ "$1" =~ ^https://api\.github\.com/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/assets/[0-9]+$ ]] || die 'URL de asset GitHub inválida.'
    local -a auth=()
    [[ -z "${GH_TOKEN:-}" ]] || auth=(-H "Authorization: Bearer $GH_TOKEN")
    curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
        "${auth[@]}" -H 'Accept: application/octet-stream' "$1" -o "$2"
}

verify_checksum() {
    python3 - "$1" "$2" <<'PY'
import hashlib, sys
from pathlib import Path
artifact, manifest = map(Path, sys.argv[1:])
matches = [line.split()[0] for line in manifest.read_text().splitlines()
           if len(line.split()) == 2 and line.split()[1].lstrip('*') == artifact.name]
if len(matches) != 1 or hashlib.file_digest(artifact.open('rb'), 'sha256').hexdigest() != matches[0]:
    raise SystemExit(f'Checksum inválido o ausente: {artifact.name}')
PY
}

install_binaries() {
    local node_version="${NODE_VERSION:-24.19.0}" tdl_version="${TDL_VERSION:-0.20.4}" archive destination
    [[ "$node_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$tdl_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Versión de binario inválida.'
    destination="$APP_ROOT/tools/node-$node_version-$NODE_ARCH"
    if [[ ! -x "$destination/bin/node" ]]; then
        archive="node-v$node_version-linux-$NODE_ARCH.tar.xz"
        fetch "https://nodejs.org/dist/v$node_version/$archive" "$WORK/$archive"
        fetch "https://nodejs.org/dist/v$node_version/SHASUMS256.txt" "$WORK/node-checksums"
        verify_checksum "$WORK/$archive" "$WORK/node-checksums"
        mkdir "$WORK/node"; extract_release "$WORK/$archive" "$WORK/node"
        mv "$WORK/node/node-v$node_version-linux-$NODE_ARCH" "$destination"
    fi
    NODE_BINARY="$destination/bin/node"
    TDL_BINARY="$(env_read "$ENV_FILE" TDL_BINARY)"
    if [[ ! -x "$TDL_BINARY" ]]; then
        destination="$APP_ROOT/tools/tdl-$tdl_version-$TDL_ARCH"
        if [[ ! -x "$destination/tdl" ]]; then
            archive="tdl_Linux_$TDL_ARCH.tar.gz"
            fetch "https://github.com/iyear/tdl/releases/download/v$tdl_version/$archive" "$WORK/$archive"
            fetch "https://github.com/iyear/tdl/releases/download/v$tdl_version/tdl_checksums.txt" "$WORK/tdl-checksums"
            verify_checksum "$WORK/$archive" "$WORK/tdl-checksums"
            mkdir "$WORK/tdl"; extract_release "$WORK/$archive" "$WORK/tdl"
            [[ -f "$WORK/tdl/tdl" && ! -L "$WORK/tdl/tdl" ]] || die 'El archivo tdl no contiene el binario esperado.'
            chmod 755 "$WORK/tdl/tdl"; mv "$WORK/tdl" "$destination"
        fi
        TDL_BINARY="$destination/tdl"
    fi
    "$NODE_BINARY" --version
    "$TDL_BINARY" version
    export NODE_BINARY TDL_BINARY
}

resolve_source() {
    RESOLVED_METHOD=source
    if [[ -n "$SOURCE_DIR" ]]; then
        SOURCE_DIR="$(realpath "$SOURCE_DIR")"
        RESOLVED_VERSION="$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || printf local)"
    else
        local repo metadata status tag_path
        repo="${SOURCE_REPO#https://github.com/}"; repo="${repo#git@github.com:}"; repo="${repo%.git}"
        tag_path="tags/$APP_REF"; [[ "$APP_REF" != latest ]] || tag_path=latest
        metadata="$WORK/release.json"
        if [[ "$INSTALL_METHOD" != source ]]; then
            local -a auth=()
            [[ -z "${GH_TOKEN:-}" ]] || auth=(-H "Authorization: Bearer $GH_TOKEN")
            status="$(curl --silent --show-error --location "${auth[@]}" -w '%{http_code}' -o "$metadata" "https://api.github.com/repos/$repo/releases/$tag_path")"
            if [[ "$status" == 200 ]]; then
                python3 - "$metadata" "$NODE_ARCH" > "$WORK/assets" <<'PY'
import json, sys
release=json.load(open(sys.argv[1])); assets={a['name']:a['url'] for a in release.get('assets',[])}
name=f'tld-web-linux-{sys.argv[2]}.tar.gz'
if name in assets and 'SHA256SUMS' in assets:
    print(release['tag_name']); print(assets[name]); print(assets['SHA256SUMS'])
PY
                if [[ -s "$WORK/assets" ]]; then
                    local -a assets
                    mapfile -t assets < "$WORK/assets"
                    RESOLVED_VERSION=${assets[0]}; RESOLVED_METHOD=release
                    local archive="tld-web-linux-$NODE_ARCH.tar.gz"
                    fetch_asset "${assets[1]}" "$WORK/$archive"; fetch_asset "${assets[2]}" "$WORK/SHA256SUMS"
                    verify_checksum "$WORK/$archive" "$WORK/SHA256SUMS"
                    mkdir "$WORK/source"; extract_release "$WORK/$archive" "$WORK/source"
                    SOURCE_DIR="$WORK/source"
                fi
            elif [[ "$status" != 404 ]]; then
                die "No se pudo consultar GitHub Releases (HTTP $status); revisa conexión/permisos."
            fi
            [[ "$RESOLVED_METHOD" == release || "$INSTALL_METHOD" != release ]] || die 'No existe un bundle compatible con SHA256SUMS para esa versión.'
        fi
        if [[ -z "$SOURCE_DIR" ]]; then
            git clone --no-checkout -- "$SOURCE_REPO" "$WORK/source"
            local ref="$APP_REF"
            [[ "$ref" != latest ]] || ref=origin/HEAD
            git -C "$WORK/source" checkout --detach "$ref" --
            SOURCE_DIR="$WORK/source"
            RESOLVED_VERSION="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
        fi
    fi
    [[ -f "$SOURCE_DIR/backend/requirements.txt" && -f "$SOURCE_DIR/scripts/configure-env.py" && -f "$SOURCE_DIR/scripts/data-admin.py" ]] || die 'La fuente no contiene la aplicación y utilidades esperadas.'
    export RESOLVED_VERSION RESOLVED_METHOD
}

build_release() {
    RELEASE="$APP_ROOT/releases/$(date -u +%Y%m%dT%H%M%S)-$$"
    mkdir "$RELEASE"
    rsync -a --exclude=.git --exclude='.venv*' --exclude=.superpowers --exclude=docs --exclude=graphify-out \
        --exclude=node_modules --exclude='.env*' --exclude=data --exclude=test-results --exclude=venv \
        "$SOURCE_DIR/" "$RELEASE/"
    if [[ "$RESOLVED_METHOD" != release ]]; then rm -rf -- "$RELEASE/frontend/.next"; fi
    chown -R "$APP_USER:$APP_GROUP" "$RELEASE"
    runuser -u "$APP_USER" -- python3 -m venv "$RELEASE/venv"
    runuser -u "$APP_USER" -- "$RELEASE/venv/bin/pip" install -r "$RELEASE/backend/requirements.txt"
    if [[ "$RESOLVED_METHOD" == source ]]; then
        (
            cd "$RELEASE/frontend"
            runuser -u "$APP_USER" -- env PATH="$(dirname "$NODE_BINARY"):$PATH" npm_config_cache="$RELEASE/.npm" npm ci --no-audit
            runuser -u "$APP_USER" -- env PATH="$(dirname "$NODE_BINARY"):$PATH" npm_config_cache="$RELEASE/.npm" npm run build
        )
        mkdir -p "$RELEASE/frontend/.next/standalone/.next" "$RELEASE/frontend/public"
        cp -a "$RELEASE/frontend/.next/static" "$RELEASE/frontend/.next/standalone/.next/"
        cp -a "$RELEASE/frontend/public" "$RELEASE/frontend/.next/standalone/"
    fi
    [[ -f "$RELEASE/frontend/.next/standalone/server.js" ]] || die 'El bundle no contiene el frontend standalone.'
    chown -R root:"$APP_GROUP" "$RELEASE"
    chmod -R u+rwX,go-w,g+rX "$RELEASE"
    install -d -o "$APP_USER" -g "$APP_GROUP" "$RELEASE/frontend/.next/standalone/.next/cache"
    SOURCE_DIR="$RELEASE"
}

prepare_repair() {
    RELEASE="$(readlink -f "$APP_ROOT/current")"
    [[ -f "$RELEASE/frontend/.next/standalone/server.js" && -x "$RELEASE/venv/bin/python" ]] || die 'No existe una versión completa que reparar.'
    SOURCE_DIR="$RELEASE"
    NODE_BINARY="$(env_read "$ENV_FILE" NODE_BINARY)"
    [[ -n "$NODE_BINARY" ]] || NODE_BINARY="$APP_ROOT/node/bin/node"
    [[ -x "$NODE_BINARY" ]] || die 'No existe Node; usa update para reconstruir las dependencias.'
    TDL_BINARY="$(env_read "$ENV_FILE" TDL_BINARY)"
    RESOLVED_VERSION="$(env_read "$ENV_FILE" APP_VERSION)"
    RESOLVED_METHOD="$(env_read "$ENV_FILE" RESOLVED_METHOD)"
    export NODE_BINARY TDL_BINARY RESOLVED_VERSION RESOLVED_METHOD
}

ensure_oidc() {
    local name value
    for name in AUTHENTIK_ISSUER AUTHENTIK_CLIENT_ID AUTHENTIK_CLIENT_SECRET; do
        value="${!name:-}"
        if [[ -z "$value" && -f "$ENV_FILE" ]]; then
            value="$(python3 - "$ENV_FILE" "$name" "${SOURCE_DIR:-$SCRIPT_DIR}" <<'PY'
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('config',Path(sys.argv[3])/'scripts/configure-env.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
print(module.read_env(Path(sys.argv[1])).get(sys.argv[2],''),end='')
PY
)"
        fi
        if [[ -z "$value" || "$value" == replace-* ]]; then
            can_prompt || die "Falta $name de tu proveedor externo. La configuración básica ya está preparada; vuelve a ejecutar el instalador desde una terminal para completar el asistente (o proporciona el valor por entorno)."
            if [[ "$name" == AUTHENTIK_CLIENT_SECRET ]]; then read -r -s -u "${INPUT_FD:-0}" -p "$name: " value; printf '\n' >&2
            else read -r -u "${INPUT_FD:-0}" -p "$name: " value; fi
        fi
        [[ -n "$value" && "$value" != *$'\n'* && "$value" != *$'\r'* ]] || die "Valor inválido: $name"
        printf -v "$name" '%s' "$value"; export "${name?}"
    done
    if [[ "${NEW_ENV:-0}" == 1 ]]; then
        write_environment "$ENV_FILE"
        chgrp "$APP_GROUP" "$ENV_FILE"
        chmod 640 "$ENV_FILE"
    fi
    [[ "$AUTHENTIK_ISSUER" == https://* ]] || die 'El issuer de Authentik debe usar HTTPS.'
    fetch "${AUTHENTIK_ISSUER%/}/.well-known/openid-configuration" "$WORK/discovery.json"
    python3 - "$WORK/discovery.json" "$AUTHENTIK_ISSUER" <<'PY'
import json,sys
if json.load(open(sys.argv[1])).get('issuer') != sys.argv[2]:
    raise SystemExit('AUTHENTIK_ISSUER debe coincidir exactamente con el issuer de discovery.')
PY
}

prepare_candidate() {
    CANDIDATE="$WORK/candidate.env"
    write_environment "$CANDIDATE"
    validate_data_paths
    # Only mutable state is owned by the service. Existing files stay in place.
    python3 - "$SOURCE_DIR/scripts" "$CANDIDATE" "$APP_USER" "$APP_GROUP" <<'PY'
import importlib.util, os, pwd, grp, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('config', Path(sys.argv[1])/'configure-env.py')
config=importlib.util.module_from_spec(spec); spec.loader.exec_module(config)
values=config.read_env(Path(sys.argv[2])); uid=pwd.getpwnam(sys.argv[3]).pw_uid; gid=grp.getgrnam(sys.argv[4]).gr_gid
paths=[values[k] for k in ('DATA_DIR','TDL_SESSIONS_DIR','EXPORTS_DIR','DOWNLOADS_DIR','LOGS_DIR','TMP_DIR')]
paths.append(str(Path(values['DATABASE_URL'].removeprefix('sqlite:///')).parent))
for raw in paths:
    path=Path(raw)
    if not path.is_absolute() or path == Path('/'):
        raise SystemExit(f'Ruta de datos inválida: {raw}')
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid); path.chmod(0o750)
PY
}

validate_data_paths() {
    python3 - "${SOURCE_DIR:-$SCRIPT_DIR}/scripts" "${CANDIDATE:-$ENV_FILE}" "$APP_ROOT" "$CONFIG_DIR" <<'PY'
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('config',Path(sys.argv[1])/'configure-env.py')
config=importlib.util.module_from_spec(spec);spec.loader.exec_module(config)
values=config.read_env(Path(sys.argv[2])); root=Path(sys.argv[3]).resolve(); configdir=Path(sys.argv[4]).resolve()
keys=['DATA_DIR','TDL_SESSIONS_DIR','EXPORTS_DIR','DOWNLOADS_DIR','LOGS_DIR','TMP_DIR']
if values.get('DATABASE_URL'):
    if not values['DATABASE_URL'].startswith('sqlite:///'):
        raise SystemExit('Ruta de datos DATABASE_URL debe usar SQLite.')
    values['DATABASE_PARENT']=str(Path(values['DATABASE_URL'].removeprefix('sqlite:///')).parent)
    keys.append('DATABASE_PARENT')
for key in keys:
    if not values.get(key):
        continue
    raw=Path(values[key]); path=raw.resolve()
    protected=[Path(p) for p in ('/etc','/usr','/bin','/sbin','/lib','/lib64','/proc','/sys','/dev','/run')]
    protected += [configdir,root/'releases',root/'tools',root/'backups',root/'current']
    if not raw.is_absolute() or path in (Path('/'),Path('/opt'),Path('/var'),Path('/home'),root) or any(
        path == p or path.is_relative_to(p) or p.is_relative_to(path) for p in protected
    ):
        raise SystemExit(f'Ruta de datos protegida o solapada: {key}')
PY
}

data_admin() { python3 "$SOURCE_DIR/scripts/data-admin.py" "$1" --env "$ENV_FILE" "${@:2}"; }
health_check() {
    curl --fail --silent --retry 15 --retry-delay 2 --retry-connrefused "http://127.0.0.1:$API_PORT/health" >/dev/null
    curl --fail --silent --retry 15 --retry-delay 2 --retry-connrefused "http://127.0.0.1:$APP_PORT/login" >/dev/null
}

link_layout_aliases() {
    local name target
    for name in app config .env; do
        target="$APP_ROOT/current"; [[ "$name" != config ]] || target="$(dirname "$ENV_FILE")"
        [[ "$name" != .env ]] || target="$ENV_FILE"
        if [[ ! -e "$APP_ROOT/$name" && ! -L "$APP_ROOT/$name" ]]; then ln -s "$target" "$APP_ROOT/$name"; fi
    done
}

activate_release() (
    local previous backup='' unit replaced=0 redis_touched=0 redis_active=0 redis_enabled=0
    local -a active_services=() enabled_services=()
    previous="$(readlink -f "$APP_ROOT/current" 2>/dev/null || true)"
    for unit in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "$unit"; then active_services+=("$unit"); fi
        if systemctl is-enabled --quiet "$unit"; then enabled_services+=("$unit"); fi
    done
    restore_previous() {
        local result=$1 file
        [[ "$result" == 0 ]] && return
        trap - EXIT
        if [[ "$replaced" == 1 ]]; then
            systemctl stop "${SERVICES[@]}" || true
            for file in env defaults; do
                local destination="$ENV_FILE"; [[ "$file" != defaults ]] || destination="$INSTALL_CONF"
                if [[ -f "$backup/$file" ]]; then cp -p -- "$backup/$file" "$destination"; else rm -f -- "$destination"; fi
            done
            if [[ -f "$backup/database.sqlite3" ]]; then
                python3 "$SOURCE_DIR/scripts/data-admin.py" restore-database --env "$ENV_FILE" --backup "$backup" || true
            fi
            for unit in "${SERVICES[@]}"; do
                if [[ -f "$backup/$unit.service" ]]; then cp -p -- "$backup/$unit.service" "$SYSTEMD_DIR/"
                else rm -f -- "$SYSTEMD_DIR/$unit.service"; fi
            done
            if [[ -n "$previous" && -d "$previous" ]]; then ln -sfn "$previous" "$APP_ROOT/current"
            elif [[ -L "$APP_ROOT/current" ]]; then rm -f -- "$APP_ROOT/current"; fi
            if [[ "$redis_touched" == 1 ]]; then
                cp -p -- "$backup/redis.conf" "${REDIS_CONFIG:-/etc/redis/redis.conf}"
                if [[ "$redis_active" == 1 ]]; then systemctl restart redis-server || true; else systemctl stop redis-server || true; fi
                [[ "$redis_enabled" == 1 ]] || systemctl disable redis-server || true
            fi
            systemctl daemon-reload
            systemctl disable "${SERVICES[@]}" || true
            ((${#enabled_services[@]} == 0)) || systemctl enable "${enabled_services[@]}" || true
        fi
        ((${#active_services[@]} == 0)) || systemctl start "${active_services[@]}" || true
        printf 'Activación fallida. Se intentó recuperar la versión anterior. Respaldo: %s\n' "${backup:-no creado}" >&2
        journalctl --no-pager -n 30 -u "$SERVICE_API" -u "$SERVICE_WORKER" -u "$SERVICE_WEB" >&2 || true
        exit "$result"
    }
    trap 'restore_previous $?' EXIT
    [[ ! -f "$ENV_FILE" ]] || data_admin check-idle
    if [[ -f "$SYSTEMD_DIR/$SERVICE_WEB.service" ]]; then systemctl stop "$SERVICE_WEB"; fi
    [[ ! -f "$ENV_FILE" ]] || data_admin check-idle
    for unit in "$SERVICE_API" "$SERVICE_WORKER"; do
        if [[ -f "$SYSTEMD_DIR/$unit.service" ]]; then systemctl stop "$unit"; fi
    done
    if [[ -f "$ENV_FILE" ]]; then backup="$(data_admin backup --destination-root "$BACKUPS_DIR")"
    else backup="$BACKUPS_DIR/$(date -u +%Y%m%dT%H%M%S)-$$"; mkdir -p "$backup"; fi
    chmod 700 "$backup"
    [[ ! -f "$ENV_FILE" ]] || cp -p -- "$ENV_FILE" "$backup/env"
    [[ ! -f "$INSTALL_CONF" ]] || cp -p -- "$INSTALL_CONF" "$backup/defaults"
    for unit in "${SERVICES[@]}"; do [[ ! -f "$SYSTEMD_DIR/$unit.service" ]] || cp -p -- "$SYSTEMD_DIR/$unit.service" "$backup/"; done
    if [[ "$INSTALL_REDIS" == 1 ]]; then
        cp -p -- "${REDIS_CONFIG:-/etc/redis/redis.conf}" "$backup/redis.conf"
        if systemctl is-active --quiet redis-server; then redis_active=1; fi
        if systemctl is-enabled --quiet redis-server; then redis_enabled=1; fi
    fi
    render_units "$WORK/units"
    replaced=1
    install -m 640 -g "$APP_GROUP" "$CANDIDATE" "$ENV_FILE"
    if [[ "$SAVE_DEFAULTS" == 1 ]]; then write_defaults "$INSTALL_CONF"; fi
    for unit in "${SERVICES[@]}"; do install -m 644 "$WORK/units/$unit.service" "$SYSTEMD_DIR/"; done
    ln -sfn "$RELEASE" "$APP_ROOT/current"
    if [[ "$INSTALL_REDIS" == 1 ]]; then redis_touched=1; configure_redis; fi
    systemctl daemon-reload
    systemctl enable "${SERVICES[@]}"
    systemctl restart "${SERVICES[@]}"
    health_check
    link_layout_aliases
    trap - EXIT
    printf 'Versión activa: %s\nRespaldo: %s\nAcceso local: http://localhost:%s\n' "$RELEASE" "$backup" "$APP_PORT"
    printf 'Servicios: systemctl status %s %s %s\n' "$SERVICE_API" "$SERVICE_WORKER" "$SERVICE_WEB"
)

run_installation() {
    preflight
    if [[ "$ACTION" != repair && "$ACTION" != configure ]]; then
        apt-get update
        local -a packages=(ca-certificates curl git rsync python3 python3-venv python3-pip build-essential wipe xz-utils)
        [[ "$INSTALL_REDIS" != 1 ]] || packages+=(redis-server)
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --no-upgrade "${packages[@]}"
    fi
    prepare_layout
    check_service_ports
    if [[ "$ACTION" == repair || "$ACTION" == configure ]]; then prepare_repair
    else resolve_source; fi
    prepare_environment
    ensure_oidc
    if [[ "$ACTION" != repair && "$ACTION" != configure ]]; then install_binaries; build_release; fi
    prepare_candidate
    activate_release
}

main() {
    local dry_run=0
    init_input
    while (($#)); do
        case "$1" in
            --dry-run) dry_run=1; shift ;;
            --yes) ASSUME_YES=1; shift ;;
            --action) ACTION="${2:?Falta acción}"; shift 2 ;;
            --source-dir) SOURCE_DIR="${2:?Falta ruta}"; shift 2 ;;
            --root) APP_ROOT="${2:?Falta ruta}"; shift 2 ;;
            --port) APP_PORT="${2:?Falta puerto}"; shift 2 ;;
            --ref) APP_REF="${2:?Falta ref}"; shift 2 ;;
            --method) INSTALL_METHOD="${2:?Falta método}"; shift 2 ;;
            --help|-h) printf '%s\n' 'Uso: bash install-tld.sh [--action install|update|repair|configure|cancel] [--dry-run] [--yes] [--source-dir RUTA] [--root RUTA] [--port PUERTO] [--ref latest|TAG|COMMIT] [--method auto|source|release]'; return ;;
            *) die "Opción desconocida: $1" ;;
        esac
    done
    discover_files
    local default_action=install
    local installed_root="${APP_ROOT:-$(env_read "$ENV_FILE" APP_ROOT)}"
    [[ ! -f "$ENV_FILE" || ! -L "${installed_root:-/opt/tld-web}/current" ]] || default_action=cancel
    ACTION="${ACTION:-$(prompt_default 'Acción (install/update/repair/configure/cancel)' "$default_action") }"
    ACTION="${ACTION% }"
    case "$ACTION" in install|update|repair|configure) ;; cancel) printf 'Cancelado.\n'; return ;; *) die 'Acción inválida.' ;; esac
    collect_options
    validate_options
    if [[ "$dry_run" == 1 ]]; then print_summary; return; fi
    print_summary
    [[ $(id -u) == 0 ]] || die 'Ejecuta el maestro como root dentro del LXC.'
    run_installation
}

if [[ "${BASH_SOURCE[0]:-}" == "$0" || -z "${BASH_SOURCE[0]:-}" ]]; then main "$@"; fi
