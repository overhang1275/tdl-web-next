from pathlib import Path

import pytest
from test_api_write import WRITE_HEADERS, create_payload
from test_api_write import api as api

from app.config import settings
from app.models import DownloadFile, DownloadJob, JobStage, JobStatus


def values(root):
    return {"downloads_dir": str(root), "command_timeout_seconds": 3600,
            "download_batch_size": 25, "download_idle_timeout_seconds": 120,
            "export_batch_size": 1000}


def test_settings_persist_across_fresh_reads(api, monkeypatch):
    client, sessions, _ = api
    for name in values(settings.downloads_dir):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json=values(settings.downloads_dir))
    assert response.status_code == 200, response.text
    monkeypatch.setattr(settings, 'download_batch_size', 100)
    with sessions() as db:
        from app.services.runtime_settings import load_runtime
        load_runtime(db)
    assert settings.download_batch_size == 25
    assert client.get('/api/v1/settings').json()['limits']['download_batch_size'] == 25


@pytest.mark.parametrize('name,bad', [('download_batch_size', 0),
    ('export_batch_size', -1), ('command_timeout_seconds', 99999999),
    ('download_idle_timeout_seconds', 'invalid')])
def test_settings_validate_limits(api, name, bad):
    client, _, _ = api
    payload = {**values(settings.downloads_dir), name: bad}
    assert client.put('/api/v1/settings', headers=WRITE_HEADERS, json=payload).status_code == 422


def test_settings_require_idle_queue(api):
    client, _, _ = api
    assert client.post('/api/v1/jobs', headers=WRITE_HEADERS, json=create_payload()).status_code == 201
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS, json=values(settings.downloads_dir))
    assert response.status_code == 409


def test_move_preserves_bytes_and_rewrites_all_paths(api, monkeypatch, tmp_path):
    client, sessions, queue = api
    source = settings.downloads_dir
    for name in values(source):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    folder = source / '123' / 'files'
    folder.mkdir(parents=True)
    media = folder / 'sample.txt'
    media.write_bytes(b'original media\x00\xff')
    with sessions() as db:
        job = DownloadJob(chat_id='123', output_subfolder='files', status=JobStatus.completed,
                          download_path=str(folder))
        db.add(job)
        db.flush()
        db.add(DownloadFile(job_id=job.id, chat_id='123', message_id='1', file_name='sample.txt',
            message_json='{}', destination_root=str(folder), output_dir=str(folder),
            local_path=str(media), status='completed', size=17))
        db.commit()
        job_id = job.id
    target = tmp_path / 'relocated'
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json={**values(target), 'confirm_move': True})
    assert response.status_code == 202, response.text
    assert media.exists()
    assert client.post('/api/v1/jobs', headers=WRITE_HEADERS, json=create_payload()).status_code == 409
    from app.services.runtime_settings import run_settings_move
    operation = client.get('/api/v1/settings').json()['operation']
    run_settings_move(operation['id'])
    moved = target / '123' / 'files' / 'sample.txt'
    assert moved.read_bytes() == b'original media\x00\xff'
    assert not media.exists()
    with sessions() as db:
        assert db.get(DownloadJob, job_id).download_path == str(moved.parent)
        item = db.query(DownloadFile).one()
        assert item.local_path == str(moved)
        assert item.output_dir == item.destination_root == str(moved.parent)
    assert client.get(f'/api/v1/jobs/{job_id}/files').json()['total'] == 1
    assert client.get('/api/v1/settings').json()['operation']['status'] == 'completed'
    assert queue.tasks


