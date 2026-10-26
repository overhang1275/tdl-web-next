from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database
from app.api.deps import get_current_user
from app.config import settings
from app.database import Base
from app.main import app
from app.models import DownloadFile, DownloadJob, JobStatus
from app.schemas import UserRead

WRITE_HEADERS = {"X-Requested-With": "tdl-web", "Origin": "http://testserver"}


class FakeQueue:
    def __init__(self):
        self.connection = SimpleNamespace(ping=lambda: True)
        self.job_ids: list[str] = []
        self.tasks: list[tuple] = []

    def enqueue(self, function, *args, **kwargs):
        token = kwargs.get("job_id") or f"job-{len(self.tasks)}"
        self.job_ids.append(token)
        self.tasks.append((function, args, kwargs, token))
        return SimpleNamespace(id=token)

    def enqueue_in(self, delay, function, *args, **kwargs):
        return self.enqueue(function, *args, **kwargs)

    def empty(self):
        self.job_ids.clear()
        self.tasks.clear()


@pytest.fixture
def api(tmp_path, monkeypatch):
    for name, value in {
        "base_dir": tmp_path,
        "sessions_dir": tmp_path / "sessions",
        "exports_dir": tmp_path / "exports",
        "downloads_dir": tmp_path / "downloads",
        "logs_dir": tmp_path / "logs",
    }.items():
        monkeypatch.setattr(settings, name, value)
    settings.ensure_directories()
    engine = create_engine(f"sqlite:///{tmp_path / 'write.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    queue = FakeQueue()
    monkeypatch.setattr("app.services.jobs.get_queue", lambda: queue)
    monkeypatch.setattr("app.services.deletion.get_queue", lambda: queue)
    monkeypatch.setattr("app.services.admin.get_queue", lambda: queue)
    monkeypatch.setattr("app.main.init_db", lambda: None)

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_current_user] = lambda: UserRead(username="admin")
    app.dependency_overrides[database.get_db] = override_db
    with TestClient(app) as client:
        yield client, sessions, queue
    app.dependency_overrides.clear()


def create_payload():
    return {
        "chat_id": "123",
        "chat_title": "Canal",
        "media_type": "document",
        "output_subfolder": "download",
        "skip_same": True,
        "refresh_export": True,
        "export_only": False,
    }


def test_create_job_and_duplicate(api):
    client, _, queue = api
    first = client.post("/api/v1/jobs", json=create_payload(), headers=WRITE_HEADERS)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "pending"
    assert len(queue.tasks) == 1
    second = client.post("/api/v1/jobs", json=create_payload(), headers=WRITE_HEADERS)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_job"


def test_cancel_and_retry(api):
    client, sessions, _ = api
    created = client.post("/api/v1/jobs", json=create_payload(), headers=WRITE_HEADERS)
    job_id = created.json()["id"]
    with sessions() as db:
        job = db.get(DownloadJob, job_id)
        job.status = JobStatus.failed
        db.add(
            DownloadFile(
                job_id=job_id,
                chat_id="123",
                message_id="1",
                file_name="a.txt",
                message_json="{}",
                destination_root=job.download_path,
                output_dir="job-1/1",
                status="failed",
                attempts=3,
            )
        )
        db.commit()
    retry = client.post(
        f"/api/v1/jobs/{job_id}/retry?mode=failed", headers=WRITE_HEADERS
    )
    assert retry.status_code == 200, retry.text
    with sessions() as db:
        item = db.query(DownloadFile).one()
        assert item.status == "pending"
        assert item.attempts == 0


def test_delete_requires_confirmation_and_sets_state(api):
    client, sessions, queue = api
    created = client.post("/api/v1/jobs", json=create_payload(), headers=WRITE_HEADERS)
    job_id = created.json()["id"]
    missing = client.request(
        "DELETE", f"/api/v1/jobs/{job_id}", json={"confirm": False}, headers=WRITE_HEADERS
    )
    assert missing.status_code == 400
    response = client.request(
        "DELETE", f"/api/v1/jobs/{job_id}", json={"confirm": True}, headers=WRITE_HEADERS
    )
    assert response.status_code == 202, response.text
    assert response.json()["deletion_requested"] is True
    assert any(task[0] == "app.worker.delete_job" for task in queue.tasks)


def test_templates_crud(api):
    client, _, _ = api
    created = client.post(
        "/api/v1/templates",
        json={"name": "Docs", "media_type": "document", "output_subfolder": "docs"},
        headers=WRITE_HEADERS,
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]
    updated = client.put(
        f"/api/v1/templates/{template_id}",
        json={"name": "Docs 2", "media_type": "video"},
        headers=WRITE_HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Docs 2"
    deleted = client.request(
        "DELETE",
        f"/api/v1/templates/{template_id}",
        json={"confirm": True},
        headers=WRITE_HEADERS,
    )
    assert deleted.status_code == 204


def test_reset_keeps_session_by_default(api):
    client, sessions, _ = api
    client.post("/api/v1/jobs", json=create_payload(), headers=WRITE_HEADERS)
    response = client.post(
        "/api/v1/admin/reset",
        json={"confirmation": "REINICIAR", "keep_session": True},
        headers=WRITE_HEADERS,
    )
    assert response.status_code == 200, response.text
    with sessions() as db:
        assert db.query(DownloadJob).count() == 0
