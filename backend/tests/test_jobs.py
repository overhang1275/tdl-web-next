from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import DownloadJob
from app.services.jobs import count_jobs, list_jobs


def test_production_requires_explicit_queue(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv('APP_ENV', 'production')
    monkeypatch.delenv('RQ_QUEUE_NAME', raising=False)
    with pytest.raises(RuntimeError, match='RQ_QUEUE_NAME'):
        Settings()


def test_queue_name_shared_by_producer_worker(monkeypatch):
    from app import rq_worker
    from app.config import settings
    from app.services.jobs import get_queue

    name = 'tdl-3974e564-2f93-40ec-b5d3-02dca95a5b3f-downloads'
    monkeypatch.setattr(settings, 'rq_queue_name', name, raising=False)
    assert get_queue().name == name
    observed = []

    class CapturingWorker:
        def __init__(self, queues, connection):
            observed.extend(queue.name for queue in queues)

        def work(self, *, with_scheduler):
            assert with_scheduler is True

    monkeypatch.setattr(rq_worker, 'init_db', lambda: None)
    monkeypatch.setattr(rq_worker, 'reconcile_deletions', lambda: None)
    monkeypatch.setattr(rq_worker, 'Worker', CapturingWorker)
    rq_worker.main()
    assert observed == [name]


def test_list_jobs_limits_in_sql_order(db_session):
    session = db_session
    base = datetime(2024, 1, 1, tzinfo=UTC)
    for index in range(5):
        session.add(
            DownloadJob(
                chat_id=str(index),
                output_subfolder="download",
                created_at=base + timedelta(minutes=index),
            )
        )
    session.commit()

    jobs = list_jobs(session, limit=2, offset=1)

    assert count_jobs(session) == 5
    assert [job.chat_id for job in jobs] == ["3", "2"]
