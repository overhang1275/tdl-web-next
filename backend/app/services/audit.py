"""Audit metadata only. Callers own commits; never pass request bodies here."""
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import AuditEvent


def audit(db: Session, actor_id: UUID | None, action: str, target_id: UUID | int | None, outcome: str) -> None:
    db.add(AuditEvent(actor_id=actor_id, action=action,
                      target_id=str(target_id) if target_id is not None else None, outcome=outcome))
    db.flush()


@contextmanager
def audited_operation(db: Session, actor_id: UUID | None, action: str, target_id=None, *, outcome="success"):
    """Durable intent before legacy effects, followed by their observed result.

    An independent pool commits only safe intent metadata, preserving the
    caller's storage guards/writes even when its request pool is full. Do not
    wrap account mutations, which hold User locks and audit atomically.
    """
    source = db.get_bind().engine
    # Recreate retains the connection creator (including search_path/connect_args)
    # without sharing finite checkout capacity with the still-open caller.
    intent_engine = create_engine(source.url, pool=source.pool.recreate(),
                                  hide_parameters=source.hide_parameters)
    try:
        with Session(intent_engine) as intent:
            audit(intent, actor_id, action, target_id, "started")
            intent.commit()
    finally:
        intent_engine.dispose()
    result = {"outcome": outcome}
    try:
        yield result
    except Exception:
        db.rollback()
        audit(db, actor_id, action, target_id, "failure")
        db.commit()
        raise
    else:
        audit(db, actor_id, action, target_id, result["outcome"])
        db.commit()
