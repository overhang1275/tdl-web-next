#!/usr/bin/env bash
# Native LXC entry point: install, update or repair the application.
set -euo pipefail

SCRIPT_DIR=''
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi
WORK=''
DEFAULT_KEYS=(APP_ROOT APP_HOST APP_ALLOWED_SUBNET APP_PORT API_PORT APP_USER CREATE_USER INSTALL_REDIS APP_REF
              INSTALL_METHOD SOURCE_REPO PUBLIC_URL AUTH_URL SAVE_DEFAULTS SERVICE_WEB
              SERVICE_API SERVICE_WORKER SERVICE_NETWORK)

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

env_read() {
    # Runs before the source/dependencies are available, including curl | bash.
    python3 - "$1" "$2" <<'PY'
import os, shlex, stat, sys
from pathlib import Path
path=Path(sys.argv[1])
if not path.is_absolute() or '..' in path.parts:
    raise SystemExit('Configuración requiere ruta absoluta confiable')
fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
try:
    for component in path.parts[1:-1]:
        child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
        os.close(fd); fd=child
        st=os.fstat(fd)
        if st.st_uid != 0 or (st.st_mode & 0o022 and not st.st_mode & stat.S_ISVTX):
            raise ValueError('Directorio de configuración no confiable')
    file=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    with os.fdopen(file,'rb') as stream:
        st=os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_uid != 0 or stat.S_IMODE(st.st_mode) not in (0o600,0o640):
            raise ValueError('Configuración requiere archivo root0600 o legado root0640')
        raw=stream.read(65537)
        if len(raw)>65536: raise ValueError('Configuración demasiado grande')
    for line in raw.decode().splitlines():
        if '=' not in line or line.lstrip().startswith('#'): continue
        key,value=line.split('=',1)
        if key.strip()==sys.argv[2]:
            value=value.strip()
            if value.startswith(('"',"'")):
                parts=shlex.split(value,comments=False)
                if len(parts)!=1: raise ValueError('Valor inválido')
                value=parts[0]
            print(value,end=''); break
except FileNotFoundError:
    pass
finally:
    os.close(fd)
PY
}

pick_value() {
    local name=$1 fallback=$2 value
    if [[ -v "$name" ]]; then printf '%s' "${!name}"; return; fi
    value="$(env_read "$ENV_FILE" "$name")"
    [[ -n "$value" || -z "${LEGACY_ENV_FILE:-}" ]] || value="$(env_read "$LEGACY_ENV_FILE" "$name")"
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
            LEGACY_ENV_FILE=/etc/telegram-downloader/telegram-downloader.env
        fi
    fi
    local input
    for input in "$ENV_FILE" "$INSTALL_CONF" "${LEGACY_ENV_FILE:-$ENV_FILE}"; do
        env_read "$input" '' >/dev/null || die 'Configuración no confiable; no se modifica la instalación.'
    done
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
    local lan_default=n
    [[ "$APP_HOST" == 127.0.0.1 || "$APP_HOST" == 0.0.0.0 ]] || die 'Interfaz web inválida.'
    [[ "$APP_HOST" != 0.0.0.0 ]] || lan_default=S
    if [[ "$(yes_no "$(prompt_default '¿El túnel está en otra máquina de 192.168.100.0/24? S/n' "$lan_default")")" == 1 ]]; then
        APP_HOST=0.0.0.0
    else APP_HOST=127.0.0.1; fi
    APP_ALLOWED_SUBNET="$(pick_value APP_ALLOWED_SUBNET 192.168.100.0/24)"
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
    AUTH_URL="$(prompt_default 'URL de ESTA consola TDL (no el dominio de Authentik)' "$(pick_value AUTH_URL "http://localhost:$APP_PORT")")"
    AUTH_URL="${AUTH_URL%/}"
    SAVE_DEFAULTS="$(yes_no "$(prompt_default '¿Guardar estas opciones como defaults? S/n' "$(pick_value SAVE_DEFAULTS S)")")"
    local web=tld-web api=tld-web-api worker=tld-web-worker
    if [[ "$legacy" == 1 ]]; then web=telegram-downloader-web; api=telegram-downloader-api; worker=telegram-downloader-worker; fi
    SERVICE_WEB="$(pick_value SERVICE_WEB "$web")"
    SERVICE_API="$(pick_value SERVICE_API "$api")"
    SERVICE_WORKER="$(pick_value SERVICE_WORKER "$worker")"
    SERVICE_NETWORK="$(pick_value SERVICE_NETWORK "$web-network")"
    SERVICE_MIGRATE=tld-web-migrate
    RUNTIME_ENV="$CONFIG_DIR/runtime.env"
    SERVICES=("$SERVICE_API" "$SERVICE_WORKER" "$SERVICE_WEB")
    if [[ "$APP_HOST" == 0.0.0.0 ]]; then SERVICES=("$SERVICE_NETWORK" "${SERVICES[@]}"); fi
    BACKUPS_DIR="$APP_ROOT/backups"
    ADMIN_USERNAME="$(pick_value ADMIN_USERNAME admin)"
    export APP_ROOT APP_HOST APP_PORT API_PORT APP_USER INSTALL_REDIS CREATE_USER PUBLIC_URL
    export AUTH_URL APP_REF INSTALL_METHOD SOURCE_REPO SERVICE_WEB SERVICE_API SERVICE_WORKER BACKUPS_DIR REDIS_URL
    export APP_ALLOWED_SUBNET SERVICE_NETWORK ADMIN_USERNAME
}

