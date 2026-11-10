from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from test_deploy import load


@pytest.fixture(scope='module')
def parsed_hba_cluster():
    binaries = Path('/usr/lib/postgresql/16/bin')
    if not (binaries / 'initdb').is_file():
        pytest.skip('Requires PostgreSQL16 server tools in the isolated Linux test runner')
    import pwd
    postgres = pwd.getpwnam('postgres')
    with tempfile.TemporaryDirectory(prefix='tdl-hba-review-') as temporary:
        root = Path(temporary)
        root.chmod(0o755)
        data, sockets = root / 'data', root / 'sockets'
        for directory in (data, sockets):
            directory.mkdir(mode=0o700)
            os.chown(directory, postgres.pw_uid, postgres.pw_gid)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        def run(tool, *args, **kwargs):
            return subprocess.run(['runuser', '-u', 'postgres', '--', str(binaries / tool), *args],
                                  check=True, capture_output=True, text=True, timeout=20, **kwargs)
        run('initdb', '-D', str(data), '--no-locale', '--encoding=UTF8', '--auth-local=peer', '--auth-host=scram-sha-256')
        run('pg_ctl', '-D', str(data), '-l', str(data / 'server.log'), '-w', 'start', '-o',
            f'-c listen_addresses=127.0.0.1 -c port={port} -c unix_socket_directories={sockets}')
        try:
            def query(statement):
                sql = statement.as_string() if hasattr(statement, 'as_string') else statement
                return run('psql', '-h', str(sockets), '-p', str(port), '-d', 'postgres',
                           '-X', '-At', '-v', 'ON_ERROR_STOP=1', input=sql).stdout.strip()
            yield data / 'pg_hba.conf', query, port
        finally:
            run('pg_ctl', '-D', str(data), '-m', 'immediate', '-w', 'stop')


@pytest.mark.parametrize('database,user,method,reject', [
    ('/^tdl_', 'all', 'trust', True),
    ('all', '/^tdl_', 'trust', True),
    ('/^tdl_', '/^tdl_', 'trust', True),
    ('/^unrelated_', 'all', 'trust', True),
    ('/^tdl_', '/^tdl_', 'scram-sha-256', False),
    ('unrelated', 'all', 'trust', False),
])
def test_provision_checks_actual_parsed_hba_selectors(parsed_hba_cluster, tmp_path, monkeypatch,
                                                     database, user, method, reject):
    native = load('native-postgres')
    hba, query, port = parsed_hba_cluster
    hba.write_text(f'local all postgres peer\nhost {database} {user} 127.0.0.1/32 {method}\n'
                   'host all all 127.0.0.1/32 scram-sha-256\n')
    parsed = json.loads(query("SELECT row_to_json(r) FROM pg_hba_file_rules r WHERE line_number=2;"))
    assert parsed['error'] is None
    assert parsed['database'] == [database] and parsed['user_name'] == [user]
    identifier = str(uuid4())
    name = 'tdl_' + identifier.replace('-', '')
    monkeypatch.setattr(native, 'psql', lambda cluster, statement: query(statement))
    values = {'INSTALLATION_ID': identifier,
              'DATABASE_URL': f'postgresql://{name}:disposable-test@127.0.0.1:{port}/{name}'}
    if reject:
        with pytest.raises(RuntimeError, match='trust'):
            native.provision(values, ('16', 'review', str(port)), tmp_path / 'journal.json')
        assert query(f"SELECT count(*) FROM pg_roles WHERE rolname='{name}';") == '0'
        assert not (tmp_path / 'journal.json').exists()
    else:
        native.provision(values, ('16', 'review', str(port)), tmp_path / 'journal.json')
        assert native.verify_target(values, fresh=True) == 16


@pytest.mark.parametrize('query', ['', '?sslmode=require', '?sslmode=verify-full'])
def test_native_remote_requires_verified_tls_before_any_command(query, monkeypatch):
    native = load('native-postgres')
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Invalid URL reached command'))
    with pytest.raises(ValueError, match='verify-full'):
        native.validate_url({'DATABASE_URL': 'postgresql://app:secret@remote.test/app' + query})


