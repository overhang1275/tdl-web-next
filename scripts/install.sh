#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/native-common.sh"
DOMAIN="${DOMAIN:-$(env_value DOMAIN)}"
if [[ -z "$DOMAIN" && -t 0 ]]; then read -r -p 'Dominio base para app.DOMINIO: ' DOMAIN; fi
[[ -n "$DOMAIN" ]] || { echo 'Usa: sudo DOMAIN=example.test bash scripts/install.sh' >&2; exit 2; }
apt-get update
apt-get install -y python3 python3-venv python3-pip redis-server nginx curl ca-certificates rsync git wipe xz-utils openssl
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_ROOT" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 0750 -o root -g "$APP_USER" "$APP_ROOT"
export APP_UID="$(id -u "$APP_USER")" APP_GID="$(id -g "$APP_USER")"
install -d -m 0750 /etc/telegram-downloader
python3 "$ROOT/scripts/configure-env.py" --deployment native --output "$ENV_FILE" --legacy "$ENV_FILE" --domain "$DOMAIN" --root "$APP_ROOT"
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"
for key in AUTHENTIK_ISSUER AUTHENTIK_CLIENT_ID AUTHENTIK_CLIENT_SECRET; do
    value="$(env_value "$key")"
    [[ -n "$value" && "$value" != replace-* && "$value" != change-* ]] || {
        echo "Configura $key en $ENV_FILE y vuelve a ejecutar el instalador. No se activaron servicios nuevos." >&2; exit 2;
    }
done
issuer="$(env_value AUTHENTIK_ISSUER)"
discovery="$(mktemp)"
curl --fail --silent --show-error "${issuer%/}/.well-known/openid-configuration" -o "$discovery"
python3 - "$discovery" "$issuer" <<'PY'
import json, sys
with open(sys.argv[1]) as source:
    metadata = json.load(source)
if metadata.get('issuer') != sys.argv[2]:
    raise SystemExit('AUTHENTIK_ISSUER debe coincidir exactamente con el issuer del discovery OIDC.')
PY
rm -f -- "$discovery"
for key in DATA_DIR TDL_SESSIONS_DIR EXPORTS_DIR DOWNLOADS_DIR LOGS_DIR; do
    dir="$(env_value "$key")"
    [[ "$dir" == /* && "$dir" != / ]] || { echo "Ruta insegura en $key" >&2; exit 1; }
    if [[ ! -d "$dir" ]]; then install -d -m 0750 -o "$APP_USER" -g "$APP_USER" "$dir"; fi
done
INGRESS="$(env_value NATIVE_INGRESS)"
[[ "$INGRESS" == tunnel || "$INGRESS" == direct || -z "$INGRESS" ]] || { echo 'NATIVE_INGRESS debe ser tunnel o direct.' >&2; exit 2; }
install_binaries
build_release
TLS_DIR="$(env_value TLS_DIR)"
APP_HOST="$(python3 -c 'import sys; from urllib.parse import urlparse; print(urlparse(sys.argv[1]).hostname)' "$(env_value AUTH_URL)")"
if [[ "$INGRESS" != tunnel ]]; then
install -d -m 0755 "$TLS_DIR"
if [[ ! -f "$TLS_DIR/fullchain.pem" && ! -f "$TLS_DIR/privkey.pem" ]]; then
    openssl req -x509 -nodes -newkey rsa:3072 -days 365 \
        -keyout "$TLS_DIR/privkey.pem" -out "$TLS_DIR/fullchain.pem" \
        -subj "/CN=$APP_HOST" -addext "subjectAltName=DNS:$APP_HOST" >/dev/null 2>&1
    chmod 600 "$TLS_DIR/privkey.pem"
    chmod 644 "$TLS_DIR/fullchain.pem"
    echo 'Certificado interno creado; instala su CA en los clientes o reemplaza ambos PEM por un certificado de confianza.'
fi
[[ -f "$TLS_DIR/fullchain.pem" && -f "$TLS_DIR/privkey.pem" ]] || { echo 'Falta el certificado o su clave TLS.' >&2; exit 1; }
fi
template="$ROOT/deploy/nginx/telegram-downloader.conf"
if [[ "$INGRESS" == tunnel ]]; then template="$ROOT/deploy/nginx/telegram-downloader-tunnel.conf"; fi
sed "s|@@APP_HOST@@|$APP_HOST|g;s|@@TLS_DIR@@|$TLS_DIR|g" \
    "$template" > /etc/nginx/sites-available/telegram-downloader
ln -sfn /etc/nginx/sites-available/telegram-downloader /etc/nginx/sites-enabled/telegram-downloader
nginx -t
activate_release
systemctl enable --now nginx
systemctl reload nginx
echo "Instalado sin contenedores: $(env_value AUTH_URL)"
echo "Configura en el proveedor OIDC el callback: $(env_value AUTH_URL)/api/auth/callback/authentik"
if [[ "$INGRESS" == tunnel ]]; then echo 'Cloudflare Tunnel (cloudflared en este LXC): Service URL http://127.0.0.1:8080'; fi