def test_failed_copy_keeps_source_and_can_resume(api, monkeypatch, tmp_path):
    client, _, _ = api
    from app.services import runtime_settings as runtime
    source = settings.downloads_dir
    for name in values(source):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    (source / 'media.txt').write_bytes(b'keep me')
    target = tmp_path / 'next-downloads'
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
        json={**values(target), 'confirm_move': True})
    assert response.status_code == 202, response.text
    operation_id = response.json()['operation']['id']
    copy = runtime._copy_file
    monkeypatch.setattr(runtime, '_copy_file', lambda *_: (_ for _ in ()).throw(OSError('disk full')))
    runtime.run_settings_move(operation_id)
    assert (source / 'media.txt').read_bytes() == b'keep me'
    assert settings.downloads_dir == source
    assert client.get('/api/v1/settings').json()['operation']['status'] == 'failed'
    staging = target / f'.tdl-relocation-{operation_id}-staging'
    staging.mkdir(exist_ok=True)
    (staging / 'part-interrupted-process').write_bytes(b'incomplete copy')
    monkeypatch.setattr(runtime, '_copy_file', copy)
    assert client.post('/api/v1/settings/retry', headers=WRITE_HEADERS).status_code == 202
    runtime.run_settings_move(operation_id)
    assert (target / 'media.txt').read_bytes() == b'keep me'
    assert not staging.exists()


@pytest.mark.parametrize('destination', ['relative/path', '/etc', 'source-child', 'occupied'])
def test_move_rejects_unsafe_destinations(api, tmp_path, destination):
    client, _, _ = api
    target = destination
    if destination == 'source-child':
        target = str(settings.downloads_dir / 'child')
    if destination == 'occupied':
        directory = tmp_path / 'occupied'
        directory.mkdir()
        (directory / 'external.txt').write_text('not ours')
        target = str(directory)
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json={**values(Path(target)), 'confirm_move': True})
    assert response.status_code in (400, 422), response.text


def test_failed_database_commit_does_not_remove_originals(api, monkeypatch, tmp_path):
    import json

    from app.models import RuntimeSettings
    from app.services import runtime_settings as runtime

    client, sessions, _ = api
    source = settings.downloads_dir
    for name in values(source):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    (source / 'precious.txt').write_bytes(b'keep until commit')
    target = tmp_path / 'commit-failure'
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json={**values(target), 'confirm_move': True})
    operation_id = response.json()['operation']['id']
    original_commit = sessions.class_.commit
    failed = False

    def commit(db):
        nonlocal failed
        row = next((item for item in db.dirty if isinstance(item, RuntimeSettings)), None)
        if row and row.pending_json and json.loads(row.pending_json).get('committed') and not failed:
            failed = True
            raise OSError('database unavailable')
        return original_commit(db)

    monkeypatch.setattr(sessions.class_, 'commit', commit)
    runtime.run_settings_move(operation_id)
    assert failed
    assert (source / 'precious.txt').read_bytes() == b'keep until commit'
    assert client.get('/api/v1/settings').json()['paths']['downloads_dir'] == str(source)
    assert client.post('/api/v1/settings/retry', headers=WRITE_HEADERS).status_code == 202
    runtime.run_settings_move(operation_id)
    assert not (source / 'precious.txt').exists()
    assert (target / 'precious.txt').read_bytes() == b'keep until commit'


def test_cleanup_failure_resumes_using_committed_destination(api, monkeypatch, tmp_path):
    from app.services import runtime_settings as runtime

    client, _, _ = api
    source = settings.downloads_dir
    for name in values(source):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    original = source / 'precious.txt'
    original.write_bytes(b'verified copy')
    target = tmp_path / 'cleanup-failure'
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json={**values(target), 'confirm_move': True})
    operation_id = response.json()['operation']['id']
    unlink = Path.unlink

    def fail_original(path, *args, **kwargs):
        if path == original:
            raise OSError('original temporarily busy')
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', fail_original)
    runtime.run_settings_move(operation_id)
    assert original.exists()
    assert client.get('/api/v1/settings').json()['paths']['downloads_dir'] == str(target)
    assert client.get('/api/v1/settings').json()['operation']['status'] == 'failed'
    monkeypatch.setattr(Path, 'unlink', unlink)
    assert client.post('/api/v1/settings/retry', headers=WRITE_HEADERS).status_code == 202
    runtime.run_settings_move(operation_id)
    assert not original.exists()
    assert (target / 'precious.txt').read_bytes() == b'verified copy'


