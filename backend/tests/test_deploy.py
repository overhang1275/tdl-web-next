from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
DEPLOY = SCRIPTS.parent / 'deploy'


@pytest.fixture(autouse=True)
def isolated_deployment_environment(monkeypatch):
    # The test runner database is not the installer target being generated.
    monkeypatch.delenv('DATABASE_URL', raising=False)


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
    legacy.chmod(0o640)
    output = tmp_path / '.env'
    config.configure(output, 'example.test', legacy, tmp_path)
    first = config.read_env(output)
    config.configure(output, 'example.test', legacy, tmp_path)
    assert config.read_env(output) == first
    assert first['DATA_DIR'] == str(data)
    assert first['DOWNLOADS_DIR'] == '/mnt/telegram'
    assert first['AUTHENTIK_ENABLED'] == 'false'
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
    monkeypatch.setenv('AUTHENTIK_ENABLED', 'true')
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


def test_basic_configuration_generates_private_stable_local_auth(tmp_path):
    import os
    import stat

    from cryptography.hazmat.primitives import serialization

    config = load('configure-env')
    env = tmp_path / 'config' / 'app.env'
    config.configure(env, 'tdl.example.test', tmp_path / 'missing', tmp_path, 'native')
    first = config.read_env(env)
    assert first['AUTH_URL'] == 'https://tdl.example.test'
    assert first['AUTHENTIK_ENABLED'] == 'false'
    assert first['DATABASE_URL'].startswith('postgresql+psycopg://')
    assert first['TDL_POSTGRES_PASSWORD'] != first['TDL_POSTGRES_ADMIN_PASSWORD']
    assert first['RQ_QUEUE_NAME'].startswith('tdl-')
    private = Path(first['JWT_PRIVATE_KEY_FILE'])
    public = Path(first['JWT_PUBLIC_KEY_FILE'])
    assert private == tmp_path / 'data' / 'keys' / 'jwt-private.pem'
    password = Path(first['ADMIN_PASSWORD_FILE'])
    original = [path.read_bytes() for path in (private, public, password)]
    key = serialization.load_pem_private_key(original[0], password=None)
    assert key.key_size >= 2048
    assert key.public_key().public_numbers() == serialization.load_pem_public_key(original[1]).public_numbers()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert stat.S_IMODE(password.stat().st_mode) == 0o600
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    if os.geteuid() == 0:
        assert env.stat().st_uid == password.stat().st_uid == 0
        assert private.stat().st_uid == int(first['APP_UID'])
        # The native mutable data root belongs to the API after installation.
        os.chown(tmp_path / 'data', int(first['APP_UID']), int(first['APP_GID']))
        (tmp_path / 'data').chmod(0o750)
        for path in (private, public):
            os.chown(path, 0, 0)
            path.chmod(0o640)
    config.configure(env, 'tdl.example.test', env, tmp_path, 'native')
    assert config.read_env(env) == first
    assert all(path.read_bytes() == before for path, before in zip((private, public, password), original, strict=True))
    if os.geteuid() == 0:
        assert all(path.stat().st_uid == int(first['APP_UID']) and path.stat().st_mode & 0o777 == 0o600
                   for path in (private, public))


def test_legacy_requires_explicit_fresh(tmp_path):
    config = load('configure-env')
    legacy = tmp_path / 'legacy.env'
    sqlite = tmp_path / 'old.sqlite3'
    sqlite.write_bytes(b'legacy fixture')
    legacy.write_text(f'DATABASE_URL=sqlite:///{sqlite}\nAUTHENTIK_CLIENT_SECRET=ignored-legacy\n')
    legacy.chmod(0o640)
    output = tmp_path / 'new.env'
    with pytest.raises(ValueError, match='--fresh'):
        config.configure(output, 'example.test', legacy, tmp_path, 'native')
    assert not output.exists()
    assert not (tmp_path / 'data' / 'keys').exists()


