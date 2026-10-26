"""Prepare native or Docker configuration without changing existing data paths."""
from __future__ import annotations

import argparse
import os
import re
import secrets
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {key.strip(): value.strip().strip("\"'") for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#") and "=" in line
            for key, value in [line.split("=", 1)]}


def configure(output: Path, domain: str, legacy: Path, root: Path, deployment: str = "docker") -> None:
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
    if deployment == "native":
        values["AUTHENTIK_AUDIENCE"] = values.get("AUTHENTIK_AUDIENCE") or values["AUTHENTIK_CLIENT_ID"]
    elif values["DATABASE_URL"].startswith("sqlite:///"):
        values["DATABASE_DIR"] = str(Path(values["DATABASE_URL"].removeprefix("sqlite:///")).parent)
    values["APP_VERSION"] = os.getenv("APP_VERSION", existing.get("APP_VERSION", "local"))
    for name in secret_names:
        if not values[name] or values[name].startswith(("replace-", "change-")):
            values[name] = secrets.token_hex(32)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
    output.chmod(0o600)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--legacy", type=Path, default=Path("/etc/telegram-downloader/telegram-downloader.env"))
    parser.add_argument("--root", type=Path, default=Path("/opt/tld-web"))
    parser.add_argument("--deployment", choices=["native", "docker"], default="docker")
    args = parser.parse_args()
    configure(args.output, args.domain, args.legacy, args.root, args.deployment)
