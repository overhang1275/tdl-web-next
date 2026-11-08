from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.v1.auth import _transaction
from app.database import get_db
from app.models import User
from app.schemas import (
    LocalUserRead,
    ManagedUserRead,
    PasswordReset,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.accounts import create_local_user, reset_password, update_user
from app.services.audit import audit
from app.services.sessions import revoke_all_sessions

router = APIRouter(prefix="/users", tags=["users"])


def public(user: User) -> ManagedUserRead:
    return ManagedUserRead(**LocalUserRead.model_validate(user).model_dump(), is_local=user.password_hash is not None)


@router.get("", response_model=list[ManagedUserRead])
def list_users(db: Session = Depends(get_db), actor: UserRead = Depends(get_current_user)):
    return [public(user) for user in db.scalars(select(User).order_by(User.username))]


@router.post("", response_model=ManagedUserRead, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), actor: UserRead = Depends(get_current_user)):
    def create():
        user = create_local_user(db, body.username, body.password, must_change_password=True)
        user.display_name = body.display_name
        db.flush()
        audit(db, actor.id, "user.create", user.id, "success")
        return public(user)
    return _transaction(db, create, failure_action="user.create", actor_id=actor.id)


@router.patch("/{user_id}", response_model=ManagedUserRead)
def patch_user(user_id: UUID, body: UserUpdate, db: Session = Depends(get_db), actor: UserRead = Depends(get_current_user)):
    def update():
        user = update_user(db, user_id, **body.model_dump(exclude_unset=True))
        audit(db, actor.id, "user.update", user.id, "success")
        return public(user)
    return _transaction(db, update, failure_action="user.update", actor_id=actor.id, target_id=user_id)


@router.post("/{user_id}/reset-password", status_code=204)
def reset_user_password(user_id: UUID, body: PasswordReset, db: Session = Depends(get_db), actor: UserRead = Depends(get_current_user)):
    def reset():
        reset_password(db, user_id, body.password)
        audit(db, actor.id, "user.reset_password", user_id, "success")
    _transaction(db, reset, failure_action="user.reset_password", actor_id=actor.id, target_id=user_id)


@router.post("/{user_id}/revoke-sessions", status_code=204)
def revoke_user_sessions(user_id: UUID, db: Session = Depends(get_db), actor: UserRead = Depends(get_current_user)):
    def revoke():
        revoke_all_sessions(db, user_id)
        audit(db, actor.id, "user.revoke_sessions", user_id, "success")
    _transaction(db, revoke, failure_action="user.revoke_sessions", actor_id=actor.id, target_id=user_id)
