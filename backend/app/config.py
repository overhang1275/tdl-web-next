from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: Path = Path(".env"), *, override: bool = False) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if override:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)


load_env_file()


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name: str = "TDL Console"
    app_version: str
    environment: str
    database_url: str
    redis_url: str
    base_dir: Path
    sessions_dir: Path
    exports_dir: Path
    downloads_dir: Path
    logs_dir: Path
    tdl_binary: str
    tdl_namespace: str
    command_timeout_seconds: int
    authentik_issuer: str
    authentik_audience: str
    authentik_jwks_url: str
    authentik_admin_group: str
    trusted_hosts: list[str]
    enable_docs: bool

    def __init__(self) -> None:
        self.app_version = os.getenv("APP_VERSION", "1.0.0")
        self.environment = os.getenv("APP_ENV", "development")
        self.base_dir = Path(os.getenv("DATA_DIR", "./data")).resolve()
        self.sessions_dir = Path(
            os.getenv("TDL_SESSIONS_DIR", self.base_dir / "sessions")
        ).resolve()
        self.exports_dir = Path(os.getenv("EXPORTS_DIR", self.base_dir / "exports")).resolve()
        self.downloads_dir = Path(os.getenv("DOWNLOADS_DIR", self.base_dir / "downloads")).resolve()
        self.logs_dir = Path(os.getenv("LOGS_DIR", self.base_dir / "logs")).resolve()
        self.database_url = os.getenv(
            "DATABASE_URL", f"sqlite:///{self.base_dir / 'telegram_downloader.sqlite3'}"
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.tdl_binary = os.getenv("TDL_BINARY", "tdl")
        self.tdl_namespace = os.getenv("TDL_NAMESPACE", "default")
        self.command_timeout_seconds = int(os.getenv("COMMAND_TIMEOUT_SECONDS", "7200"))
        self.download_batch_size = max(1, int(os.getenv("DOWNLOAD_BATCH_SIZE", "100")))
        self.download_idle_timeout_seconds = max(
            1, int(os.getenv("DOWNLOAD_IDLE_TIMEOUT_SECONDS", "600"))
        )
        self.export_batch_size = max(1, int(os.getenv("EXPORT_BATCH_SIZE", "5000")))
        self.authentik_issuer = os.getenv("AUTHENTIK_ISSUER", "").strip()
        self.authentik_audience = os.getenv("AUTHENTIK_AUDIENCE", "").strip()
        self.authentik_jwks_url = os.getenv("AUTHENTIK_JWKS_URL", "").strip()
        if not self.authentik_jwks_url and self.authentik_issuer:
            self.authentik_jwks_url = f"{self.authentik_issuer.rstrip('/')}/jwks/"
        self.authentik_admin_group = os.getenv("AUTHENTIK_ADMIN_GROUP", "").strip()
        self.trusted_hosts = [
            host.strip() for host in os.getenv("TRUSTED_HOSTS", "*").split(",") if host.strip()
        ] or ["*"]
        self.enable_docs = _bool("ENABLE_DOCS", self.environment != "production")

    def validate(self) -> None:
        if os.getenv("DEPLOYMENT_MODE") == "docker" and self.database_url.startswith("sqlite:///"):
            database_dir = Path(self.database_url.removeprefix("sqlite:///")).resolve().parent
            mounted_dir = Path(os.getenv("DATABASE_DIR", str(self.base_dir))).resolve()
            if database_dir != mounted_dir:
                raise RuntimeError("DATABASE_DIR must match the SQLite directory mounted by Docker")
        if self.environment != "production":
            return
        if not self.authentik_issuer or not self.authentik_audience or not self.authentik_jwks_url:
            raise RuntimeError(
                "AUTHENTIK_ISSUER, AUTHENTIK_AUDIENCE and AUTHENTIK_JWKS_URL are required "
                "in production"
            )

    def ensure_directories(self) -> None:
        for path in (
            self.base_dir,
            self.sessions_dir,
            self.exports_dir,
            self.downloads_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for path in (self.base_dir, self.sessions_dir, self.exports_dir, self.logs_dir):
            try:
                path.chmod(0o700)
            except OSError:
                pass

    @staticmethod
    def apply_umask() -> None:
        os.umask(0o077)


settings = Settings()
