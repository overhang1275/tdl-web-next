"""Prepare native or Docker configuration without changing existing data paths."""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shlex
import tempfile
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip()
        if value.startswith(('"', "'")):
            parts = shlex.split(value, comments=False)
            if len(parts) != 1:
                raise ValueError(f'Invalid quoted value for {key}')
            value = parts[0]
        values[key.strip()] = value
    return values


def encode_value(value: str) -> str:
    if any(char in value for char in '\n\r\0'):
        raise ValueError('Environment values must fit on one line')
    if any(char.isspace() or char in '\\"\'' for char in value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value


def configure(output: Path, domain: str, legacy: Path, root: Path, deployment: str = "docker",
              native_options: dict | None = None) -> None:
    if not re.fullmatch(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", domain):
        raise ValueError("DOMAIN must be a hostname without a scheme, path or port")
    existing = read_env(output)
    old = read_env(legacy)
    data = existing.get("DATA_DIR") or old.get("DATA_DIR") or str(root / "data")
    if not Path(data).is_absolute():
        raise ValueError("DATA_DIR must be absolute")
    paths = {"DATA_DIR": data, "TDL_SESSIONS_DIR": f"{data}/sessions", "EXPORTS_DIR": f"{data}/exports",
             "DOWNLOADS_DIR": f"{data}/downloads", "LOGS_DIR": f"{data}/logs",
             "DATABASE_URL": f"sqlite:///{data}/telegram_downloader.sqlite3"}
    values = {**paths, "DOMAIN": domain, "AUTH_URL": f"https://app.{domain}",
              "AUTHENTIK_ISSUER": f"https://auth.{domain}/application/o/tdl-console/",
              "AUTHENTIK_JWKS_URL": f"https://auth.{domain}/application/o/tdl-console/jwks/",
              "AUTHENTIK_CLIENT_ID": "tdl-console", "TLS_DIR": "/etc/telegram-downloader/certs",
              "AUTHENTIK_BOOTSTRAP_EMAIL": f"admin@{domain}", "TDL_NAMESPACE": "default",
              "COMMAND_TIMEOUT_SECONDS": "7200", "DOWNLOAD_BATCH_SIZE": "100",
              "DOWNLOAD_IDLE_TIMEOUT_SECONDS": "600", "EXPORT_BATCH_SIZE": "5000"}
    for name in (*paths, "TDL_NAMESPACE", "COMMAND_TIMEOUT_SECONDS", "DOWNLOAD_BATCH_SIZE",
                 "DOWNLOAD_IDLE_TIMEOUT_SECONDS", "EXPORT_BATCH_SIZE"):
        if old.get(name):
            values[name] = old[name]
    secret_names = ("AUTH_SECRET", "AUTHENTIK_CLIENT_SECRET", "AUTHENTIK_SECRET_KEY", "AUTHENTIK_BOOTSTRAP_PASSWORD", "PG_PASS")
    if deployment == "native":
        for name in ("AUTHENTIK_BOOTSTRAP_EMAIL",):
            values.pop(name, None)
        values.update({"APP_ENV": "production", "API_INTERNAL_URL": "http://127.0.0.1:8000",
                       "NATIVE_INGRESS": os.getenv("NATIVE_INGRESS", "direct"),
                       "REDIS_URL": "redis://127.0.0.1:6379/1", "TRUSTED_HOSTS": "127.0.0.1,localhost",
                       "TDL_BINARY": str(root / "bin" / "tdl"), "AUTHENTIK_ADMIN_GROUP": "tdl-admin"})
        for name in ("AUTHENTIK_ISSUER", "AUTHENTIK_CLIENT_ID", "AUTHENTIK_CLIENT_SECRET", "AUTHENTIK_JWKS_URL"):
            values[name] = os.getenv(name, old.get(name, ""))
        values["AUTH_URL"] = os.getenv("AUTH_URL", values["AUTH_URL"])
        secret_names = ("AUTH_SECRET",)
    for name in secret_names:
        values[name] = secrets.token_hex(32)
    for name in ("APP_UID", "APP_GID"):
        values[name] = os.getenv(name, "10001")
    values = {**values, **(old if deployment == "native" else {}), **existing}
    if deployment == "native" and native_options:
        allowed = {"APP_ROOT", "APP_HOST", "APP_PORT", "API_PORT", "APP_USER", "INSTALL_REDIS",
                   "PUBLIC_URL", "AUTH_URL", "REDIS_URL", "CONFIG_DIR", "BACKUPS_DIR", "LOGS_DIR",
                   "SERVICE_WEB", "SERVICE_API", "SERVICE_WORKER", "NODE_BINARY", "TDL_BINARY", "RESOLVED_METHOD"}
        for name, value in native_options.items():
            if name in allowed:
                value = str(value)
                if any(char in value for char in '\n\r\0'):
                    raise ValueError(f"Invalid multiline value for {name}")
                values[name] = value
        values["API_INTERNAL_URL"] = f"http://127.0.0.1:{values.get('API_PORT', '8000')}"
        values["APP_VERSION"] = native_options.get("RESOLVED_VERSION", "local")
        if not old.get("LOGS_DIR") and not existing.get("LOGS_DIR"):
            values["LOGS_DIR"] = str(root / "logs")
        values["TMP_DIR"] = str(root / "tmp")
        for name in ('AUTHENTIK_ISSUER', 'AUTHENTIK_CLIENT_ID', 'AUTHENTIK_CLIENT_SECRET'):
            if os.environ.get(name):
                values[name] = os.environ[name]
    if deployment == "native":
        values["AUTHENTIK_AUDIENCE"] = values.get("AUTHENTIK_AUDIENCE") or values["AUTHENTIK_CLIENT_ID"]
    elif values["DATABASE_URL"].startswith("sqlite:///"):
        values["DATABASE_DIR"] = str(Path(values["DATABASE_URL"].removeprefix("sqlite:///")).parent)
    if not (deployment == "native" and native_options):
        values["APP_VERSION"] = os.getenv("APP_VERSION", existing.get("APP_VERSION", "local"))
    for name in secret_names:
        if not values[name] or values[name].startswith(("replace-", "change-")):
            values[name] = secrets.token_hex(32)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.env-', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write("".join(f"{key}={encode_value(str(value))}\n" for key, value in values.items()))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain", default="localhost")
    parser.add_argument("--native-options", type=Path)
    parser.add_argument("--legacy", type=Path, default=Path("/etc/telegram-downloader/telegram-downloader.env"))
    parser.add_argument("--root", type=Path, default=Path("/opt/tld-web"))
    parser.add_argument("--deployment", choices=["native", "docker"], default="docker")
    args = parser.parse_args()
    import json

    options = json.loads(args.native_options.read_text()) if args.native_options else None
    configure(args.output, args.domain, args.legacy, args.root, args.deployment, options)
