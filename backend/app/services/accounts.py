from __future__ import annotations

import hashlib
import re
import secrets
from threading import BoundedSemaphore
from uuid import UUID

from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.services.auth import AuthError

# Two 64 MiB hashes leave memory for the API inside its 512 MiB limit (one worker).
_hash_slots = BoundedSemaphore(2)
_hasher = PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)
_redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)


def canonical_username(username: str) -> str:
    if not isinstance(username, str) or not re.fullmatch(r"[a-zA-Z0-9._-]{3,64}", username):
        raise ValueError("Username must contain 3–64 ASCII letters, digits, dots, underscores or hyphens.")
    return username.lower()


def _valid_password(password: str) -> bool:
    return isinstance(password, str) and 12 <= len(password) <= 128


def _hash_password(password: str) -> str:
    with _hash_slots:
        return _hasher.hash(password)


def hash_password(password: str) -> str:
    if not _valid_password(password):
        raise ValueError("Password must contain 12–128 characters.")
    return _hash_password(password)


# Random per process; unknown users still pay the same Argon2 verification cost.
_dummy_hash = _hash_password(secrets.token_urlsafe(32))


def create_local_user(db: Session, username: str, password: str, *, must_change_password: bool = False) -> User:
    username = canonical_username(username)
    password_hash = hash_password(password)
    user = User(username=username, password_hash=password_hash, must_change_password=must_change_password)
    try:
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise AuthError("username_unavailable", "El nombre de usuario no está disponible.", 409) from None
    return user


def lock_user(db: Session, user_id: UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if user is None:
        raise AuthError("user_not_found", "La cuenta no existe.", 404)
    return user


def lock_administration(db: Session) -> None:
    # ASCII TDLADMIN: serialize counts BEFORE taking any User/Session lock.
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 0x54444C41444D494E})


def update_user(db: Session, user_id: UUID, **changes) -> User:
    from app.services.sessions import revoke_all_sessions

    lock_administration(db)
    user = lock_user(db, user_id)
    if changes.get("active") is False and user.active and user.password_hash is not None:
        count = db.scalar(select(func.count()).select_from(User).where(User.active.is_(True), User.password_hash.is_not(None)))
        if count <= 1:
            raise AuthError("last_local_admin", "Debe quedar un administrador local activo.", 409)
    for name, value in changes.items():
        if name not in {"active", "display_name"}:
            raise ValueError("Unsupported account field")
        setattr(user, name, value)
    db.flush()  # revoke_all refreshes the locked User; never lose pending edits.
    if changes.get("active") is False:
        revoke_all_sessions(db, user.id)
    return user


def reset_password(db: Session, user_id: UUID, password: str, *, temporary: bool = True) -> User:
    from app.services.sessions import revoke_all_sessions

    password_hash = hash_password(password)
    user = lock_user(db, user_id)
    if user.password_hash is None:
        raise AuthError("external_account", "La cuenta utiliza un proveedor externo.", 409)
    user.password_hash = password_hash
    user.must_change_password = temporary
    db.flush()
    revoke_all_sessions(db, user.id)
    return user


def change_password(db: Session, user_id: UUID, current_password: str, new_password: str) -> None:
    user = lock_user(db, user_id)
    # Reuse the bounded verifier and limiter, without an intervening commit.
    verify_credentials(db, user.username, current_password, origin="internal-web")
    reset_password(db, user.id, new_password, temporary=False)


# Reserve before hashing so parallel failures cannot all pass an unlocked check.
# Epochs prevent a late success from decrementing a newer, expired/recreated window.
_RESERVE = """
for i = 1, 2 do
    if tonumber(redis.call('HGET', KEYS[i], 'count') or '0') >= tonumber(ARGV[i]) then
        return {}
    end
end
local epochs = {}
for i = 1, 2 do
    if redis.call('EXISTS', KEYS[i]) == 0 then
        redis.call('HSET', KEYS[i], 'epoch', ARGV[3])
        redis.call('EXPIRE', KEYS[i], 900)
    end
    redis.call('HINCRBY', KEYS[i], 'count', 1)
    epochs[i] = redis.call('HGET', KEYS[i], 'epoch')
end
return epochs
"""
_RELEASE = """
for i = 1, 2 do
    if redis.call('HGET', KEYS[i], 'epoch') == ARGV[i] then
        if redis.call('HINCRBY', KEYS[i], 'count', -1) == 0 then
            redis.call('DEL', KEYS[i])
        end
    end
end
return 1
"""


def _rate_keys(username: str, origin: str) -> list[str]:
    return [f"{settings.auth_rate_limit_prefix}:{kind}:{hashlib.sha256(value.encode()).hexdigest()}"
            for kind, value in (("account", username), ("origin", origin))]


def _invalid_credentials() -> AuthError:
    return AuthError("invalid_credentials", "Usuario o contraseña incorrectos.")


def verify_credentials(db: Session, username: str, password: str, *, origin: str) -> User:
    """Origin is a trusted server/peer identifier, never a freely supplied client IP.

    Keep this caller-owned transaction open through issue_session and commit both
    together: reset/deactivation needs this same user row lock before revocation.
    """
    try:
        canonical = canonical_username(username)
    except ValueError:
        canonical = ""  # Invalid names share a bucket and never become real users.
    keys = _rate_keys(canonical, origin)
    try:
        epochs = _redis.eval(_RESERVE, 2, *keys, 5, 30, secrets.token_hex(16))
    except RedisError:
        raise AuthError("auth_unavailable", "No se puede iniciar sesión en este momento.", 503) from None
    if not epochs:
        raise AuthError("login_rate_limited", "Demasiados intentos. Inténtalo más tarde.", 429)
    if not _valid_password(password):
        raise _invalid_credentials()
    user = db.scalar(select(User).where(User.username == canonical).with_for_update().execution_options(populate_existing=True))
    password_hash = user.password_hash if user is not None and user.password_hash else _dummy_hash
    try:
        with _hash_slots:
            verified = _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        verified = False
    if not verified or user is None or not user.active or user.password_hash is None:
        raise _invalid_credentials()
    try:
        _redis.eval(_RELEASE, 2, *keys, *epochs)
    except RedisError:
        raise AuthError("auth_unavailable", "No se puede iniciar sesión en este momento.", 503) from None
    return user
