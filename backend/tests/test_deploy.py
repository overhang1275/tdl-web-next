from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
DEPLOY = SCRIPTS.parent / 'deploy'


def test_compose_without_authentik_needs_no_oidc_secrets():
    basic = (DEPLOY / 'docker/compose.yml').read_text()
    assert 'AUTHENTIK_ENABLED: ${AUTHENTIK_ENABLED:-false}' in basic
    assert '${AUTHENTIK_ISSUER:?' not in basic
    assert '${AUTHENTIK_CLIENT_SECRET:?' not in basic
    assert '${PG_PASS' not in basic
    assert 'authentik-server:' not in basic
    assert 'authentik-server' not in (DEPLOY / 'nginx/tdl-web.conf.template').read_text()


def test_tdl_postgres_does_not_reuse_authentik_volume():
    basic = (DEPLOY / 'docker/compose.yml').read_text()
    hosted = (DEPLOY / 'docker/compose.authentik.yml').read_text()
    assert '- tdl-postgres-data:/var/lib/postgresql/data' in basic
    assert 'volumes: [postgres-data:/var/lib/postgresql/data]' in hosted
    assert 'POSTGRES_USER: postgres' in basic
    assert 'POSTGRES_USER: authentik' in hosted


def test_postgres_initializer_limits_application_role():
    initializer = (DEPLOY / 'docker/init-tdl-postgres.sh').read_text()
    assert "<<'SQL'" in initializer
    assert r'\getenv tdl_password TDL_POSTGRES_PASSWORD' in initializer
    assert "PASSWORD :'tdl_password'" in initializer
    assert 'NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION' in initializer
    assert 'CREATE DATABASE tdl OWNER tdl' in initializer


def test_api_waits_for_migration():
    basic = (DEPLOY / 'docker/compose.yml').read_text()
    api = basic.split('\n  api:\n')[1].split('\n  worker:')[0]
    web = basic.split('\n  web:\n')[1].split('\n  nginx:')[0]
    assert 'migrate: {condition: service_completed_successfully}' in api
    assert 'bootstrap: {condition: service_completed_successfully}' in web
    bootstrap = basic.split('\n  bootstrap:\n')[1].split('\n  api:')[0]
    assert 'user: "0:0"' in bootstrap
    assert '--docker-maintenance' in bootstrap
    assert '--password-file' in bootstrap
    assert 'jwt-private.pem' not in web


def test_postgres_port_not_published():
    basic = (DEPLOY / 'docker/compose.yml').read_text()
    postgres = basic.split('\n  tdl-postgres:\n')[1].split('\n  redis:')[0]
    assert 'ports:' not in postgres
    assert 'networks: [services]' in postgres


def test_compose_shares_explicit_installation_queue():
    basic = (DEPLOY / 'docker/compose.yml').read_text()
    assert 'RQ_QUEUE_NAME: ${RQ_QUEUE_NAME:?Set RQ_QUEUE_NAME}' in basic
    assert 'telegram-downloads' not in basic
    assert basic.split('\n  worker:\n')[1].split('\n  web:')[0].count('<<: *api') == 1


def test_backend_test_runner_has_an_explicit_queue():
    compose = (DEPLOY / 'docker/compose.test.yml').read_text()
    runner = compose.split('\n  backend-tests:\n')[1].split('\n  frontend-tests:')[0]
    assert 'RQ_QUEUE_NAME: ${RQ_QUEUE_NAME:?Set isolated RQ_QUEUE_NAME}' in runner


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


def test_backup_refuses_active_jobs_and_preserves_database(tmp_path, admin_databases):
    config = load('configure-env')
    admin = load('data-admin')
    env = tmp_path / '.env'
    config.configure(env, 'example.test', tmp_path / 'missing', tmp_path)
    with env.open('a') as stream:
        stream.write(f"DATABASE_URL={admin_databases[0]}\n")
    engine = create_engine(admin_databases[0])
    with engine.begin() as db:
        db.execute(text('CREATE TABLE download_jobs (id INTEGER, status TEXT)'))
        db.execute(text("INSERT INTO download_jobs VALUES (1, 'running')"))
    with pytest.raises(RuntimeError, match='activos'):
        admin.backup(env)
    with engine.begin() as db:
        db.execute(text("UPDATE download_jobs SET status='completed'"))
    engine.dispose()
    destination = admin.backup(env)
    assert (destination / 'database.dump').read_bytes().startswith(b'PGDMP')
    assert (destination / '.env').read_text() == env.read_text()
    engine = create_engine(admin_databases[0])
    with engine.connect() as db:
        assert db.execute(text('SELECT status FROM download_jobs')).scalar_one() == 'completed'
    engine.dispose()


def test_native_update_refuses_download_folder_migration(admin_databases):
    admin = load('data-admin')
    engine = create_engine(admin_databases[0])
    with engine.begin() as db:
        db.execute(text('CREATE TABLE runtime_settings (id INTEGER, operation_status TEXT)'))
        db.execute(text("INSERT INTO runtime_settings VALUES (1, 'moving')"))
    engine.dispose()
    with pytest.raises(RuntimeError, match='traslado'):
        admin.require_idle({'DATABASE_URL': admin_databases[0]})


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


def test_native_backup_uses_protected_destination_and_can_restore_database(tmp_path, admin_databases):
    config = load('configure-env')
    admin = load('data-admin')
    env = tmp_path / 'app.env'
    config.configure(env, 'example.test', tmp_path / 'missing', tmp_path)
    with env.open('a') as stream:
        stream.write(f"DATABASE_URL={admin_databases[0]}\n")
    engine = create_engine(admin_databases[0])
    with engine.begin() as db:
        db.execute(text('CREATE TABLE marker (value TEXT)'))
        db.execute(text("INSERT INTO marker VALUES ('before')"))
    engine.dispose()
    snapshot = admin.backup(env, tmp_path / 'protected-backups')
    assert snapshot.parent == tmp_path / 'protected-backups'
    engine = create_engine(admin_databases[0])
    with engine.begin() as db:
        db.execute(text("UPDATE marker SET value='after'"))
    engine.dispose()
    target = tmp_path / 'target.env'
    target.write_text(env.read_text().replace(admin_databases[0], admin_databases[1]))
    admin.restore_database(target, snapshot, services_stopped=True)
    engine = create_engine(admin_databases[1])
    with engine.connect() as db:
        assert db.execute(text('SELECT value FROM marker')).scalar_one() == 'before'
    engine.dispose()


def test_native_backup_rejects_pending_deletion(admin_databases):
    admin = load('data-admin')
    engine = create_engine(admin_databases[0])
    with engine.begin() as db:
        db.execute(text('CREATE TABLE download_jobs (status TEXT, deletion_requested BOOLEAN)'))
        db.execute(text("INSERT INTO download_jobs VALUES ('completed', true)"))
    engine.dispose()
    with pytest.raises(RuntimeError, match='borrados'):
        admin.require_idle({'DATABASE_URL': admin_databases[0]})
