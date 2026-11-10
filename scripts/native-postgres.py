"""Native installer operations; privileged inputs are literal, protected files."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from psycopg import sql
from sqlalchemy import create_engine, text

spec = importlib.util.spec_from_file_location('data_admin', Path(__file__).with_name('data-admin.py'))
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)
config = admin.config
RUNTIME_KEYS = set('''APP_ENV APP_VERSION DATA_DIR TDL_SESSIONS_DIR EXPORTS_DIR DOWNLOADS_DIR LOGS_DIR TMP_DIR
DATABASE_URL REDIS_URL RQ_QUEUE_NAME JWT_PRIVATE_KEY_FILE JWT_PUBLIC_KEY_FILE TDL_BINARY TDL_NAMESPACE
COMMAND_TIMEOUT_SECONDS DOWNLOAD_BATCH_SIZE DOWNLOAD_IDLE_TIMEOUT_SECONDS EXPORT_BATCH_SIZE TRUSTED_HOSTS
ENABLE_DOCS AUTHENTIK_ENABLED AUTHENTIK_ISSUER AUTHENTIK_AUDIENCE AUTHENTIK_JWKS_URL AUTHENTIK_ADMIN_GROUP
AUTHENTIK_CLIENT_ID AUTHENTIK_CLIENT_SECRET AUTH_SECRET AUTH_URL AUTH_TRUST_HOST API_INTERNAL_URL'''.split())


def runtime_environment(source, destination):
    values = config.read_env(source, privileged=True)
    config.write_private(destination, ''.join(f'{name}={config.encode_value(value)}\n'
                                             for name, value in values.items() if name in RUNTIME_KEYS))


def validate_url(values):
    url = admin.database_url(values)
    if url.host not in {'127.0.0.1', 'localhost', '::1'}:
        ca = url.query.get('sslrootcert', '')
        if url.query.get('sslmode') != 'verify-full' or not ca or not Path(ca).is_file():
            raise ValueError('PostgreSQL remoto requiere sslmode=verify-full y sslrootcert CA existente')
        config.checked_path(ca)
        config.trusted_parent(Path(ca))
    return url


def command(args, *, input=None):
    try:
        return subprocess.run(args, input=input, check=True, capture_output=True, text=True,
                              env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C',
                                   'DEBIAN_FRONTEND': 'noninteractive'}).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        raise RuntimeError('Operación PostgreSQL nativa fallida; no se modifican recursos ajenos') from None


def psql(cluster, statement):
    version, name, port = cluster
    # Debian's wrapper discovers the selected cluster's socket/config, including custom paths.
    return command(['runuser', '-u', 'postgres', '--', 'psql', '--cluster', f'{version}/{name}',
                    '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-d', 'postgres'],
                   input=statement.as_string() if hasattr(statement, 'as_string') else statement)


def local_cluster(port):
    rows = command(['pg_lsclusters', '--no-header']).splitlines() if shutil.which('pg_lsclusters') else []
    existing = bool(rows)
    if not rows:
        command(['apt-get', 'update'])
        command(['apt-get', 'install', '-y', '--no-install-recommends', '--no-upgrade',
                 'postgresql', 'postgresql-client'])
        rows = command(['pg_lsclusters', '--no-header']).splitlines()
    matches = [row.split()[:3] for row in rows if len(row.split()) >= 4 and row.split()[2] == str(port)]
    if len(matches) != 1 or int(matches[0][0]) < 16:
        raise RuntimeError('Se requiere un cluster PostgreSQL 16+ en el puerto indicado; use DATABASE_URL explícita')
    cluster = tuple(matches[0])
    # Do not restart, stop, reconfigure or change HBA on a shared cluster.
    psql(cluster, 'SELECT 1;')
    if not existing:
        addresses = psql(cluster, 'SHOW listen_addresses;')
        if not set(address.strip() for address in addresses.split(',')) <= {'localhost', '127.0.0.1', '::1'}:
            raise RuntimeError('El nuevo PostgreSQL debe escuchar solo loopback; no se publica la aplicación')
    return cluster


def provision(values, cluster, journal):
    url = validate_url(values)
    identifier = str(UUID(values['INSTALLATION_ID']))
    expected = 'tdl_' + UUID(identifier).hex
    if url.host not in {'127.0.0.1', 'localhost', '::1'} or url.username != expected or url.database != expected:
        raise ValueError('Solo se provisionan nombres UUID dedicados a esta instalación')
    addresses = psql(cluster, 'SHOW listen_addresses;')
    if not set(address.strip() for address in addresses.split(',')) <= {'localhost', '127.0.0.1', '::1'}:
        raise RuntimeError('El cluster local debe escuchar solo loopback; no se cambia su configuración compartida')
    trust = psql(cluster, sql.SQL("""SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL OR (
        auth_method='trust' AND database && ARRAY['all','sameuser','samerole','samegroup',{}]
        AND user_name && ARRAY['all',{}])""").format(sql.Literal(expected), sql.Literal(expected)))
    if trust != '0':
        raise RuntimeError('Reglas HBA trust o inválidas para la aplicación; configure acceso específico autenticado')
    role = psql(cluster, sql.SQL("SELECT coalesce(shobj_description(oid, 'pg_authid'), '') FROM pg_roles WHERE rolname={}").format(sql.Literal(expected)))
    database = psql(cluster, sql.SQL('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname={}').format(sql.Literal(expected)))
    saved = None
    if journal.exists():
        config.checked_path(journal)
        config.trusted_parent(journal)
        with config.regular_file(journal) as stream:
            metadata = os.fstat(stream.fileno())
            if metadata.st_uid != 0 or metadata.st_mode & 0o077:
                raise ValueError('Journal PostgreSQL debe ser privado y propiedad de root')
            saved = json.loads(config.bounded_bytes(stream))
    identity = {'installation_id': identifier, 'role': expected, 'database': expected, 'cluster': list(cluster)}
    if saved is not None and any(saved.get(key) != value for key, value in identity.items()):
        raise RuntimeError('Journal no corresponde al cluster/destino; recuperación manual requerida')
    # Empty comments must still count as an existing role: query presence separately.
    present = psql(cluster, sql.SQL('SELECT rolname FROM pg_roles WHERE rolname={}').format(sql.Literal(expected)))
    if (present or database) and saved is None:
        raise RuntimeError('colisión de rol/base existente sin journal; use DATABASE_URL propia')
    if present and role != 'tdl:' + identifier or database and database != expected:
        raise RuntimeError('colisión de recursos ajenos; no se cambia su contraseña ni se borran')
    state = saved or identity
    def save():
        config.write_private(journal, json.dumps(state, indent=2) + '\n')
    save()
    if not present:
        state['role_pending'] = True
        save()
        psql(cluster, sql.SQL("BEGIN; SET LOCAL password_encryption='scram-sha-256'; CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}; COMMENT ON ROLE {} IS {}; COMMIT;").format(
            sql.Identifier(expected), sql.Literal(url.password), sql.Identifier(expected), sql.Literal('tdl:' + identifier)))
    state['role_created'] = True
    save()
    if not database:
        state['database_pending'] = True
        save()
        psql(cluster, sql.SQL('CREATE DATABASE {} OWNER {} TEMPLATE template0;').format(sql.Identifier(expected), sql.Identifier(expected)))
    psql(cluster, sql.SQL('REVOKE ALL ON DATABASE {} FROM PUBLIC;').format(sql.Identifier(expected)))
    state['database_created'] = True
    save()


def verify_target(values, *, fresh=False, check_role=True):
    engine = create_engine(admin.database_url(values))
    try:
        with engine.connect() as db:
            major = int(db.execute(text('SHOW server_version_num')).scalar_one()) // 10000
            if major < 16:
                raise RuntimeError('Se requiere PostgreSQL 16 o posterior')
            if fresh:
                admin.require_empty(db)
            if check_role:
                unsafe = db.execute(text('''SELECT r.rolsuper OR r.rolcreatedb OR r.rolcreaterole OR r.rolreplication OR r.rolbypassrls
                    OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=r.oid)
                    OR r.oid<>(SELECT datdba FROM pg_database WHERE datname=current_database())
                    FROM pg_roles r WHERE r.rolname=current_user''')).scalar_one()
                if unsafe:
                    raise RuntimeError('El rol de aplicación debe ser propietario dedicado sin privilegios administrativos ni membresías')
            return major
    finally:
        engine.dispose()


def prepare(env_file, journal_root, *, fresh=False):
    values = config.read_env(env_file, privileged=True)
    url = validate_url(values)
    name = 'tdl_' + UUID(values['INSTALLATION_ID']).hex
    if url.host in {'127.0.0.1', 'localhost', '::1'} and url.username == name and url.database == name:
        cluster = local_cluster(url.port)
        provision(values, cluster, journal_root / (name + '.json'))
    major = verify_target(values, fresh=fresh)
    if not Path(f'/usr/lib/postgresql/{major}/bin/pg_dump').is_file():
        command(['apt-get', 'update'])
        command(['apt-get', 'install', '-y', '--no-install-recommends', '--no-upgrade', f'postgresql-client-{major}'])
    admin.pg_versions(values, 'pg_dump')
    admin.pg_versions(values, 'pg_restore')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'runtime'])
    parser.add_argument('--env', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--fresh', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'runtime':
            runtime_environment(args.env, args.output)
        else:
            prepare(args.env, args.output, fresh=args.fresh)
    except Exception as error:
        if isinstance(error, (ValueError, RuntimeError)):
            print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
