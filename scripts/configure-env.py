"""Prepare protected local-auth configuration without touching old databases or jobs."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip()
        if value.startswith(('"', "'")):
            parts = shlex.split(value, comments=False)
            if len(parts) != 1:
                raise ValueError(f'Invalid quoted value for {key}')
            value = parts[0]
        values[key.strip()] = value
    return values


def encode_value(value: str) -> str:
    if any(char in value for char in '\n\r\0'):
        raise ValueError('Environment values must fit on one line')
    if any(char.isspace() or char in '\\"\'' for char in value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value


def checked_path(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('Secret paths must be absolute without parent traversal')
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('Secret paths must not contain a symlink')
    if path.exists() and not path.is_file():
        raise ValueError('Secret path must name a regular file')
    return path


def trusted_parent(path: Path, key_uid: int = 0) -> None:
    if os.geteuid() != 0:
        return
    for item in path.parents:
        if not item.exists():
            continue
        metadata = item.stat()
        if item != path.parent and metadata.st_mode & 0o1000:
            continue
        if metadata.st_uid not in {0, key_uid} or metadata.st_mode & 0o022:
            raise ValueError('Secret directories must be root-owned and not writable by other users')


def parent_fd(path: Path, *, create: bool = False) -> int:
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:-1]:
            if create:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=directory)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return directory
    except BaseException:
        os.close(directory)
        raise


def write_private(path: Path, content: str | bytes, uid: int = 0, gid: int = 0) -> None:
    checked_path(path)
    trusted_parent(path, uid)
    directory = parent_fd(path, create=True)
    temporary = '.tdl-' + secrets.token_hex(16)
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content.encode() if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o600)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), uid, gid)
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def key_bytes(path: Path, uid: int, gid: int) -> bytes:
    directory = parent_fd(path)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError('JWT key files must be regular files')
            raw = stream.read(65537)
            if len(raw) > 65536:
                raise ValueError('JWT key file is too large')
            os.fchmod(stream.fileno(), 0o600)
            if os.geteuid() == 0:
                os.fchown(stream.fileno(), uid, gid)
            return raw
    finally:
        os.close(directory)


def openssl(*args: str, content: bytes | None = None) -> bytes:
    result = subprocess.run(['openssl', *args], input=content, capture_output=True)
    if result.returncode:
        raise ValueError('JWT key generation/validation failed')
    return result.stdout


def prepare_keys(private: Path, public: Path, uid: int, gid: int) -> None:
    if private == public:
        raise ValueError('JWT key files must be distinct')
    if public.exists() and not private.exists():
        raise ValueError('JWT private key missing; restore the original key pair')
    raw = key_bytes(private, uid, gid) if private.exists() else openssl(
        'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048')
    openssl('rsa', '-check', '-noout', content=raw)
    derived = openssl('pkey', '-pubout', content=raw)
    description = openssl('pkey', '-text_pub', '-noout', content=raw).decode()
    bits = re.search(r'Public-Key: \((\d+) bit\)', description)
    if not bits or int(bits[1]) < 2048:
        raise ValueError('JWT keys must use RSA with at least 2048 bits')
    if public.exists() and key_bytes(public, uid, gid) != derived:
        raise ValueError('JWT key files do not match; restore the original key pair')
    if not private.exists():
        write_private(private, raw, uid, gid)
    if not public.exists():
        write_private(public, derived, uid, gid)


def database_identity(raw: str) -> tuple:
    try:
        url = urlsplit(raw)
        if url.scheme not in {'postgresql', 'postgresql+psycopg'} or not all(
            (url.hostname, url.username, url.password, url.path.lstrip('/'))
        ):
            raise ValueError
        return url.hostname.lower(), url.port or 5432, unquote(url.path.lstrip('/'))
    except ValueError:
        raise ValueError('DATABASE_URL must name a PostgreSQL host, user, password and database') from None


def enabled(value) -> bool:
    normalized = str(value).strip().lower()
    if normalized not in {'true', 'false'}:
        raise ValueError('AUTHENTIK_ENABLED must be true or false')
    return normalized == 'true'


def configure(output: Path, domain: str, legacy: Path, root: Path, deployment: str = 'docker',
              native_options: dict | None = None) -> None:
    if not re.fullmatch(r'(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?', domain):
        raise ValueError('DOMAIN must be a hostname without a scheme, path or port')
    checked_path(output)
    trusted_parent(output)
    options = native_options or {}
    previous = {**read_env(legacy), **read_env(output)}
    fresh = str(options.get('FRESH', False)).lower() in {'true', '1'}
    data = previous.get('DATA_DIR') or str(root / 'data')
    if not Path(data).is_absolute():
        raise ValueError('DATA_DIR must be absolute')
    prior_database = previous.get('DATABASE_URL', '')
    legacy_sqlite = prior_database.startswith('sqlite:') or (not prior_database and any(
        (Path(data) / name).exists() for name in ('telegram_downloader.sqlite3', 'database.sqlite3')))
    if legacy_sqlite and not fresh:
        raise ValueError('Legacy SQLite requires explicit --fresh; old data will be preserved')
    values = {
        'DATA_DIR': data, 'TDL_SESSIONS_DIR': f'{data}/sessions', 'EXPORTS_DIR': f'{data}/exports',
        'DOWNLOADS_DIR': f'{data}/downloads', 'LOGS_DIR': f'{data}/logs', 'DOMAIN': domain,
        'AUTH_URL': f'https://{domain}', 'AUTHENTIK_ENABLED': 'false',
        'TLS_DIR': '/etc/telegram-downloader/certs', 'TDL_NAMESPACE': 'default',
        'COMMAND_TIMEOUT_SECONDS': '7200', 'DOWNLOAD_BATCH_SIZE': '100',
        'DOWNLOAD_IDLE_TIMEOUT_SECONDS': '600', 'EXPORT_BATCH_SIZE': '5000',
        'APP_UID': os.getenv('APP_UID', '10001'), 'APP_GID': os.getenv('APP_GID', '10001'),
        'ADMIN_USERNAME': 'admin', 'APP_VERSION': os.getenv('APP_VERSION', 'local'),
    }
    if deployment == 'native':
        values.update({
            'APP_ENV': 'production', 'API_INTERNAL_URL': 'http://127.0.0.1:8000',
            'NATIVE_INGRESS': os.getenv('NATIVE_INGRESS', 'direct'),
            'REDIS_URL': 'redis://127.0.0.1:6379/1', 'TRUSTED_HOSTS': '127.0.0.1,localhost',
            'TDL_BINARY': str(root / 'bin' / 'tdl'), 'TMP_DIR': str(root / 'tmp'),
            'LOGS_DIR': str(root / 'logs'),
        })
    values.update(previous)
    allowed = {
        'APP_ROOT', 'APP_HOST', 'APP_ALLOWED_SUBNET', 'APP_PORT', 'API_PORT', 'APP_USER', 'INSTALL_REDIS',
        'PUBLIC_URL', 'AUTH_URL', 'REDIS_URL', 'CONFIG_DIR', 'BACKUPS_DIR', 'LOGS_DIR', 'APP_UID', 'APP_GID',
        'SERVICE_WEB', 'SERVICE_API', 'SERVICE_WORKER', 'SERVICE_NETWORK', 'NODE_BINARY', 'TDL_BINARY',
        'RESOLVED_METHOD', 'DATABASE_URL', 'AUTHENTIK_ENABLED', 'JWT_PRIVATE_KEY_FILE', 'JWT_PUBLIC_KEY_FILE',
        'RQ_QUEUE_NAME', 'ADMIN_USERNAME', 'ADMIN_PASSWORD_FILE',
    }
    for name in allowed:
        if name in options:
            values[name] = str(options[name])
        elif name in {'AUTHENTIK_ENABLED', 'AUTH_URL', 'DATABASE_URL', 'ADMIN_USERNAME', 'ADMIN_PASSWORD_FILE'} and os.getenv(name):
            values[name] = os.environ[name]
    if deployment == 'native' and native_options:
        values['API_INTERNAL_URL'] = f"http://127.0.0.1:{values.get('API_PORT', '8000')}"
        values['APP_VERSION'] = options.get('RESOLVED_VERSION', 'local')
    for name in ('AUTH_SECRET', 'TDL_POSTGRES_PASSWORD', 'TDL_POSTGRES_ADMIN_PASSWORD'):
        if not values.get(name) or values[name].startswith(('replace-', 'change-')):
            values[name] = secrets.token_hex(32)
    if values['TDL_POSTGRES_PASSWORD'] == values['TDL_POSTGRES_ADMIN_PASSWORD']:
        raise ValueError('TDL_POSTGRES_PASSWORD and TDL_POSTGRES_ADMIN_PASSWORD must be distinct')
    identifier = str(UUID(str(options.get('FRESH_INSTALLATION_ID') or uuid4()))) if fresh else str(
        UUID(previous['INSTALLATION_ID']) if previous.get('INSTALLATION_ID') else uuid4())
    values['INSTALLATION_ID'] = identifier
    if fresh or not values.get('RQ_QUEUE_NAME'):
        values['RQ_QUEUE_NAME'] = f'tdl-{identifier}-downloads'
    if deployment == 'docker' and (fresh or not values.get('COMPOSE_PROJECT_NAME')):
        values['COMPOSE_PROJECT_NAME'] = f'tdl-{identifier}'
    explicit_database = options.get('DATABASE_URL') or os.getenv('DATABASE_URL')
    old_database = previous.get('DATABASE_URL', '')
    if fresh or not old_database:
        if explicit_database:
            if fresh and old_database.startswith(('postgresql:', 'postgresql+psycopg:')) and (
                database_identity(str(explicit_database)) == database_identity(old_database)
            ):
                raise ValueError('--fresh requires a new empty DATABASE_URL target')
            values['DATABASE_URL'] = str(explicit_database)
        else:
            name = f'tdl_{UUID(identifier).hex}' if deployment == 'native' else 'tdl'
            host = '127.0.0.1' if deployment == 'native' else 'tdl-postgres'
            values['DATABASE_URL'] = f"postgresql+psycopg://{name}:{values['TDL_POSTGRES_PASSWORD']}@{host}:5432/{name}"
    database_identity(values['DATABASE_URL'])
    provider = enabled(values['AUTHENTIK_ENABLED'])
    values['AUTHENTIK_ENABLED'] = str(provider).lower()
    provider_names = ('AUTHENTIK_ISSUER', 'AUTHENTIK_CLIENT_ID', 'AUTHENTIK_CLIENT_SECRET',
                      'AUTHENTIK_AUDIENCE', 'AUTHENTIK_JWKS_URL', 'AUTHENTIK_ADMIN_GROUP')
    if provider:
        for name in provider_names:
            if name in options or os.getenv(name):
                values[name] = str(options.get(name, os.getenv(name)))
        issuer = values.get('AUTHENTIK_ISSUER', '')
        values['AUTHENTIK_AUDIENCE'] = values.get('AUTHENTIK_AUDIENCE') or values.get('AUTHENTIK_CLIENT_ID', '')
        values['AUTHENTIK_JWKS_URL'] = values.get('AUTHENTIK_JWKS_URL') or (issuer.rstrip('/') + '/jwks/' if issuer else '')
        values['AUTHENTIK_ADMIN_GROUP'] = values.get('AUTHENTIK_ADMIN_GROUP') or 'tdl-admin'
        missing = [name for name in provider_names if not values.get(name) or values[name].startswith(('replace-', 'change-'))]
        if not issuer.startswith('https://') and 'AUTHENTIK_ISSUER' not in missing:
            missing.append('AUTHENTIK_ISSUER')
        if missing:
            raise ValueError('Incomplete enabled provider: ' + ', '.join(missing))
    else:
        for name in provider_names:
            values.pop(name, None)
    if deployment == 'native':
        for name in ('PG_PASS', 'AUTHENTIK_SECRET_KEY', 'AUTHENTIK_BOOTSTRAP_PASSWORD', 'AUTHENTIK_BOOTSTRAP_EMAIL'):
            values.pop(name, None)
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,63}', values['ADMIN_USERNAME']):
        raise ValueError('ADMIN_USERNAME must be 3-64 lowercase username characters')
    uid, gid = int(values['APP_UID']), int(values['APP_GID'])
    if uid <= 0 or gid <= 0:
        raise ValueError('APP_UID and APP_GID must be unprivileged positive IDs')
    keys = Path(data) / 'keys' if deployment == 'native' else root / 'keys'
    private = checked_path(values.setdefault('JWT_PRIVATE_KEY_FILE', str(keys / 'jwt-private.pem')))
    public = checked_path(values.setdefault('JWT_PUBLIC_KEY_FILE', str(keys / 'jwt-public.pem')))
    config_dir = Path(values.get('CONFIG_DIR') or output.parent)
    password = checked_path(values.setdefault('ADMIN_PASSWORD_FILE', str(config_dir / 'admin-password')))
    trusted_parent(password)
    for path in (private, public):
        trusted_parent(path, uid)
    if len({private, public, password, output}) != 4:
        raise ValueError('Configuration and secret files must use distinct paths')
    # Validate every value before creating any files; secret errors never include values.
    content = ''.join(f'{key}={encode_value(str(value))}\n' for key, value in values.items())
    if password.exists():
        metadata = password.stat()
        if metadata.st_mode & 0o077 or (os.geteuid() == 0 and metadata.st_uid != 0):
            raise ValueError('ADMIN_PASSWORD_FILE must be a root-owned private regular file')
    prepare_keys(private, public, uid, gid)
    if not password.exists():
        initial = getpass.getpass('Contraseña inicial de administrador (Enter genera una temporal): ') if options.get('PROMPT_ADMIN_PASSWORD') else ''
        initial = initial or secrets.token_urlsafe(32)
        if not 12 <= len(initial) <= 128 or any(char in initial for char in '\r\n\0'):
            raise ValueError('Administrator password must contain 12-128 characters on one line')
        write_private(password, initial + '\n')
    write_private(output, content)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--domain', default='localhost')
    parser.add_argument('--native-options', type=Path)
    parser.add_argument('--legacy', type=Path, default=Path('/etc/telegram-downloader/telegram-downloader.env'))
    parser.add_argument('--root', type=Path, default=Path('/opt/tld-web'))
    parser.add_argument('--deployment', choices=['native', 'docker'], default='docker')
    parser.add_argument('--fresh', action='store_true')
    args = parser.parse_args()
    options = json.loads(args.native_options.read_text()) if args.native_options else {}
    if args.fresh:
        options['FRESH'] = True
    try:
        configure(args.output, args.domain, args.legacy, args.root, args.deployment, options)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except OSError:
        # Do not expose file contents, credentials or subprocess diagnostics.
        raise SystemExit('Configuration failed; check private paths, required provider fields and --fresh eligibility.') from None
    password_file = read_env(args.output)['ADMIN_PASSWORD_FILE']
    print(f'Contraseña inicial protegida: {password_file}')
    print(f'Consultar como root: sudo cat -- {shlex.quote(password_file)}')
    print('La cuenta inicial debe cambiarla al entrar; las cuentas existentes se conservan.')