def test_legacy_sqlite_file_without_database_url_also_requires_fresh(tmp_path):
    config = load('configure-env')
    data = tmp_path / 'data'
    data.mkdir()
    sqlite = data / 'telegram_downloader.sqlite3'
    sqlite.write_bytes(b'legacy SQLite fixture')
    with pytest.raises(ValueError, match='--fresh'):
        config.configure(tmp_path / 'app.env', 'example.test', tmp_path / 'missing', tmp_path, 'native')
    assert sqlite.read_bytes() == b'legacy SQLite fixture'


def test_fresh_assigns_new_queue_without_deleting_old_resources(tmp_path):
    config = load('configure-env')
    env = tmp_path / 'app.env'
    data = tmp_path / 'data'
    data.mkdir()
    markers = [data / name for name in ('old.sqlite3', 'telegram.session', 'media.bin')]
    for path in markers:
        path.write_bytes(b'keep old resources')
    env.write_text(f'DATA_DIR={data}\nDATABASE_URL=sqlite:///{markers[0]}\nRQ_QUEUE_NAME=legacy-queue\n')
    env.chmod(0o640)
    config.configure(env, 'example.test', env, tmp_path, 'native', {'FRESH': True})
    first = config.read_env(env)
    config.configure(env, 'example.test', env, tmp_path, 'native', {'FRESH': True})
    second = config.read_env(env)
    assert first['RQ_QUEUE_NAME'] != second['RQ_QUEUE_NAME'] != 'legacy-queue'
    assert first['DATABASE_URL'] != second['DATABASE_URL']
    assert all(path.read_bytes() == b'keep old resources' for path in markers)
    assert second['AUTHENTIK_ENABLED'] == 'false'
    docker = tmp_path / 'docker.env'
    config.configure(docker, 'example.test', tmp_path / 'missing', tmp_path, native_options={'FRESH': True})
    assert config.read_env(docker)['COMPOSE_PROJECT_NAME'].startswith('tdl-')


def test_fresh_rejects_same_database_even_with_different_password(tmp_path):
    config = load('configure-env')
    env = tmp_path / 'app.env'
    env.write_text('DATABASE_URL=postgresql+psycopg://old:before@localhost:5432/existing\n')
    env.chmod(0o600)
    with pytest.raises(ValueError, match='DATABASE_URL'):
        config.configure(env, 'example.test', env, tmp_path, 'native',
                         {'FRESH': True, 'DATABASE_URL': 'postgresql://new:after@LOCALHOST/existing'})


def test_optional_provider_is_explicit_and_incomplete_error_does_not_leak(tmp_path, monkeypatch):
    config = load('configure-env')
    legacy = tmp_path / 'legacy.env'
    legacy.write_text('AUTHENTIK_ISSUER=malformed\nAUTHENTIK_CLIENT_SECRET=private-fixture\n')
    legacy.chmod(0o640)
    output = tmp_path / 'app.env'
    config.configure(output, 'example.test', legacy, tmp_path, 'native')
    assert 'AUTHENTIK_CLIENT_SECRET' not in config.read_env(output)
    monkeypatch.setenv('AUTHENTIK_ENABLED', 'true')
    with pytest.raises(ValueError) as error:
        config.configure(output, 'example.test', output, tmp_path, 'native')
    assert 'AUTHENTIK_ISSUER' in str(error.value)
    assert 'private-fixture' not in str(error.value)


def test_configuration_rejects_symlink_secret_paths(tmp_path):
    config = load('configure-env')
    target = tmp_path / 'target'
    target.write_text('preserve')
    linked = tmp_path / 'linked'
    linked.symlink_to(target)
    with pytest.raises(ValueError, match='symlink'):
        config.configure(tmp_path / 'env', 'example.test', tmp_path / 'missing', tmp_path,
                         'native', {'JWT_PRIVATE_KEY_FILE': str(linked)})
    assert target.read_text() == 'preserve'


