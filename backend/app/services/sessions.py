"""Native sessions. Helpers flush but never commit.

Mutation lock order is User FOR UPDATE, then AuthSession FOR UPDATE. Account
reset/deactivation must use the same order, including before bulk revocation.
RefreshReplay is the one failure whose revocation the caller MUST commit.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import ValidationError
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthSession, User
from app.schemas import TokenPair, UserRead
from app.services.auth import AuthError

ISSUER = "tdl-console"
ACCESS_AUDIENCE = "tdl-api"
REFRESH_AUDIENCE = "tdl-refresh"
_redis = Redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)


class RefreshReplay(AuthError):
    def __init__(self) -> None:
        super().__init__("refresh_reused", "La sesión fue revocada.")


def _now() -> datetime:
    return datetime.now(UTC)


def _invalid() -> AuthError:
    return AuthError("invalid_session", "La sesión no es válida.")


def _unavailable() -> AuthError:
    return AuthError("auth_unavailable", "La autenticación no está disponible temporalmente.", 503)


def _private_key():
    try:
        key = serialization.load_pem_private_key(settings.jwt_private_key_file.read_bytes(), password=None)
        if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
            raise ValueError
        return key
    except (OSError, ValueError, TypeError):
        raise _unavailable() from None


def _public_key():
    try:
        key = serialization.load_pem_public_key(settings.jwt_public_key_file.read_bytes())
        if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
            raise ValueError
        return key
    except (OSError, ValueError, TypeError):
        raise _unavailable() from None


def _cipher() -> Fernet:
    private = _private_key().private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"tdl-console/rotation-cache/v1").derive(private)
    return Fernet(base64.urlsafe_b64encode(key))


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _decode(token: str, *, refresh: bool = False) -> dict:
    if not isinstance(token, str) or len(token) > 4096:
        raise _invalid()
    try:
        claims = jwt.decode(
            token, _public_key(), algorithms=["RS256"], issuer=ISSUER,
            audience=REFRESH_AUDIENCE if refresh else ACCESS_AUDIENCE,
            options={"require": ["iss", "aud", "sub", "sid", "iat", "exp", "token_use"]},
        )
        for name in ("sub", "sid", "fid") if refresh else ("sub", "sid"):
            if not isinstance(claims[name], str):
                raise ValueError
            UUID(claims[name])
        if claims["token_use"] != ("refresh" if refresh else "access"):
            raise ValueError
        if any(type(claims[k]) is not int for k in ("iat", "exp")):
            raise ValueError
        if refresh:
            if type(claims["gen"]) is not int or claims["gen"] < 0 or not isinstance(claims["jti"], str) or len(claims["jti"]) < 43:
                raise ValueError
        return claims
    except jwt.ExpiredSignatureError:
        raise AuthError("token_expired", "La sesión expiró.") from None
    except jwt.InvalidAudienceError:
        raise AuthError("invalid_audience", "Token inválido.") from None
    except jwt.InvalidIssuerError:
        raise AuthError("invalid_issuer", "Token inválido.") from None
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise _invalid() from None


def _lock_user(db: Session, user_id: UUID) -> User:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if user is None:
        raise _invalid()
    return user


def _lock_session(db: Session, session_id: UUID, user_id: UUID | None = None) -> tuple[User, AuthSession]:
    if user_id is None:
        user_id = db.scalar(select(AuthSession.user_id).where(AuthSession.id == session_id))
    if user_id is None:
        raise _invalid()
    user = _lock_user(db, user_id)
    row = db.scalar(select(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user.id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise _invalid()
    return user, row


def _check_active(user: User, row: AuthSession, now: datetime) -> None:
    if not user.active or row.revoked_at is not None or now >= row.absolute_expires_at or now >= row.idle_expires_at:
        raise _invalid()


def _identity(user: User, row: AuthSession, expires_at: int) -> UserRead:
    return UserRead(id=user.id, session_id=row.id, username=user.username, name=user.display_name,
                    expires_at=datetime.fromtimestamp(expires_at, UTC), must_change_password=user.must_change_password)


def _pair(user: User, row: AuthSession, now: datetime) -> TokenPair:
    key = _private_key()
    issued = int(now.timestamp())
    deadline = int(min(now + timedelta(seconds=300), row.absolute_expires_at, row.idle_expires_at).timestamp())
    common = {"iss": ISSUER, "sub": str(user.id), "sid": str(row.id), "iat": issued}
    access = jwt.encode({**common, "aud": ACCESS_AUDIENCE, "exp": deadline, "token_use": "access"}, key, algorithm="RS256")
    refresh = jwt.encode({**common, "aud": REFRESH_AUDIENCE, "exp": int(row.absolute_expires_at.timestamp()),
                          "token_use": "refresh", "fid": str(row.family_id), "gen": row.generation,
                          "jti": secrets.token_urlsafe(32)}, key, algorithm="RS256")
    return TokenPair(access_token=access, refresh_token=refresh, expires_at=deadline, session_id=row.id,
                     must_change_password=user.must_change_password, user=_identity(user, row, deadline))


def issue_session(db: Session, user: User) -> TokenPair:
    user = _lock_user(db, user.id)
    if not user.active:
        raise _invalid()
    now = _now()
    row = AuthSession(id=uuid4(), user_id=user.id, family_id=uuid4(), generation=0,
                      created_at=now, last_activity_at=now, absolute_expires_at=now + timedelta(seconds=28800),
                      idle_expires_at=now + timedelta(seconds=1800))
    result = _pair(user, row, now)
    row.refresh_token_hash = _hash(result.refresh_token)
    db.add(row)
    db.flush()
    return result


def verify_session(db: Session, token: str) -> UserRead:
    claims = _decode(token)
    result = db.execute(select(User, AuthSession).join(AuthSession, AuthSession.user_id == User.id)
                        .where(User.id == UUID(claims["sub"]), AuthSession.id == UUID(claims["sid"]))
                        .execution_options(populate_existing=True)).first()
    if result is None:
        raise _invalid()
    user, row = result
    _check_active(user, row, _now())
    return _identity(user, row, claims["exp"])


def rotate_session(db: Session, refresh_token: str) -> TokenPair:
    claims = _decode(refresh_token, refresh=True)
    user, row = _lock_session(db, UUID(claims["sid"]), UUID(claims["sub"]))
    now = _now()  # Read after waiting for locks, never extend from request arrival.
    _check_active(user, row, now)
    if claims["fid"] != str(row.family_id):
        raise _invalid()
    digest = _hash(refresh_token)
    cache_key = f"{settings.auth_rotation_prefix}:{row.id}:{digest}"
    if claims["gen"] == row.generation and secrets.compare_digest(digest, row.refresh_token_hash):
        row.previous_refresh_token_hash = digest
        row.generation += 1
        row.rotated_at = now
        result = _pair(user, row, now)
        row.refresh_token_hash = _hash(result.refresh_token)
        db.flush()
        encrypted = _cipher().encrypt(json.dumps({"generation": row.generation, "rotated_at": now.timestamp(), "pair": result.model_dump(mode="json")}).encode())
        try:
            # A rollback can leave this entry behind. Readers must check committed
            # generation AND current hash while holding the same database lock.
            _redis.set(cache_key, encrypted, ex=5)
        except RedisError:
            raise _unavailable() from None
        return result
    if claims["gen"] >= row.generation:
        raise _invalid()  # Forged/uncommitted generation must never revoke a family.
    try:
        encrypted = _redis.get(cache_key)
    except RedisError:
        raise _unavailable() from None
    if encrypted is not None:
        try:
            cached = json.loads(_cipher().decrypt(encrypted))
            pair = TokenPair.model_validate(cached["pair"])
            if now.timestamp() < cached["rotated_at"] + 5:
                if (cached["generation"] == row.generation and pair.session_id == row.id
                        and secrets.compare_digest(_hash(pair.refresh_token), row.refresh_token_hash)):
                    return pair
                raise AuthError("refresh_superseded", "Otra petición ya renovó la sesión. Reintenta.", 409)
        except (InvalidToken, ValueError, KeyError, TypeError, ValidationError):
            raise _unavailable() from None
    if row.rotated_at is not None and now < row.rotated_at + timedelta(seconds=5):
        # Eviction during rapid rotations cannot distinguish a legitimate old
        # retry. Fail closed transiently, without issuing tokens or revoking.
        raise _unavailable()
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.family_id == row.family_id,
                                        AuthSession.revoked_at.is_(None)).values(revoked_at=now))
    db.flush()
    raise RefreshReplay()


def revoke_session(db: Session, session_id: UUID) -> None:
    _, row = _lock_session(db, session_id)
    if row.revoked_at is None:
        row.revoked_at = _now()
        db.flush()


def revoke_refresh_session(db: Session, refresh_token: str) -> None:
    """Logout proof only: no renewal, Redis access, or requirement for live access.

    A signed older generation proves ownership for revocation, never issuance.
    An unconfirmed future/current-hash token is not accepted as logout proof.
    """
    claims = _decode(refresh_token, refresh=True)
    _, row = _lock_session(db, UUID(claims["sid"]), UUID(claims["sub"]))
    if (claims["fid"] != str(row.family_id) or claims["gen"] > row.generation
            or (claims["gen"] == row.generation and not secrets.compare_digest(_hash(refresh_token), row.refresh_token_hash))):
        raise _invalid()
    if row.revoked_at is None:
        row.revoked_at = _now()
        db.flush()


def revoke_all_sessions(db: Session, user_id: UUID) -> None:
    _lock_user(db, user_id)
    db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)).values(revoked_at=_now()))
    db.flush()


def record_activity(db: Session, session_id: UUID) -> None:
    user, row = _lock_session(db, session_id)
    now = _now()
    _check_active(user, row, now)
    if now >= row.last_activity_at + timedelta(seconds=60):
        row.last_activity_at = now
        row.idle_expires_at = min(now + timedelta(seconds=1800), row.absolute_expires_at)
        db.flush()
