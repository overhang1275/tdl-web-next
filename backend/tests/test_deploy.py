from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), SCRIPTS / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_keeps_existing_paths_and_secrets(tmp_path, monkeypatch):
    config = load('configure-env')
    legacy = tmp_path / 'legacy.env'
    data = tmp_path / 'original-data'
    legacy.write_text(f'DATA_DIR={data}\nDOWNLOADS_DIR=/mnt/telegram\n')
    output = tmp_path / '.env'
    config.configure(output, 'example.test', legacy, tmp_path)
    first = config.read_env(output)
    config.configure(output, 'example.test', legacy, tmp_path)
    assert config.read_env(output) == first
    assert first['DATA_DIR'] == str(data)
    assert first['DOWNLOADS_DIR'] == '/mnt/telegram'
    assert first['AUTHENTIK_ISSUER'].endswith('/tdl-console/')
    assert len(first['AUTH_SECRET']) == 64


def test_env_round_trip_preserves_quoted_secret(tmp_path):
    config = load('configure-env')
    output = tmp_path / '.env'
    config.configure(output, 'example.test', tmp_path / 'missing', tmp_path)
    with output.open('a') as stream:
        stream.write('CUSTOM_SECRET="literal \\"quote\\" and \\\\ slash $value"\n')
    expected = 'literal "quote" and \\ slash $value'
    config.configure(output, 'example.test', output, tmp_path)
    assert config.read_env(output)['CUSTOM_SECRET'] == expected


def test_backup_refuses_active_jobs_and_preserves_database(tmp_path):
    config = load('configure-env')
    admin = load('data-admin')
    env = tmp_path / '.env'
    config.configure(env, 'example.test', tmp_path / 'missing', tmp_path)
    values = config.read_env(env)
    db_path = admin.database_path(values)
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE download_jobs (id INTEGER, status TEXT)')
        db.execute("INSERT INTO download_jobs VALUES (1, 'running')")
    with pytest.raises(RuntimeError, match='activos'):
        admin.backup(env)
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE download_jobs SET status='completed'")
    destination = admin.backup(env)
    with sqlite3.connect(destination / 'database.sqlite3') as db:
        assert db.execute('SELECT status FROM download_jobs').fetchone()[0] == 'completed'
    assert db_path.exists()
    assert (destination / '.env').read_text() == env.read_text()


def test_native_update_refuses_download_folder_migration(tmp_path):
    admin = load('data-admin')
    path = tmp_path / 'state.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE runtime_settings (id INTEGER, operation_status TEXT)')
        db.execute("INSERT INTO runtime_settings VALUES (1, 'moving')")
    with pytest.raises(RuntimeError, match='traslado'):
        admin.require_idle({'DATABASE_URL': f'sqlite:///{path}'})


def test_native_configuration_uses_external_oidc_and_no_container_defaults(tmp_path, monkeypatch):
    config = load('configure-env')
    monkeypatch.setenv('AUTHENTIK_ISSUER', 'https://identity.example.test/application/o/tdl/')
    monkeypatch.setenv('AUTHENTIK_CLIENT_ID', 'external-client')
    monkeypatch.setenv('AUTHENTIK_CLIENT_SECRET', 'external-secret')
    monkeypatch.setenv('NATIVE_INGRESS', 'tunnel')
    monkeypatch.setenv('AUTH_URL', 'https://downloads.example.test')
    env = tmp_path / 'native.env'
    config.configure(env, 'example.test', tmp_path / 'missing', tmp_path, deployment='native')
    values = config.read_env(env)
    assert values['AUTHENTIK_CLIENT_SECRET'] == 'external-secret'
    assert values['AUTHENTIK_AUDIENCE'] == 'external-client'
    assert values['REDIS_URL'] == 'redis://127.0.0.1:6379/1'
    assert values['API_INTERNAL_URL'] == 'http://127.0.0.1:8000'
    assert values['NATIVE_INGRESS'] == 'tunnel'
    assert values['AUTH_URL'] == 'https://downloads.example.test'
    assert 'PG_PASS' not in values
    assert 'AUTHENTIK_BOOTSTRAP_PASSWORD' not in values


def test_native_backup_uses_protected_destination_and_can_restore_database(tmp_path):
    config = load('configure-env')
    admin = load('data-admin')
    env = tmp_path / 'app.env'
    config.configure(env, 'example.test', tmp_path / 'missing', tmp_path)
    db_path = admin.database_path(config.read_env(env))
    db_path.parent.mkdir()
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE marker (value TEXT)')
        db.execute("INSERT INTO marker VALUES ('before')")
    snapshot = admin.backup(env, tmp_path / 'protected-backups')
    assert snapshot.parent == tmp_path / 'protected-backups'
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE marker SET value='after'")
    admin.restore_database(env, snapshot)
    with sqlite3.connect(db_path) as db:
        assert db.execute('SELECT value FROM marker').fetchone()[0] == 'before'


def test_native_backup_rejects_pending_deletion(tmp_path):
    admin = load('data-admin')
    path = tmp_path / 'state.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE download_jobs (status TEXT, deletion_requested INTEGER)')
        db.execute("INSERT INTO download_jobs VALUES ('completed', 1)")
    with pytest.raises(RuntimeError, match='borrados'):
        admin.require_idle({'DATABASE_URL': f'sqlite:///{path}'})