def test_missing_private_key_never_silently_rotates_existing_public_key(tmp_path):
    config = load('configure-env')
    public = tmp_path / 'keys' / 'jwt-public.pem'
    public.parent.mkdir()
    public.write_bytes(b'preserve public key')
    with pytest.raises(ValueError, match='private key missing'):
        config.configure(tmp_path / 'app.env', 'example.test', tmp_path / 'missing', tmp_path)
    assert public.read_bytes() == b'preserve public key'


def test_configure_cli_names_missing_provider_fields_without_secret_output(tmp_path):
    import os
    import subprocess
    import sys

    result = subprocess.run([sys.executable, str(SCRIPTS / 'configure-env.py'), '--output', str(tmp_path / 'app.env'),
                             '--root', str(tmp_path), '--legacy', str(tmp_path / 'missing')],
                            capture_output=True, text=True, env={**os.environ, 'AUTHENTIK_ENABLED': 'true',
                            'AUTHENTIK_CLIENT_SECRET': 'never-echo-provider-secret'})
    assert result.returncode != 0
    assert 'AUTHENTIK_ISSUER' in result.stderr and 'AUTHENTIK_CLIENT_ID' in result.stderr
    assert 'never-echo-provider-secret' not in result.stdout + result.stderr
    assert not (tmp_path / 'keys').exists()


def test_weak_existing_signing_key_is_rejected(tmp_path):
    import subprocess

    config = load('configure-env')
    private = tmp_path / 'weak.pem'
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:1024',
                    '-out', str(private)], capture_output=True, check=True)
    private.chmod(0o640)
    original = file_snapshot(private)
    with pytest.raises(ValueError, match='2048'):
        config.configure(tmp_path / 'app.env', 'example.test', tmp_path / 'missing', tmp_path,
                         native_options={'JWT_PRIVATE_KEY_FILE': str(private)})
    assert all(current == before for current, before in zip(file_snapshot(private), original, strict=True))
    assert not (tmp_path / 'app.env').exists()


def file_snapshot(path):
    import stat

    info = path.stat()
    return path.read_bytes(), info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)


