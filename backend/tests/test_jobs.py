from __future__ import annotations

from datetime import datetime, timedelta

from app.models import DownloadJob
from app.services.jobs import count_jobs, list_jobs


def test_list_jobs_limits_in_sql_order(db_session):
    session = db_session
    base = datetime(2024, 1, 1)
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