def test_flush_failure_keeps_originals_and_old_configuration(api, monkeypatch, tmp_path):
    from app.services import runtime_settings as runtime

    client, _, _ = api
    source = settings.downloads_dir
    for name in values(source):
        monkeypatch.setattr(settings, name, getattr(settings, name))
    (source / 'precious.txt').write_bytes(b'not just cached')
    target = tmp_path / 'flush-failure'
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json={**values(target), 'confirm_move': True})
    monkeypatch.setattr(runtime.os, 'fsync', lambda *_: (_ for _ in ()).throw(OSError('flush failed')))
    runtime.run_settings_move(response.json()['operation']['id'])
    assert (source / 'precious.txt').exists()
    response = client.get('/api/v1/settings').json()
    assert response['paths']['downloads_dir'] == str(source)
    assert response['operation']['status'] == 'failed'


@pytest.mark.parametrize('destination', ['/tmp/tdl-media', '/var/tmp/tdl-media', '/run/tdl-media'])
def test_native_rejects_temporary_storage(api, monkeypatch, destination):
    client, _, _ = api
    exists = Path.exists
    monkeypatch.delenv('DEPLOYMENT_MODE', raising=False)
    monkeypatch.setattr(Path, 'exists', lambda path: False if path == Path('/.dockerenv') else exists(path))
    response = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json={**values(Path(destination)), 'confirm_move': True})
    assert response.status_code == 400, response.text


# Observe the real PostgreSQL wait instead of assuming a thread delay means blocking.
def _wait_for_storage_contender(engine, contender_pid, finished):
    from time import monotonic

    from sqlalchemy import text

    deadline = monotonic() + 10
    with engine.connect() as observer:
        while monotonic() < deadline:
            if finished.is_set():
                return False
            if contender_pid and observer.scalar(text(
                "SELECT EXISTS (SELECT FROM pg_locks WHERE pid = :pid "
                "AND locktype = 'advisory' AND NOT granted)"
            ), {'pid': contender_pid[0]}):
                return True
            finished.wait(0.01)
    raise AssertionError('Contender neither completed nor waited for the storage lock')


@pytest.mark.parametrize('first', ['create', 'move'])
def test_create_job_and_move_are_serialized(api, monkeypatch, tmp_path, first):
    _race_storage_request_with_move(api, monkeypatch, tmp_path, first, 'create')


@pytest.mark.parametrize('first', ['delete', 'move'])
def test_delete_job_and_move_are_serialized(api, monkeypatch, tmp_path, first):
    _race_storage_request_with_move(api, monkeypatch, tmp_path, first, 'delete')