@pytest.mark.parametrize('kind', ['invalid', 'mismatched'])
def test_rejected_signing_pair_preserves_both_files_metadata_and_bytes(tmp_path, kind):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    config = load('configure-env')
    private, public = tmp_path / 'private.pem', tmp_path / 'public.pem'
    first = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    second = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private.write_bytes(b'root-sensitive fixture' if kind == 'invalid' else first.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public.write_bytes(second.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    private.chmod(0o640)
    public.chmod(0o644)
    original = [file_snapshot(path) for path in (private, public)]
    with pytest.raises(ValueError):
        config.configure(tmp_path / 'app.env', 'example.test', tmp_path / 'missing', tmp_path,
                         native_options={'JWT_PRIVATE_KEY_FILE': str(private), 'JWT_PUBLIC_KEY_FILE': str(public)})
    assert all(file_snapshot(path) == before for path, before in zip((private, public), original, strict=True))
    assert not (tmp_path / 'app.env').exists()
    assert not (tmp_path / 'admin-password').exists()


@pytest.mark.parametrize('source', ['output', 'legacy'])
@pytest.mark.parametrize('kind', ['service_owned', 'group_writable', 'symlink'])
def test_untrusted_environment_rejected_before_key_or_output_mutation(tmp_path, source, kind):
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if os.geteuid() != 0:
        pytest.skip('Privileged environment trust check requires root')
    config = load('configure-env')
    output, legacy = tmp_path / 'output.env', tmp_path / 'legacy.env'
    selected = output if source == 'output' else legacy
    sensitive = tmp_path / 'root-sensitive'
    public = tmp_path / 'root-public'
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sensitive.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    sensitive.chmod(0o600)
    public.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    public.chmod(0o600)
    selected.write_text(f'DATA_DIR={tmp_path}/redirected\nJWT_PRIVATE_KEY_FILE={sensitive}\nJWT_PUBLIC_KEY_FILE={public}\n')
    selected.chmod(0o600)
    if kind == 'service_owned':
        os.chown(selected, 10001, 10001)
    elif kind == 'group_writable':
        selected.chmod(0o660)
    elif kind == 'symlink':
        selected.rename(tmp_path / 'linked.env')
        selected.symlink_to(tmp_path / 'linked.env')
    original = [file_snapshot(path) for path in (sensitive, public)]
    env_before = selected.read_bytes()
    with pytest.raises((ValueError, OSError)):
        config.configure(output, 'example.test', legacy, tmp_path, 'native')
    assert all(file_snapshot(path) == before for path, before in zip((sensitive, public), original, strict=True))
    assert selected.read_bytes() == env_before
    if source == 'legacy':
        assert not output.exists()
    assert not (tmp_path / 'redirected').exists()
    assert not (tmp_path / 'data').exists()
    assert not (tmp_path / 'admin-password').exists()


def test_legacy_environment_fifo_rejected_without_blocking(tmp_path):
    import os
    import subprocess
    import sys

    legacy = tmp_path / 'legacy.env'
    os.mkfifo(legacy, 0o600)
    result = subprocess.run([sys.executable, str(SCRIPTS / 'configure-env.py'), '--output', str(tmp_path / 'output.env'),
                             '--legacy', str(legacy), '--root', str(tmp_path)],
                            capture_output=True, text=True, timeout=3)
    assert result.returncode != 0
    assert not (tmp_path / 'output.env').exists()
    assert not (tmp_path / 'keys').exists()


def test_root_legacy_0640_upgrades_canonical_to_private_and_preserves_source(tmp_path):
    import os

    if os.geteuid() != 0:
        pytest.skip('Root-owned legacy upgrade requires root')
    config = load('configure-env')
    legacy, output = tmp_path / 'legacy.env', tmp_path / 'canonical.env'
    legacy.write_text('AUTH_SECRET=stable-root-owned-legacy-secret\n')
    legacy.chmod(0o640)
    original = file_snapshot(legacy)
    config.configure(output, 'example.test', legacy, tmp_path, 'native')
    first = config.read_env(output)
    assert first['AUTH_SECRET'] == 'stable-root-owned-legacy-secret'
    assert file_snapshot(legacy) == original
    assert output.stat().st_uid == 0 and output.stat().st_mode & 0o777 == 0o600
    # Older installers also wrote the canonical path with root-owned0640.
    output.chmod(0o640)
    config.configure(output, 'example.test', output, tmp_path, 'native')
    assert config.read_env(output) == first
    assert output.stat().st_mode & 0o777 == 0o600


def test_key_write_rejects_parent_swapped_to_symlink_after_preflight(tmp_path, monkeypatch):
    config = load('configure-env')
    parent = tmp_path / 'keys'
    parent.mkdir()
    victim = tmp_path / 'victim'
    victim.mkdir()
    target = victim / 'key.pem'
    target.write_bytes(b'preserve unrelated file')
    key = parent / 'key.pem'
    check = config.checked_path

    def swap_after_check(raw):
        checked = check(raw)
        parent.rename(tmp_path / 'original-keys')
        parent.symlink_to(victim, target_is_directory=True)
        return checked

    monkeypatch.setattr(config, 'checked_path', swap_after_check)
    with pytest.raises(OSError):
        config.write_private(key, b'new signing material', 10001, 10001)
    assert target.read_bytes() == b'preserve unrelated file'


def test_native_backup_uses_protected_destination_and_can_restore_database(tmp_path, admin_databases):
    config = load('configure-env')
    admin = load('data-admin')
    env = tmp_path / 'app.env'
    config.configure(env, 'example.test', tmp_path / 'missing', tmp_path)
    (tmp_path / 'data').mkdir()
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
    target.chmod(0o600)
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
