#!/usr/bin/env bash
# Shared by the native LXC installer and updater. Compose is managed separately.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ROOT="${APP_ROOT:-/opt/tld-web}"
APP_USER=telegramdl
ENV_FILE="${ENV_FILE:-/etc/telegram-downloader/telegram-downloader.env}"
NODE_VERSION="${NODE_VERSION:-24.19.0}"
TDL_VERSION="${TDL_VERSION:-0.20.4}"
SERVICES=(telegram-downloader-api telegram-downloader-worker telegram-downloader-web)
[[ $(id -u) == 0 ]] || { echo 'Ejecuta como root.' >&2; exit 1; }
[[ "$APP_ROOT" =~ ^/[A-Za-z0-9_./-]+$ && "$APP_ROOT" != / ]] || { echo 'APP_ROOT debe ser una ruta absoluta segura.' >&2; exit 1; }
env_value() { [[ -f "$ENV_FILE" ]] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 || true; }

install_binaries() {
    local node_arch tdl_arch temp archive
    case "$(uname -m)" in
        x86_64) node_arch=x64; tdl_arch=64bit ;;
        aarch64) node_arch=arm64; tdl_arch=arm64 ;;
        *) echo 'Se requiere x86_64 o arm64.' >&2; return 1 ;;
    esac
    temp="$(mktemp -d)"
    archive="node-v$NODE_VERSION-linux-$node_arch.tar.xz"
    curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/$archive" -o "$temp/$archive"
    curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt" -o "$temp/SHASUMS256.txt"
    (cd "$temp"; sha256sum --check --ignore-missing SHASUMS256.txt)
    mkdir -p "$APP_ROOT/node" "$APP_ROOT/bin"
    tar -xJf "$temp/$archive" --strip-components=1 -C "$APP_ROOT/node"
    if [[ ! -x "$(env_value TDL_BINARY)" ]]; then
        archive="tdl_Linux_$tdl_arch.tar.gz"
        curl -fsSL "https://github.com/iyear/tdl/releases/download/v$TDL_VERSION/$archive" -o "$temp/$archive"
        curl -fsSL "https://github.com/iyear/tdl/releases/download/v$TDL_VERSION/tdl_checksums.txt" -o "$temp/tdl_checksums.txt"
        (cd "$temp"; sha256sum --check --ignore-missing tdl_checksums.txt)
        tar -xzf "$temp/$archive" -C "$temp" tdl
        install -m 0755 "$temp/tdl" "$APP_ROOT/bin/tdl"
    fi
    rm -rf -- "$temp"
    "$APP_ROOT/node/bin/node" --version
    "$(env_value TDL_BINARY)" version
}

build_release() {
    RELEASE="$APP_ROOT/releases/$(date -u +%Y%m%dT%H%M%S)-$$"
    install -d -o "$APP_USER" -g "$APP_USER" "$RELEASE"
    rsync -a --exclude=.git --exclude='.venv*' --exclude=.superpowers --exclude=docs \
        --exclude=graphify-out --exclude=node_modules --exclude=.next --exclude='.env' \
        --exclude=data --exclude=test-results "$ROOT/" "$RELEASE/"
    python3 -m venv "$RELEASE/venv"
    "$RELEASE/venv/bin/pip" install -r "$RELEASE/backend/requirements.txt"
    mkdir -p "$RELEASE/frontend/public"
    chown -R "$APP_USER:$APP_USER" "$RELEASE"
    (
        cd "$RELEASE/frontend"
        runuser -u "$APP_USER" -- env PATH="$APP_ROOT/node/bin:$PATH" npm_config_cache="$RELEASE/.npm" "$APP_ROOT/node/bin/npm" ci --no-audit
        runuser -u "$APP_USER" -- env PATH="$APP_ROOT/node/bin:$PATH" npm_config_cache="$RELEASE/.npm" "$APP_ROOT/node/bin/npm" run build
    )
    cp -a "$RELEASE/frontend/.next/static" "$RELEASE/frontend/.next/standalone/.next/static"
    cp -a "$RELEASE/frontend/public" "$RELEASE/frontend/.next/standalone/public"
    chown -R root:"$APP_USER" "$RELEASE"
    chmod -R g+rX "$RELEASE"
    install -d -o "$APP_USER" -g "$APP_USER" "$RELEASE/frontend/.next/standalone/.next/cache"
}

activate_release() (
    local previous backup='' unit units_replaced=0
    local -a active_services=()
    previous="$(readlink -f "$APP_ROOT/current" 2>/dev/null || true)"
    for unit in "${SERVICES[@]}"; do
        if systemctl is-active --quiet "$unit"; then active_services+=("$unit"); fi
    done
    restore_previous() {
        local result=$1
        [[ "$result" == 0 ]] && return
        trap - EXIT
        systemctl stop "${SERVICES[@]}" || true
        if [[ "$units_replaced" == 1 ]]; then
            for unit in "${SERVICES[@]}"; do
                if [[ -f "$backup/$unit.service" ]]; then
                    cp "$backup/$unit.service" /etc/systemd/system/
                else
                    systemctl disable "$unit" || true
                    rm -f -- "/etc/systemd/system/$unit.service"
                fi
            done
        fi
        if [[ -n "$previous" && -d "$previous" ]]; then
            ln -sfn "$previous" "$APP_ROOT/current"
        elif [[ -L "$APP_ROOT/current" && "$(readlink "$APP_ROOT/current")" == "${RELEASE:-}" ]]; then
            rm -f -- "$APP_ROOT/current"
        fi
        systemctl daemon-reload
        if ((${#active_services[@]})); then systemctl start "${active_services[@]}" || true; fi
        echo "No se activó la versión. Se intentó recuperar los servicios anteriores. Respaldo: ${backup:-no creado}." >&2
        exit "$result"
    }
    trap 'restore_previous $?' EXIT
    systemctl stop telegram-downloader-web || true
    python3 "$ROOT/scripts/data-admin.py" check-idle --env "$ENV_FILE"
    systemctl stop telegram-downloader-api telegram-downloader-worker || true
    backup="$(python3 "$ROOT/scripts/data-admin.py" backup --env "$ENV_FILE")"
    for unit in "${SERVICES[@]}"; do
        if [[ -f "/etc/systemd/system/$unit.service" ]]; then cp "/etc/systemd/system/$unit.service" "$backup/"; fi
    done
    units_replaced=1
    for unit in "${SERVICES[@]}"; do
        sed "s|/opt/tld-web|$APP_ROOT|g;s|/etc/telegram-downloader/telegram-downloader.env|$ENV_FILE|g" \
            "$ROOT/deploy/systemd/$unit.service" > "/etc/systemd/system/$unit.service"
    done
    ln -sfn "$RELEASE" "$APP_ROOT/current"
    systemctl daemon-reload
    systemctl enable redis-server "${SERVICES[@]}"
    systemctl restart redis-server
    systemctl restart "${SERVICES[@]}"
    curl --fail --silent --retry 15 --retry-delay 2 --retry-connrefused http://127.0.0.1:8000/health
    curl --fail --silent --retry 15 --retry-delay 2 --retry-connrefused http://127.0.0.1:3000/login >/dev/null
    trap - EXIT
    echo "Versión activa: $RELEASE · Respaldo: $backup"
)