valid_path() { [[ "$1" =~ ^/[A-Za-z0-9_./-]+$ && "$1" != / && "$1" != *'/../'* && "$1" != */.. && "$1" != *'/./'* ]]; }

validate_options() {
    if ! valid_path "$APP_ROOT" || ! valid_path "$CONFIG_DIR" || ! valid_path "$ENV_FILE" || ! valid_path "$SYSTEMD_DIR"; then die 'Usa rutas absolutas sin espacios ni segmentos . o ...'; fi
    [[ "$APP_ROOT" != /etc && "$APP_ROOT" != /usr && "$APP_ROOT" != /var && "$APP_ROOT" != /home && "$APP_ROOT" != /opt ]] || die 'Elige una carpeta exclusiva para la aplicación.'
    [[ "$APP_HOST" == 127.0.0.1 || "$APP_HOST" == 0.0.0.0 ]] || die 'APP_HOST debe ser 127.0.0.1 o 0.0.0.0 con firewall.'
    [[ "$APP_ALLOWED_SUBNET" == 192.168.100.0/24 ]] || die 'La subred autorizada debe ser 192.168.100.0/24.'
    local port service
    for port in "$APP_PORT" "$API_PORT"; do
        if [[ ! "$port" =~ ^[0-9]{1,5}$ ]] || ! ((10#$port > 0 && 10#$port <= 65535)); then die 'Puerto inválido (1–65535).'; fi
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
    for directory in "$APP_ROOT" "$CONFIG_DIR" "$SYSTEMD_DIR" "$ENV_FILE"; do
        while [[ "$directory" != / ]]; do
            [[ ! -L "$directory" ]] || die 'Las rutas de instalación no pueden contener enlaces simbólicos.'
            directory="${directory%/*}"; directory="${directory:-/}"
        done
    done
}

print_summary() {
    printf '%s\n' "APP_ROOT=$APP_ROOT" "APP_HOST=$APP_HOST" "APP_PORT=$APP_PORT" "API_PORT=$API_PORT" \
        "APP_USER=$APP_USER" "APP_REF=$APP_REF" "INSTALL_METHOD=$INSTALL_METHOD" \
        "INSTALL_REDIS=$INSTALL_REDIS" "PUBLIC_URL=$PUBLIC_URL" "AUTH_URL=$AUTH_URL" "ENV_FILE=$ENV_FILE" "APP_ALLOWED_SUBNET=$APP_ALLOWED_SUBNET"
}

options_json() {
    export CONFIG_DIR NODE_BINARY="${NODE_BINARY:-}" RESOLVED_VERSION="${RESOLVED_VERSION:-local}" RESOLVED_METHOD="${RESOLVED_METHOD:-source}"
    if [[ "${FRESH:-0}" == 1 && -z "${FRESH_INSTALLATION_ID:-}" ]]; then FRESH_INSTALLATION_ID="$(python3 -c 'from uuid import uuid4; print(uuid4())')"; fi
    export FRESH="${FRESH:-0}" FRESH_INSTALLATION_ID="${FRESH_INSTALLATION_ID:-}"
    export PROMPT_ADMIN_PASSWORD=false
    if can_prompt; then PROMPT_ADMIN_PASSWORD=true; fi
    if id "$APP_USER" >/dev/null 2>&1; then APP_UID="$(id -u "$APP_USER")"; APP_GID="$(id -g "$APP_USER")"; fi
    export APP_UID="${APP_UID:-10001}" APP_GID="${APP_GID:-10001}"
    python3 -c 'import json,os; names="APP_ROOT APP_HOST APP_ALLOWED_SUBNET APP_PORT API_PORT APP_USER APP_UID APP_GID INSTALL_REDIS PUBLIC_URL AUTH_URL REDIS_URL CONFIG_DIR BACKUPS_DIR SERVICE_WEB SERVICE_API SERVICE_WORKER SERVICE_NETWORK NODE_BINARY RESOLVED_VERSION RESOLVED_METHOD ADMIN_USERNAME".split(); result={k:os.environ.get(k, "") for k in names}; result.update({k:os.environ[k] for k in "TDL_BINARY DATABASE_URL AUTHENTIK_ENABLED ADMIN_PASSWORD_FILE FRESH FRESH_INSTALLATION_ID".split() if os.environ.get(k)}); result["PROMPT_ADMIN_PASSWORD"]=os.environ["PROMPT_ADMIN_PASSWORD"]=="true"; print(json.dumps(result))'
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
    local destination=$1 options legacy=$ENV_FILE status=0
    [[ -f "$ENV_FILE" ]] || legacy="${LEGACY_ENV_FILE:-$ENV_FILE}"
    options="$(mktemp)"
    options_json > "$options"
    python3 "${SOURCE_DIR:-$SCRIPT_DIR}/scripts/configure-env.py" --deployment native --domain localhost \
        --root "$APP_ROOT" --output "$destination" --legacy "$legacy" --native-options "$options" || status=$?
    rm -f -- "$options"
    return "$status"
}

prepare_environment() {
    if [[ ! -e "$APP_ROOT/current" ]]; then NEW_ENV=1; fi
    [[ ! -f "$ENV_FILE" ]] || return 0
    mkdir -p -- "$(dirname "$ENV_FILE")"
    write_environment "$ENV_FILE"
    chown root:root "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    if [[ "$SAVE_DEFAULTS" == 1 ]]; then write_defaults "$INSTALL_CONF"; fi
    link_layout_aliases
    printf 'Configuración básica privada creada en %s.\n' "$ENV_FILE"
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
    cat > "$directory/$SERVICE_MIGRATE.service" <<EOF
# Managed by install-tld.sh: $APP_ROOT
[Unit]
Description=TLD PostgreSQL migration
After=network-online.target postgresql.service
Wants=network-online.target
Before=$SERVICE_API.service $SERVICE_WORKER.service
[Service]
Type=oneshot
RemainAfterExit=yes
User=$APP_USER
Group=${APP_GROUP:-$APP_USER}
WorkingDirectory=${RELEASE:-$APP_ROOT/current}/backend
EnvironmentFile=${MIGRATION_ENV:-$RUNTIME_ENV}
ExecStart=${RELEASE:-$APP_ROOT/current}/venv/bin/alembic upgrade head
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
UMask=0077
EOF
    cat > "$directory/$SERVICE_WEB.service" <<EOF
# Managed by install-tld.sh: $APP_ROOT
[Unit]
Description=TLD Web frontend
After=network-online.target $SERVICE_API.service
Wants=network-online.target $SERVICE_API.service
Requires=$SERVICE_API.service
[Service]
User=$APP_USER
Group=${APP_GROUP:-$APP_USER}
WorkingDirectory=$APP_ROOT/current/frontend/.next/standalone
EnvironmentFile=$RUNTIME_ENV
Environment=NODE_ENV=production HOSTNAME=$APP_HOST PORT=$APP_PORT
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
    if [[ "$APP_HOST" == 0.0.0.0 ]]; then
        sed -i "/^After=/s/$/ $SERVICE_NETWORK.service/;/^Wants=/a Requires=$SERVICE_NETWORK.service" "$directory/$SERVICE_WEB.service"
        cat > "$directory/$SERVICE_NETWORK.service" <<EOF
# Managed by install-tld.sh: $APP_ROOT
[Unit]
Description=TLD Web restricted LAN access
After=network-online.target nftables.service
Wants=network-online.target
Before=$SERVICE_WEB.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft --file $CONFIG_DIR/network.nft
ExecStop=-/usr/sbin/nft delete table inet ${SERVICE_WEB//[^a-zA-Z0-9_]/_}_access
[Install]
WantedBy=multi-user.target
EOF
    fi
    cat > "$directory/$SERVICE_API.service" <<EOF
# Managed by install-tld.sh: $APP_ROOT
[Unit]
Description=TLD Web API
After=network-online.target $SERVICE_MIGRATE.service
Wants=network-online.target
Requires=$SERVICE_MIGRATE.service
[Service]
User=$APP_USER
Group=${APP_GROUP:-$APP_USER}
WorkingDirectory=$APP_ROOT/current/backend
EnvironmentFile=$RUNTIME_ENV
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
    sed "s/Description=TLD Web API/Description=TLD Web worker/;s|^ExecStart=.*|ExecStart=$APP_ROOT/current/venv/bin/python -m app.rq_worker|;/^ExecStartPost=/d;s/^After=.*/After=network-online.target $SERVICE_MIGRATE.service $SERVICE_API.service/;s/^Requires=.*/Requires=$SERVICE_MIGRATE.service $SERVICE_API.service/" \
        "$directory/$SERVICE_API.service" > "$directory/$SERVICE_WORKER.service"
}

render_firewall() {
    local destination=$1 table="${SERVICE_WEB//[^a-zA-Z0-9_]/_}_access"
    mkdir -p -- "$(dirname "$destination")"
    cat > "$destination" <<EOF
add table inet $table
flush table inet $table
table inet $table {
    chain frontend {
        type filter hook input priority -10; policy accept;
        iifname "lo" tcp dport $APP_PORT accept
        ip saddr $APP_ALLOWED_SUBNET tcp dport $APP_PORT accept
        tcp dport $APP_PORT drop
    }
}
EOF
}

check_network_access() {
    [[ "$APP_HOST" == 0.0.0.0 ]] || return 0
    [[ ! -f "$SYSTEMD_DIR/$SERVICE_NETWORK.service" ]] || owned_service "$SERVICE_NETWORK" || die 'La unidad de firewall pertenece a otra instalación.'
    if nft list table inet "${SERVICE_WEB//[^a-zA-Z0-9_]/_}_access" >/dev/null 2>&1 && ! owned_service "$SERVICE_NETWORK"; then
        die 'La tabla de firewall ya existe sin una unidad administrada de esta instalación; no se modificará.'
    fi
    render_firewall "$WORK/network.nft"
    nft --check --file "$WORK/network.nft" || die 'No se puede aplicar el firewall dentro del LXC. No se expondrá el frontend; revisa CAP_NET_ADMIN en Proxmox.'
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
    # shellcheck disable=SC1091
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
    exec {INSTALL_LOCK}>"$CONFIG_DIR/install.lock"
    flock -n "$INSTALL_LOCK" || die 'Ya existe una instalación en curso.'
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
    [[ ! -f "$SYSTEMD_DIR/$SERVICE_MIGRATE.service" ]] || owned_service "$SERVICE_MIGRATE" || die 'La unidad migrate pertenece a otra instalación.'
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

verify_release_code() {
    python3 - "$RELEASE" <<'PY'
import os, sys
from pathlib import Path
release=Path(sys.argv[1])
for base in (release/'backend', release/'scripts', release/'venv'):
    if not base.is_dir(): raise SystemExit('Release root incompleta')
    for path in (base, *base.rglob('*')):
        if path.is_symlink() and path.is_dir() and not path.resolve().is_relative_to(release):
            raise SystemExit('Código root enlazado a directorio fuera de la release; reconstruye con update')
        st=path.stat()
        if st.st_uid != 0 or st.st_mode & 0o022:
            raise SystemExit('Código ejecutado por root modificable por otro usuario; reconstruye con update')
PY
}

ensure_oidc() {
    AUTHENTIK_ENABLED="$(pick_value AUTHENTIK_ENABLED false)"
    export AUTHENTIK_ENABLED
    # The generator validates enabled fields locally; provider outages cannot block local login.
}

bootstrap_admin() {
    local username password_file configuration=${CANDIDATE:-$ENV_FILE}
    username="$(env_read "$configuration" ADMIN_USERNAME)"
    password_file="$(env_read "$configuration" ADMIN_PASSWORD_FILE)"
    PYTHONPATH="$RELEASE/backend" "$RELEASE/venv/bin/python" -m app.admin create-admin \
        --username "$username" --password-file "$password_file" --env-file "$configuration"
    printf 'Contraseña inicial protegida: %s\nConsultar como root: sudo cat -- %q\nDebe cambiarse al entrar.\n' "$password_file" "$password_file"
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
if values.get('DATABASE_URL', '').startswith('sqlite:'):
    raise SystemExit('La base de datos SQLite heredada requiere --fresh; no se modificará.')
if values.get('DATABASE_URL'):
    config.database_identity(values['DATABASE_URL'])
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

data_admin() { "$RELEASE/venv/bin/python" "$SOURCE_DIR/scripts/data-admin.py" "$1" --env "$ENV_FILE" "${@:2}"; }

prepare_postgres() {
    local -a fresh=()
    [[ "${FRESH:-0}" != 1 && "${NEW_ENV:-0}" != 1 ]] || fresh=(--fresh)
    "$RELEASE/venv/bin/python" "$SOURCE_DIR/scripts/native-postgres.py" prepare \
        --env "$CANDIDATE" --output "$CONFIG_DIR/postgres-resources" "${fresh[@]}"
}

prepare_runtime() {
    "$RELEASE/venv/bin/python" "$SOURCE_DIR/scripts/native-postgres.py" runtime \
        --env "$CANDIDATE" --output "$WORK/runtime.env"
}

migrate_database() {
    MIGRATION_ENV="$WORK/runtime.env" render_units "$WORK/migration-units"
    install -m 644 "$WORK/migration-units/$SERVICE_MIGRATE.service" "$SYSTEMD_DIR/"
    systemctl daemon-reload
    systemctl restart "$SERVICE_MIGRATE"
}
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
    local previous backup='' unit replaced=0 redis_touched=0 redis_active=0 redis_enabled=0 old_postgres=0
    local -a active_services=() enabled_services=()
    previous="$(readlink -f "$APP_ROOT/current" 2>/dev/null || true)"
    for unit in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "$unit"; then active_services+=("$unit"); fi
        if systemctl is-enabled --quiet "$unit"; then enabled_services+=("$unit"); fi
    done
    # Invoked indirectly by the EXIT trap, including failed migration/bootstrap.
    # shellcheck disable=SC2317
    restore_previous() {
        local result=$1 file
        [[ "$result" == 0 ]] && return
        trap - EXIT
        if [[ "$replaced" == 1 ]]; then
            systemctl stop "${SERVICES[@]}" || true
            systemctl stop "$SERVICE_MIGRATE" || true
            for file in env defaults runtime; do
                local destination="$ENV_FILE"; [[ "$file" != defaults ]] || destination="$INSTALL_CONF"
                [[ "$file" != runtime ]] || destination="$RUNTIME_ENV"
                if [[ -f "$backup/$file" ]]; then cp -p -- "$backup/$file" "$destination.rollback"; mv -f -- "$destination.rollback" "$destination"; else rm -f -- "$destination"; fi
            done
            if [[ "$APP_HOST" == 0.0.0.0 ]]; then
                if [[ -f "$backup/network.nft" ]]; then cp -p "$backup/network.nft" "$CONFIG_DIR/network.nft"
                else rm -f -- "$CONFIG_DIR/network.nft"; fi
            fi
            # Schema/data are never rolled back automatically after candidate migrations or writes.
            for unit in "${SERVICES[@]}" "$SERVICE_MIGRATE"; do
                if [[ -f "$backup/$unit.service" ]]; then cp -p -- "$backup/$unit.service" "$SYSTEMD_DIR/"
                else rm -f -- "$SYSTEMD_DIR/$unit.service"; fi
            done
            if [[ -n "$previous" && -d "$previous" ]]; then ln -s "$previous" "$APP_ROOT/.current-rollback-$$"; mv -Tf "$APP_ROOT/.current-rollback-$$" "$APP_ROOT/current"
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
        printf 'Activación fallida. Se intentó recuperar release/config anterior; esquema PostgreSQL sin rollback automático. Respaldo: %s\n' "${backup:-no creado}" >&2
        journalctl --no-pager -n 30 -u "$SERVICE_API" -u "$SERVICE_WORKER" -u "$SERVICE_WEB" >&2 || true
        exit "$result"
    }
    trap 'restore_previous $?' EXIT
    if [[ "${NEW_ENV:-0}" != 1 && "$(env_read "$ENV_FILE" DATABASE_URL)" == postgres* ]]; then old_postgres=1; fi
    [[ "$old_postgres" != 1 ]] || data_admin check-idle
    if [[ -f "$SYSTEMD_DIR/$SERVICE_WEB.service" ]]; then systemctl stop "$SERVICE_WEB"; fi
    for unit in "$SERVICE_API" "$SERVICE_WORKER"; do
        if [[ -f "$SYSTEMD_DIR/$unit.service" ]]; then systemctl stop "$unit"; fi
    done
    [[ "$old_postgres" != 1 ]] || data_admin check-idle
    if [[ "$old_postgres" == 1 ]]; then backup="$(data_admin backup --destination-root "$BACKUPS_DIR")"
    else backup="$BACKUPS_DIR/$(date -u +%Y%m%dT%H%M%S)-$$"; mkdir -p "$backup"; fi
    chmod 700 "$backup"
    [[ ! -f "$ENV_FILE" ]] || cp -p -- "$ENV_FILE" "$backup/env"
    [[ ! -f "$INSTALL_CONF" ]] || cp -p -- "$INSTALL_CONF" "$backup/defaults"
    [[ ! -f "$RUNTIME_ENV" ]] || cp -p -- "$RUNTIME_ENV" "$backup/runtime"
    if [[ "$APP_HOST" == 0.0.0.0 && -f "$CONFIG_DIR/network.nft" ]]; then cp -p "$CONFIG_DIR/network.nft" "$backup/network.nft"; fi
    for unit in "${SERVICES[@]}" "$SERVICE_MIGRATE"; do [[ ! -f "$SYSTEMD_DIR/$unit.service" ]] || cp -p -- "$SYSTEMD_DIR/$unit.service" "$backup/"; done
    if [[ "$INSTALL_REDIS" == 1 ]]; then
        cp -p -- "${REDIS_CONFIG:-/etc/redis/redis.conf}" "$backup/redis.conf"
        if systemctl is-active --quiet redis-server; then redis_active=1; fi
        if systemctl is-enabled --quiet redis-server; then redis_enabled=1; fi
    fi
    prepare_postgres
    prepare_runtime
    replaced=1
    migrate_database
    bootstrap_admin
    render_units "$WORK/units"
    install -m 600 -o root -g root "$CANDIDATE" "$ENV_FILE.next"
    mv -f -- "$ENV_FILE.next" "$ENV_FILE"
    install -m 600 -o root -g root "$WORK/runtime.env" "$RUNTIME_ENV.next"
    mv -f -- "$RUNTIME_ENV.next" "$RUNTIME_ENV"
    if [[ "$APP_HOST" == 0.0.0.0 ]]; then install -m 600 "$WORK/network.nft" "$CONFIG_DIR/network.nft"; fi
    if [[ "$SAVE_DEFAULTS" == 1 ]]; then write_defaults "$INSTALL_CONF"; fi
    for unit in "${SERVICES[@]}" "$SERVICE_MIGRATE"; do install -m 644 "$WORK/units/$unit.service" "$SYSTEMD_DIR/"; done
    ln -s "$RELEASE" "$APP_ROOT/.current-next-$$"
    mv -Tf "$APP_ROOT/.current-next-$$" "$APP_ROOT/current"
    if [[ "$INSTALL_REDIS" == 1 ]]; then redis_touched=1; configure_redis; fi
    systemctl daemon-reload
    systemctl enable "${SERVICES[@]}"
    systemctl restart "${SERVICES[@]}"
    health_check
    link_layout_aliases
    trap - EXIT
    printf 'Versión activa: %s\nRespaldo: %s\nAcceso local: http://localhost:%s\n' "$RELEASE" "$backup" "$APP_PORT"
    printf 'Servicios: systemctl status %s %s %s\n' "$SERVICE_API" "$SERVICE_WORKER" "$SERVICE_WEB"
    if [[ "${FRESH:-0}" == 1 ]]; then printf 'Instalación nueva: base y cola independientes. Recursos anteriores conservados.\n'; fi
)

run_installation() {
    preflight
    if [[ "$ACTION" != repair && "$ACTION" != configure ]]; then
        apt-get update
        local -a packages=(ca-certificates curl git rsync python3 python3-venv python3-pip build-essential wipe xz-utils openssl)
        [[ "$INSTALL_REDIS" != 1 ]] || packages+=(redis-server)
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends --no-upgrade "${packages[@]}"
    fi
    if [[ "$APP_HOST" == 0.0.0.0 ]] && ! command -v nft >/dev/null; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nftables
    fi
    prepare_layout
    check_service_ports
    check_network_access
    if [[ "$ACTION" == repair || "$ACTION" == configure ]]; then prepare_repair; verify_release_code
    else resolve_source; fi
    prepare_environment
    ensure_oidc
    if [[ "$ACTION" != repair && "$ACTION" != configure ]]; then install_binaries; build_release; fi
    if [[ "$ACTION" != repair && "$ACTION" != configure ]]; then verify_release_code; fi
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
            --fresh) FRESH=1; shift ;;
            --admin-username) ADMIN_USERNAME="${2:?Falta usuario}"; shift 2 ;;
            --admin-password-file) ADMIN_PASSWORD_FILE="${2:?Falta archivo}"; export ADMIN_PASSWORD_FILE; shift 2 ;;
            --lan) APP_HOST=0.0.0.0; APP_ALLOWED_SUBNET=192.168.100.0/24; shift ;;
            --action) ACTION="${2:?Falta acción}"; shift 2 ;;
            --source-dir) SOURCE_DIR="${2:?Falta ruta}"; shift 2 ;;
            --root) APP_ROOT="${2:?Falta ruta}"; shift 2 ;;
            --port) APP_PORT="${2:?Falta puerto}"; shift 2 ;;
            --ref) APP_REF="${2:?Falta ref}"; shift 2 ;;
            --method) INSTALL_METHOD="${2:?Falta método}"; shift 2 ;;
            --help|-h) printf '%s\n' 'Uso: bash install-tld.sh [--action install|update|repair|configure|cancel] [--lan: solo 192.168.100.0/24] [--dry-run] [--yes] [--fresh] [--admin-username USUARIO] [--admin-password-file ARCHIVO] [--source-dir RUTA] [--root RUTA] [--port PUERTO] [--ref latest|TAG|COMMIT] [--method auto|source|release]'; return ;;
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
