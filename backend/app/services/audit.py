"""Audit metadata only. Callers own commits; never pass request bodies here."""
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuditEvent


def audit(db: Session, actor_id: UUID | None, action: str, target_id: UUID | int | None, outcome: str) -> None:
    db.add(AuditEvent(actor_id=actor_id, action=action,
                      target_id=str(target_id) if target_id is not None else None, outcome=outcome))
    db.flush()


@contextmanager
def audited_operation(db: Session, actor_id: UUID | None, action: str, target_id=None, *, outcome="success"):
    """For legacy services that commit internally; record their observed result.

    Enter without committing, so storage guards remain held until the service's
    own commit. Account mutations instead audit inside their atomic transaction.
    """
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