def test_native_runtime_filters_all_root_maintenance_credentials(tmp_path):
    native = load('native-postgres')
    source, target, web = tmp_path / 'source.env', tmp_path / 'runtime.env', tmp_path / 'web.env'
    source.write_text('DATABASE_URL=postgresql://app:pw@127.0.0.1/app\nAUTH_SECRET=session\n'
                      'AUTH_URL=https://tld.test\nAPI_INTERNAL_URL=http://127.0.0.1:8000\n'
                      'TDL_POSTGRES_ADMIN_PASSWORD=maintenance\nTDL_POSTGRES_PASSWORD=duplicate\n'
                      'ADMIN_PASSWORD_FILE=/root/admin\nPG_PASS=legacy\nUNKNOWN_SECRET=hidden\n'
                      'RQ_QUEUE_NAME=tdl-unique-downloads\nJWT_PRIVATE_KEY_FILE=/data/key\n')
    source.chmod(0o600)
    native.runtime_environment(source, target, web)
    result = target.read_text()
    assert 'DATABASE_URL=' in result and 'AUTH_SECRET=session' in result
    assert 'RQ_QUEUE_NAME=tdl-unique-downloads' in result
    assert all(secret not in result for secret in ('maintenance', 'duplicate', '/root/admin', 'legacy', 'hidden'))
    assert target.stat().st_mode & 0o777 == 0o600
    web_result = web.read_text()
    assert 'AUTH_SECRET=session' in web_result and 'AUTH_URL=https://tld.test' in web_result
    assert 'API_INTERNAL_URL=http://127.0.0.1:8000' in web_result
    assert all(name not in web_result for name in ('DATABASE_URL', 'JWT_PRIVATE_KEY_FILE', 'RQ_QUEUE_NAME', 'TDL_'))
    assert web.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('statement', ['CREATE TABLE keep_me (id integer)', 'SELECT lo_create(0)'])
def test_fresh_rejects_actual_nonempty_target(admin_databases, statement):
    native = load('native-postgres')
    engine = create_engine(admin_databases[0])
    with engine.begin() as db:
        db.execute(text(statement))
    engine.dispose()
    with pytest.raises(RuntimeError, match='vac'):
        native.verify_target({'DATABASE_URL': admin_databases[0]}, fresh=True, check_role=False)


def test_provision_only_journaled_uuid_role_and_database(tmp_path, monkeypatch):
    native = load('native-postgres')
    identifier = str(uuid4())
    name = 'tdl_' + identifier.replace('-', '')
    values = {'INSTALLATION_ID': identifier, 'DATABASE_URL': f'postgresql://{name}:secret@127.0.0.1/{name}'}
    calls = []
    state = {'role': False, 'database': False}

    def psql(cluster, statement):
        query = statement.as_string() if hasattr(statement, 'as_string') else statement
        calls.append(query)
        if 'listen_addresses' in query:
            return 'localhost'
        if 'pg_hba_file_rules' in query:
            return '0'
        if 'FROM pg_roles' in query:
            return ('tdl:' + identifier) if state['role'] else ''
        if 'FROM pg_database' in query:
            return name if state['database'] else ''
        if 'CREATE ROLE' in query:
            state['role'] = True
        if 'CREATE DATABASE' in query:
            state['database'] = True
        return ''

    monkeypatch.setattr(native, 'psql', psql)
    journal = tmp_path / 'resources.json'
    native.provision(values, ('16', 'main', '5432'), journal)
    first = len(calls)
    native.provision(values, ('16', 'main', '5432'), journal)
    assert not any('CREATE ' in query for query in calls[first:])
    assert any('NOSUPERUSER NOCREATEDB NOCREATEROLE' in query for query in calls)
    assert not any(word in '\n'.join(calls) for word in ('ALTER ROLE', 'DROP ', 'postgres PASSWORD'))
    assert json.loads(journal.read_text())['database_created'] is True
    assert journal.stat().st_mode & 0o777 == 0o600
    journal.unlink()
    with pytest.raises(RuntimeError, match='colisi'):
        native.provision(values, ('16', 'main', '5432'), journal)


def test_psql_password_stays_in_stdin_and_not_environment(monkeypatch):
    native = load('native-postgres')
    seen = []
    monkeypatch.setenv('TDL_POSTGRES_ADMIN_PASSWORD', 'must-not-leak')
    def run(args, **kwargs):
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, 'ok\n', '')
    monkeypatch.setattr(subprocess, 'run', run)
    native.psql(('16', 'main', '5432'), "SELECT 'stdin-secret';")
    args, kwargs = seen[0]
    assert 'stdin-secret' not in ' '.join(args)
    assert kwargs['input'] == "SELECT 'stdin-secret';"
    assert 'TDL_POSTGRES_ADMIN_PASSWORD' not in kwargs['env']
    assert '-X' in args and 'ON_ERROR_STOP=1' in args


