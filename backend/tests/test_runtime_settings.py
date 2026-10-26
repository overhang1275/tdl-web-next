from pathlib import Path

import pytest
from test_api_write import WRITE_HEADERS, create_payload
from test_api_write import api as api

from app.config import settings
from app.models import DownloadFile, DownloadJob, JobStatus


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