def _race_storage_request_with_move(api, monkeypatch, tmp_path, first, action):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event, current_thread

    from sqlalchemy import event

    from app.models import RuntimeSettings
    from app.services import runtime_settings as runtime

    client, sessions, _ = api
    engine = sessions.kw['bind']
    if action == 'delete':
        with sessions() as db:
            job = DownloadJob(chat_id='123', output_subfolder='download', status=JobStatus.completed)
            db.add(job)
            db.commit()
            job_id = job.id
    ready = Barrier(2, timeout=10)
    release = Event()
    finished = Event()
    contender_pid = []
    paused = False

    def pause_first(db, *_):
        nonlocal paused
        if not paused:
            paused = True
            ready.wait()
            assert release.wait(10)

    if first == 'move':
        require_idle = runtime._require_idle

        def pause_idle(db):
            require_idle(db)
            pause_first(db)

        monkeypatch.setattr(runtime, '_require_idle', pause_idle)
    else:
        # Keep the first job/deletion uncommitted while the move attempts its check.
        event.listen(sessions.class_, 'before_flush', pause_first)

    def capture_pid(connection, cursor, *_):
        if current_thread().name != 'MainThread' and paused and not contender_pid:
            contender_pid.append(cursor.connection.info.backend_pid)

    event.listen(engine, 'before_cursor_execute', capture_pid)

    def move():
        return client.put('/api/v1/settings', headers=WRITE_HEADERS,
                          json={**values(tmp_path / 'racing-move'), 'confirm_move': True})

    def mutate():
        if action == 'create':
            return client.post('/api/v1/jobs', headers=WRITE_HEADERS, json=create_payload())
        return client.request('DELETE', f'/api/v1/jobs/{job_id}',
                              headers=WRITE_HEADERS, json={'confirm': True})

    def second():
        try:
            return (mutate if first == 'move' else move)()
        finally:
            finished.set()

    try:
        with ThreadPoolExecutor(1, thread_name_prefix='storage-first') as one, \
                ThreadPoolExecutor(1, thread_name_prefix='storage-second') as two:
            winner = one.submit(move if first == 'move' else mutate)
            ready.wait()
            loser = two.submit(second)
            try:
                blocked = _wait_for_storage_contender(engine, contender_pid, finished)
            finally:
                release.set()
            responses = [winner.result(timeout=10), loser.result(timeout=10)]
        accepted = 202 if first == 'move' or action == 'delete' else 201
        assert [response.status_code for response in responses] == [accepted, 409], [
            response.text for response in responses]
        assert blocked, 'Incompatible operation bypassed the PostgreSQL storage lock'
        with sessions() as db:
            row = db.get(RuntimeSettings, 1)
            assert bool(row and row.operation_status == 'queued') == (first == 'move')
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', capture_pid)
        if first != 'move':
            event.remove(sessions.class_, 'before_flush', pause_first)