def test_existing_cluster_discovery_never_reconfigures_or_installs(monkeypatch):
    native = load('native-postgres')
    calls = []
    monkeypatch.setattr(native.shutil, 'which', lambda name: '/usr/bin/' + name)
    def command(args, **kwargs):
        calls.append(args)
        if args[0] == 'pg_lsclusters':
            return '17 shared 5432 online postgres /custom/data /custom/log\n16 other 5433 online postgres /other /log'
        return '1'
    monkeypatch.setattr(native, 'command', command)
    assert native.local_cluster(5432) == ('17', 'shared', '5432')
    assert not any(args[0] in {'apt-get', 'systemctl', 'pg_ctlcluster'} for args in calls)


def test_sql_quoting_never_turns_password_into_commands(tmp_path, monkeypatch):
    from urllib.parse import quote
    native = load('native-postgres')
    identifier = str(uuid4())
    name = 'tdl_' + identifier.replace('-', '')
    password = "p'; DROP DATABASE foreign; --\\secret"
    values = {'INSTALLATION_ID': identifier,
              'DATABASE_URL': f'postgresql://{name}:{quote(password, safe="")}@127.0.0.1/{name}'}
    calls = []
    def psql(cluster, statement):
        query = statement.as_string() if hasattr(statement, 'as_string') else statement
        calls.append(query)
        if 'listen_addresses' in query:
            return 'localhost'
        return '0' if 'pg_hba_file_rules' in query else ''
    monkeypatch.setattr(native, 'psql', psql)
    native.provision(values, ('16', 'main', '5432'), tmp_path / 'journal.json')
    create = next(query for query in calls if 'CREATE ROLE' in query)
    assert "p''; DROP DATABASE foreign; --" in create
    assert f'CREATE ROLE "{name}"' in create


def test_native_checks_limited_role_and_owner_with_real_postgres(admin_databases):
    from sqlalchemy.engine import make_url
    native = load('native-postgres')
    url = make_url(admin_databases[0])
    role = 'tdl_native_test_' + uuid4().hex
    control = create_engine(url, isolation_level='AUTOCOMMIT')
    try:
        with control.connect() as db:
            db.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD 'disposable-test'"))
            db.execute(text(f'ALTER DATABASE "{url.database}" OWNER TO {role}'))
        target = url.set(username=role, password='disposable-test').render_as_string(hide_password=False)
        assert native.verify_target({'DATABASE_URL': target}, fresh=True) >= 16
        with control.connect() as db:
            db.execute(text(f'ALTER ROLE {role} CREATEDB'))
        with pytest.raises(RuntimeError, match='privilegios'):
            native.verify_target({'DATABASE_URL': target})
    finally:
        with control.connect() as db:
            db.execute(text(f'ALTER DATABASE "{url.database}" OWNER TO "{url.username}"'))
            db.execute(text(f'DROP ROLE {role}'))
        control.dispose()


@pytest.mark.parametrize('addresses,trust', [('*', '0'), ('0.0.0.0', '0'), ('localhost', '1')])
def test_local_access_rejects_exposed_or_trust_before_creation(tmp_path, monkeypatch, addresses, trust):
    native = load('native-postgres')
    identifier = str(uuid4())
    name = 'tdl_' + identifier.replace('-', '')
    def psql(cluster, statement):
        query = statement.as_string() if hasattr(statement, 'as_string') else statement
        if 'listen_addresses' in query:
            return addresses
        if 'pg_hba_file_rules' in query:
            return trust
        if 'CREATE ' in query:
            pytest.fail('Unsafe cluster reached resource creation')
        return ''
    monkeypatch.setattr(native, 'psql', psql)
    with pytest.raises(RuntimeError, match='loopback|trust'):
        native.provision({'INSTALLATION_ID': identifier,
                          'DATABASE_URL': f'postgresql://{name}:secret@localhost/{name}'},
                         ('16', 'shared', '5432'), tmp_path / 'journal.json')
