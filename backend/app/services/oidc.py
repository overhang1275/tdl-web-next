"""External sign-in only; protected API requests always use native TDL sessions.

Helpers flush without committing. External group removal requires manual TDL
session revocation or waiting at most the eight-hour absolute session lifetime.
"""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ExternalIdentity, User
from app.schemas import TokenPair
from app.services.auth import AuthError, verify_authentik_token
from app.services.sessions import issue_session


def exchange_authentik(db: Session, access_token: str) -> TokenPair:
    claims = verify_authentik_token(access_token)
    lookup = select(ExternalIdentity).where(
        ExternalIdentity.issuer == claims["iss"], ExternalIdentity.subject == claims["sub"],
    )
    identity = db.scalar(lookup)
    if identity is None:
        try:
            # Roll back both inserts if another first login wins the identity key.
            with db.begin_nested():
                name = claims.get("name")
                user = User(
                    username=f"ext_{uuid4().hex}",
                    display_name=name[:255] if isinstance(name, str) and "\x00" not in name else None,
                )
                db.add(user)
                db.flush()
                identity = ExternalIdentity(user_id=user.id, issuer=claims["iss"], subject=claims["sub"])
                db.add(identity)
                db.flush()
        except IntegrityError as exc:
            if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != "uq_external_identities_issuer_subject":
                raise
            identity = db.scalar(lookup.execution_options(populate_existing=True))
            if identity is None:
                raise AuthError("auth_unavailable", "La autenticación no está disponible temporalmente.", 503) from None
    # Match native credential verification: User lock persists through issuance.
    user = db.scalar(select(User).where(User.id == identity.user_id).with_for_update().execution_options(populate_existing=True))
    if user is None or not user.active:
        raise AuthError("forbidden", "No tienes acceso a esta aplicación.", 403)
    return issue_session(db, user)