def test_lock_released_after_rollback(api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    from app.services.runtime_settings import _lock

    _, sessions, _ = api
    ready = Barrier(2, timeout=10)
    finished = Event()
    contender_pid = []
    with sessions() as owner:
        _lock(owner)
        owner.add(DownloadJob(chat_id='rolled-back', output_subfolder='download'))
        owner.flush()

        def contend():
            try:
                with sessions() as db:
                    contender_pid.append(db.connection().connection.driver_connection.info.backend_pid)
                    ready.wait()
                    _lock(db)
                    db.commit()
            finally:
                finished.set()

        with ThreadPoolExecutor(1) as executor:
            waiting = executor.submit(contend)
            ready.wait()
            try:
                blocked = _wait_for_storage_contender(sessions.kw['bind'], contender_pid, finished)
            finally:
                owner.rollback()
            waiting.result(timeout=10)
        assert blocked, 'Storage lock must remain held until rollback'
    with sessions() as db:
        assert db.query(DownloadJob).count() == 0


def test_nested_storage_lock_preserves_pending_changes(api):
    from sqlalchemy import text

    from app.services.runtime_settings import _lock

    _, sessions, _ = api
    with sessions() as db:
        db.execute(text("SET LOCAL lock_timeout = '1s'"))
        _lock(db)
        assert db.scalar(text('SHOW lock_timeout')) == '1s'
        job = DownloadJob(chat_id='kept', output_subfolder='download')
        db.add(job)
        _lock(db)
        assert db.scalar(text('SHOW lock_timeout')) == '1s'
        db.commit()
    with sessions() as db:
        assert db.query(DownloadJob).one().chat_id == 'kept'


def test_storage_guard_refreshes_preloaded_move_state(api):
    from starlette.requests import Request

    from app.api.errors import ApiError
    from app.models import RuntimeSettings
    from app.services.runtime_settings import guard_storage_write

    _, sessions, _ = api
    with sessions() as db:
        db.add(RuntimeSettings(id=1, values_json='{}', operation_status='idle'))
        db.commit()
    with sessions() as stale, sessions() as writer:
        cached = stale.get(RuntimeSettings, 1)
        row = writer.get(RuntimeSettings, 1)
        row.operation_status = 'queued'
        writer.commit()
        assert cached.operation_status == 'idle'
        with pytest.raises(ApiError) as error:
            guard_storage_write(Request({'type': 'http', 'method': 'POST'}), stale)
        assert error.value.status_code == 409


@pytest.mark.parametrize('action', ['create', 'retry', 'delete', 'wipe', 'reset'])
def test_storage_services_reject_pending_move(api, action):
    from app.api.errors import ApiError
    from app.models import RuntimeSettings
    from app.schemas import JobCreate
    from app.services.admin import reset_application_state
    from app.services.deletion import enqueue_delete
    from app.services.jobs import create_job, retry_job, wipe_delete_job

    _, sessions, _ = api
    with sessions() as db:
        job = DownloadJob(chat_id='123', output_subfolder='download', status=JobStatus.failed)
        db.add(job)
        db.add(RuntimeSettings(id=1, values_json='{}', operation_status='queued'))
        db.commit()
        with pytest.raises(ApiError) as error:
            if action == 'create':
                create_job(db, JobCreate(**create_payload()), enqueue=False)
            elif action == 'retry':
                retry_job(db, job)
            elif action == 'delete':
                enqueue_delete(db, job)
            elif action == 'wipe':
                wipe_delete_job(db, job)
            else:
                reset_application_state(db)
        assert error.value.status_code == 409


def test_reset_keeps_storage_lock_through_filesystem_cleanup(api, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event

    from app.services import admin
    from app.services.runtime_settings import _lock

    client, sessions, _ = api
    ready = Barrier(2, timeout=10)
    finished = Event()
    contender_pid = []
    cleanup = admin._remove_contents
    checked = False

    def contend():
        try:
            with sessions() as db:
                contender_pid.append(db.connection().connection.driver_connection.info.backend_pid)
                ready.wait()
                _lock(db)
                db.commit()
        finally:
            finished.set()

    with ThreadPoolExecutor(1) as executor:
        waiting = None

        def check_cleanup(path):
            nonlocal checked, waiting
            if not checked:
                checked = True
                waiting = executor.submit(contend)
                ready.wait()
                assert _wait_for_storage_contender(sessions.kw['bind'], contender_pid, finished), (
                    'Reset released the storage lock before deleting files')
            cleanup(path)

        monkeypatch.setattr(admin, '_remove_contents', check_cleanup)
        response = client.post('/api/v1/admin/reset', headers=WRITE_HEADERS,
                               json={'confirmation': 'REINICIAR', 'keep_session': True})
        if waiting is not None:
            waiting.result(timeout=10)
        assert response.status_code == 200, response.text
        assert checked


@pytest.mark.parametrize('phase', ['create_paths', 'retry_snapshot', 'retry_reconcile'])
def test_late_job_preparation_cannot_cross_cancel_and_move(api, monkeypatch, tmp_path, phase):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event, current_thread

    from sqlalchemy import event

    from app.services import runtime_settings as runtime
    from app.services import transfers

    client, sessions, _ = api
    engine = sessions.kw['bind']
    ready = Barrier(2, timeout=10)
    release = Event()
    finished = Event()
    contender_pid = []
    paused = False
    job_id = None
    target = tmp_path / 'late-preparation-move'
    if phase != 'create_paths':
        created = client.post('/api/v1/jobs', headers=WRITE_HEADERS, json=create_payload())
        job_id = created.json()['id']
        with sessions() as db:
            job = db.get(DownloadJob, job_id)
            job.status = JobStatus.failed
            Path(job.filtered_json_path).parent.mkdir(parents=True, exist_ok=True)
            Path(job.filtered_json_path).write_text(json.dumps({'id': 123, 'messages': []}))
            db.commit()

    def pause():
        nonlocal paused
        if not paused:
            paused = True
            ready.wait()
            assert release.wait(10)

    commit = sessions.class_.commit

    def pause_paths(db):
        nonlocal job_id
        for item in db.dirty:
            if isinstance(item, DownloadJob) and item.download_path and not paused:
                job_id = item.id
                pause()
                break
        return commit(db)

    if phase == 'create_paths':
        monkeypatch.setattr(sessions.class_, 'commit', pause_paths)
    elif phase == 'retry_snapshot':
        write = transfers.write_json_atomic

        def pause_snapshot(*args, **kwargs):
            pause()
            return write(*args, **kwargs)

        monkeypatch.setattr(transfers, 'write_json_atomic', pause_snapshot)
    else:
        reconcile = transfers.reconcile_files

        def pause_reconcile(*args, **kwargs):
            result = reconcile(*args, **kwargs)
            pause()
            return result

        monkeypatch.setattr(transfers, 'reconcile_files', pause_reconcile)

    def capture_pid(connection, cursor, *_):
        if current_thread().name != 'MainThread' and paused and not contender_pid:
            contender_pid.append(cursor.connection.info.backend_pid)

    event.listen(engine, 'before_cursor_execute', capture_pid)

    def prepare():
        if phase == 'create_paths':
            return client.post('/api/v1/jobs', headers=WRITE_HEADERS, json=create_payload())
        return client.post(f'/api/v1/jobs/{job_id}/retry', headers=WRITE_HEADERS)

    def cancel_and_move():
        try:
            cancelled = client.post(f'/api/v1/jobs/{job_id}/cancel', headers=WRITE_HEADERS)
            assert cancelled.status_code == 200, cancelled.text
            move = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                              json={**values(target), 'confirm_move': True})
            assert move.status_code == 202, move.text
            runtime.run_settings_move(move.json()['operation']['id'])
        finally:
            finished.set()

    try:
        with ThreadPoolExecutor(1) as first, ThreadPoolExecutor(1) as second:
            preparation = first.submit(prepare)
            ready.wait()
            mutation = second.submit(cancel_and_move)
            try:
                blocked = _wait_for_storage_contender(engine, contender_pid, finished)
            finally:
                release.set()
            response = preparation.result(timeout=10)
            mutation.result(timeout=10)
            assert response.status_code in (200, 201), response.text
        with sessions() as db:
            job = db.get(DownloadJob, job_id)
            assert job.download_path == str(target / '123' / 'download')
            assert job.status == JobStatus.cancelled
            assert job.stage == JobStage.cancelled
            assert job.cancel_requested is True
        assert blocked, 'Preparation released storage exclusion before its final write'
    finally:
        release.set()
        event.remove(engine, 'before_cursor_execute', capture_pid)


def test_worker_storage_lock_bounds_writers_and_allows_polling(api, monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor, wait
    from threading import Barrier, Event
    from time import monotonic

    from app.services import runtime_settings as runtime

    client, sessions, _ = api
    move = client.put('/api/v1/settings', headers=WRITE_HEADERS,
                      json={**values(tmp_path / 'slow-move'), 'confirm_move': True})
    assert move.status_code == 202, move.text
    ready = Barrier(2, timeout=10)
    release = Event()
    copy = runtime._copy_tree

    def slow_copy(*args):
        ready.wait()
        assert release.wait(10)
        return copy(*args)

    monkeypatch.setattr(runtime, '_copy_tree', slow_copy)
    with ThreadPoolExecutor(5) as executor:
        worker = executor.submit(runtime.run_settings_move, move.json()['operation']['id'])
        ready.wait()
        started = monotonic()
        writers = [executor.submit(client.post, '/api/v1/jobs', headers=WRITE_HEADERS,
                                   json={**create_payload(), 'chat_id': str(index)}) for index in range(4)]
        try:
            done, pending = wait(writers, timeout=2)
            elapsed = monotonic() - started
            polling = client.get('/api/v1/jobs')
            assert polling.status_code == 200, polling.text
            assert not pending, 'Writers waited indefinitely behind the file-copy transaction'
            assert elapsed < 2
            assert [future.result().status_code for future in done] == [409] * 4
            assert all(future.result().json()['error']['code'] == 'storage_busy' for future in done)
            assert polling.json()['total'] == 0
        finally:
            release.set()
            worker.result(timeout=10)
    assert client.get('/api/v1/settings').json()['operation']['status'] == 'completed'
    assert client.post('/api/v1/jobs', headers=WRITE_HEADERS, json=create_payload()).status_code == 201
    with sessions() as db:
        assert db.query(DownloadJob).count() == 1
