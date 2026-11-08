"""Internal-only fixture for a controlled idle deadline in the isolated e2e stack."""
import os
if os.environ.get("APP_ENV") != "test" or os.environ.get("E2E_INTEGRATION") != "1":
    raise RuntimeError("Test control requires isolated test configuration")

from datetime import UTC, datetime, timedelta
from fastapi import FastAPI
from sqlalchemy import select, update
from app.database import SessionLocal
from app.models import AuthSession, User

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/expire-idle-probe", status_code=204)
def expire():
    with SessionLocal.begin() as db:
        db.execute(update(AuthSession).where(AuthSession.user_id == select(User.id).where(User.username == "idle-probe").scalar_subquery()).values(idle_expires_at=datetime.now(UTC) - timedelta(seconds=1)))
