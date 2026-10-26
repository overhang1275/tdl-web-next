from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from redis import Redis
from redis.exceptions import RedisError
from rq import Worker

from app.config import settings
from app.services import auth
from app.services.tdl import TdlService


class StatusService:
    def __init__(self, ttl: float = 10.0) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._cached: dict | None = None
        self._cached_at = 0.0

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None
            self._cached_at = 0.0

    def get(self, force: bool = False) -> dict:
        with self._lock:
            if (
                not force
                and self._cached is not None
                and time.monotonic() - self._cached_at < self.ttl
            ):
                return dict(self._cached)
        data = self._build()
        with self._lock:
            self._cached = data
            self._cached_at = time.monotonic()
        return dict(data)

    def _build(self) -> dict:
        tdl = TdlService()
        binary = tdl.binary
        tdl_installed = bool(shutil.which(binary)) or Path(binary).exists()
        try:
            session_active = tdl.is_logged_in()
            session_error = None
        except Exception as exc:  # tdl failures must not break the status page
            session_active = False
            session_error = str(exc)

        redis_connected = False
        redis_error = None
        worker_count = 0
        try:
            redis = Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            redis.ping()
            redis_connected = True
            worker_count = len(Worker.all(connection=redis))
        except (RedisError, Exception) as exc:
            redis_error = str(exc)

        return {
            "environment": settings.environment,
            "version": settings.app_version,
            "session_active": session_active,
            "session_error": session_error,
            "tdl_installed": tdl_installed,
            "tdl_binary": binary,
            "redis_connected": redis_connected,
            "redis_error": redis_error,
            "worker_connected": worker_count > 0,
            "worker_count": worker_count,
            "storage": str(tdl.storage_path),
            "can_start_services": settings.environment != "production",
            "authentik_configured": auth.configured(),
        }


status_service = StatusService()
