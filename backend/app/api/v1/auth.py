from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.errors import ApiError
from app.database import get_db
from app.schemas import (
    ExchangeRequest,
    LocalLoginRequest,
    PasswordChange,
    RefreshRequest,
    TokenPair,
    UserRead,
)
from app.services.accounts import change_password, verify_credentials
from app.services.audit import audit
from app.services.auth import AuthError
from app.services.oidc import exchange_authentik
from app.services.sessions import (
    RefreshReplay,
    issue_session,
    record_activity,
    revoke_all_sessions,
    revoke_refresh_session,
    revoke_session,
    rotate_session,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _transaction[T](db: Session, action: Callable[[], T], *, failure_action=None, actor_id=None, target_id=None) -> T:
    try:
        result = action()
        db.commit()
        return result
    except RefreshReplay as exc:
        # Replay invalidates the family even though this request returns 401.
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        raise ApiError(exc.code, exc.message, exc.status_code) from None
    except AuthError as exc:
        db.rollback()
        if failure_action is not None:
            audit(db, actor_id, failure_action, target_id, "failure")
            db.commit()
        raise ApiError(exc.code, exc.message, exc.status_code) from None
    except Exception:
        db.rollback()
        raise


@router.post("/token", response_model=TokenPair)
def token(body: LocalLoginRequest, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    response.headers["Cache-Control"] = "no-store"

    def issue() -> TokenPair:
        # Deliberately conservative: all internal callers share the limit.
        # ASGI proxy middleware may rewrite client.host using forwarded headers.
        user = verify_credentials(db, body.username, body.password, origin="internal-web")
        pair = issue_session(db, user)  # Same transaction and user lock as verification.
        audit(db, user.id, "auth.login", user.id, "success")
        return pair

    try:
        return _transaction(db, issue)
    except ApiError as exc:
        audit(db, None, "auth.login", None, "failure" if exc.status_code == 401 else "rejected")
        db.commit()
        raise


@router.post("/refresh", response_model=TokenPair)
def refresh(body: RefreshRequest, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    response.headers["Cache-Control"] = "no-store"
    return _transaction(db, lambda: rotate_session(db, body.refresh_token))


@router.post("/exchange", response_model=TokenPair)
def exchange(body: ExchangeRequest, response: Response, db: Session = Depends(get_db)) -> TokenPair:
    response.headers["Cache-Control"] = "no-store"
    def issue():
        pair = exchange_authentik(db, body.access_token)
        audit(db, pair.user.id, "auth.exchange", pair.user.id, "success")
        return pair
    return _transaction(db, issue, failure_action="auth.exchange")


@router.post("/logout", status_code=204)
def logout(request: Request, body: RefreshRequest | None = None, db: Session = Depends(get_db)) -> None:
    def revoke() -> None:
        if body is not None:
            revoke_refresh_session(db, body.refresh_token)
        else:
            user = get_current_user(request, db)
            revoke_session(db, user.session_id)

    _transaction(db, revoke)


@router.post("/activity", status_code=204)
def activity(user: UserRead = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    _transaction(db, lambda: record_activity(db, user.session_id))


@router.post("/revoke-all", status_code=204)
def revoke_all(user: UserRead = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    def revoke():
        revoke_all_sessions(db, user.id)
        audit(db, user.id, "auth.revoke_all", user.id, "success")
    _transaction(db, revoke)


@router.post("/change-password", status_code=204)
def change(body: PasswordChange, user: UserRead = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    def update():
        change_password(db, user.id, body.current_password, body.new_password)
        audit(db, user.id, "auth.change_password", user.id, "success")
    _transaction(db, update, failure_action="auth.change_password", actor_id=user.id, target_id=user.id)


@router.get("/me", response_model=UserRead)
def me(user: UserRead = Depends(get_current_user)) -> UserRead:
    return user
