from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import database
from app.api.deps import get_current_user
from app.config import settings
from app.database import Base
from app.main import app
from app.models import DownloadFile, DownloadJob, DownloadTemplate, JobStage, JobStatus, MediaType
from app.schemas import UserRead
from app.services.status import status_service


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    for name, value in {
        "base_dir": tmp_path,
        "sessions_dir": tmp_path / "sessions",
        "exports_dir": tmp_path / "exports",
        "downloads_dir": tmp_path / "downloads",
        "logs_dir": tmp_path / "logs",
    }.items():
        monkeypatch.setattr(settings, name, value)
    settings.ensure_directories()
    engine = create_engine(f"sqlite:///{tmp_path / 'api.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)

    download_root = tmp_path / "downloads" / "123" / "download"
    message_dir = download_root / "job-1" / "10"
    message_dir.mkdir(parents=True)
    text_file = message_dir / "note.txt"
    text_file.write_text("hola", encoding="utf-8")
    html_file = message_dir / "page.html"
    html_file.write_text("<script>alert(1)</script>", encoding="utf-8")
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "logs" / "job-1.log").write_text(
        "[2026-01-01T00:00:00Z] Completed: 1 archivo\n", encoding="utf-8"
    )

    with sessions() as db:
        job = DownloadJob(
            chat_id="123",
            chat_title="Canal de prueba",
            media_type=MediaType.document,
            output_subfolder="download",
            download_path=str(download_root),
            filtered_json_path=str(tmp_path / "exports" / "filtered.json"),
            export_json_path=str(tmp_path / "exports" / "export.json"),
            stage=JobStage.downloading,
            status=JobStatus.running,
            transfer_initialized=True,
            total_filtered_messages=2,
            total_downloaded_files=1,
            created_at=datetime.now(UTC),
        )
        db.add(job)
        db.flush()
        db.add_all(
            [
                DownloadFile(
                    job_id=job.id,
                    chat_id="123",
                    message_id="10",
                    file_name="note.txt",
                    message_json="{}",
                    destination_root=str(download_root),
                    output_dir="job-1/10",
                    local_path=str(text_file),
                    expected_size=4,
                    size=4,
                    status="completed",
                ),
                DownloadFile(
                    job_id=job.id,
                    chat_id="123",
                    message_id="11",
                    file_name="page.html",
                    message_json="{}",
                    destination_root=str(download_root),
                    output_dir="job-1/11",
                    local_path=str(html_file),
                    expected_size=25,
                    size=25,
                    status="completed",
                ),
            ]
        )
        db.add(
            DownloadTemplate(
                name="Documentos",
                media_type=MediaType.document,
                output_subfolder="download",
                created_at=datetime.now(UTC),
            )
        )
        db.commit()
        yield sessions, job.id


@pytest.fixture
def client(seeded, monkeypatch):
    sessions, _ = seeded
    monkeypatch.setattr("app.main.init_db", lambda: None)
    monkeypatch.setattr(
        status_service,
        "get",
        lambda force=False: {
            "environment": "test",
            "version": "1.0.0",
            "session_active": False,
            "session_error": None,
            "tdl_installed": False,
            "tdl_binary": "tdl",
            "redis_connected": False,
            "redis_error": None,
            "worker_connected": False,
            "worker_count": 0,
            "storage": "/tmp/sessions",
            "can_start_services": True,
            "authentik_configured": True,
        },
    )

    def override_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_current_user] = lambda: UserRead(username="admin")
    app.dependency_overrides[database.get_db] = override_db
    with TestClient(app) as test_client:
        yield test_client, sessions
    app.dependency_overrides.clear()


def test_jobs_list_and_detail(client):
    test_client, _ = client
    response = test_client.get("/api/v1/jobs")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    job = body["items"][0]
    assert job["chat_title"] == "Canal de prueba"
    assert job["progress_percent"] == 50.0
    assert job["total_expected_bytes"] == 29
    detail = test_client.get(f"/api/v1/jobs/{job['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == job["id"]


def test_files_list_and_content(client):
    test_client, _ = client
    files = test_client.get("/api/v1/jobs/1/files")
    assert files.status_code == 200
    items = files.json()["items"]
    assert {item["name"] for item in items} == {"note.txt", "page.html"}
    note = next(item for item in items if item["name"] == "note.txt")
    content = test_client.get(note["content_url"])
    assert content.status_code == 200
    assert content.text == "hola"
    html = next(item for item in items if item["name"] == "page.html")
    unsafe = test_client.get(html["content_url"])
    assert unsafe.status_code == 200
    assert unsafe.headers["content-disposition"].startswith("attachment")
    assert unsafe.headers["content-security-policy"] == "sandbox"


def test_legacy_path_traversal_is_blocked(client):
    test_client, _ = client
    response = test_client.get("/api/v1/jobs/1/files/content?path=../../secret")
    assert response.status_code == 404


def test_logs_and_dashboard(client):
    test_client, _ = client
    logs = test_client.get("/api/v1/jobs/1/logs")
    assert logs.status_code == 200
    assert "Completed" in logs.json()["content"]
    dashboard = test_client.get("/api/v1/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["active_jobs"] == 1


def test_templates_and_search(client):
    test_client, _ = client
    templates = test_client.get("/api/v1/templates")
    assert templates.status_code == 200
    assert templates.json()[0]["name"] == "Documentos"
    search = test_client.get("/api/v1/search?q=note")
    assert search.status_code == 200
    assert search.json()["files"][0]["title"] == "note.txt"


def test_settings_does_not_expose_secrets(client):
    test_client, _ = client
    response = test_client.get("/api/v1/settings")
    assert response.status_code == 200
    text = response.text
    assert "AUTHENTIK_CLIENT_SECRET" not in text
    assert "AUTH_SECRET" not in text
