from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MASTER = ROOT / 'install-tld.sh'
pytestmark = pytest.mark.skipif(os.name == 'nt', reason='Native Bash installer is tested in Linux Docker')


def shell(code, tmp_path, **variables):
    return subprocess.run(['bash', '-c', 'source "$MASTER"\n' + code],
        env={**os.environ, 'MASTER': str(MASTER), 'APP_ROOT': str(tmp_path / 'app-root'),
             'CONFIG_DIR': str(tmp_path / 'etc'), 'SYSTEMD_DIR': str(tmp_path / 'units'),
             **{key: str(value) for key, value in variables.items()}},
        capture_output=True, text=True, timeout=15)


def test_master_dry_run_is_noninteractive_and_tunnel_is_only_reference(tmp_path):
    result = subprocess.run(['bash', str(MASTER), '--dry-run'], input='', text=True,
        capture_output=True, timeout=10,
        env={**os.environ, 'CONFIG_DIR': str(tmp_path / 'etc'), 'APP_ROOT': str(tmp_path / 'app'),
             'PUBLIC_URL': 'https://tld.example.test', 'AUTHENTIK_CLIENT_SECRET': 'never-print-this'})
    assert result.returncode == 0, result.stderr
    assert 'APP_PORT=8080' in result.stdout
    assert 'APP_HOST=127.0.0.1' in result.stdout
    assert 'PUBLIC_URL=https://tld.example.test' in result.stdout
    assert 'AUTH_URL=http://localhost:8080' in result.stdout
    assert 'never-print-this' not in result.stdout + result.stderr
    assert not (tmp_path / 'etc').exists()


def test_saved_defaults_are_read_as_data_not_shell(tmp_path):
    config = tmp_path / 'install.conf'
    marker = tmp_path / 'executed'
    config.write_text(f'APP_PORT=8181\nPUBLIC_URL=\nUNUSED=$(touch {marker})\n')
    result = shell('collect_options\nprint_summary', tmp_path, INSTALL_CONF=config)
    assert result.returncode == 0, result.stderr
    assert 'APP_PORT=8181' in result.stdout
    assert 'PUBLIC_URL=\n' in result.stdout
    assert not marker.exists()


@pytest.mark.parametrize('assignment', ['APP_ROOT=/', 'APP_PORT=70000',
    'PUBLIC_URL=http://example.test', 'APP_USER=root', 'APP_REF=--upload-pack=bad',
    'APP_ROOT=/opt/../etc', 'INSTALL_METHOD=unknown'])
def test_invalid_options_are_rejected(tmp_path, assignment):
    result = shell(f'collect_options\n{assignment}\nvalidate_options', tmp_path)
    assert result.returncode != 0


def test_port_collision_is_reported(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        result = shell('collect_options\ncheck_port "$APP_PORT"', tmp_path,
                       APP_PORT=listener.getsockname()[1])
    assert result.returncode != 0
    assert 'puerto' in (result.stdout + result.stderr).lower()


def test_units_use_loopback_selected_user_and_separate_processes(tmp_path):
    units = tmp_path / 'units'
    units.mkdir()
    result = shell('collect_options\nNODE_BINARY="$APP_ROOT/tools/node/bin/node"\nrender_units "$SYSTEMD_DIR"',
                   tmp_path, APP_PORT=8181, API_PORT=8182, APP_USER='operator')
    assert result.returncode == 0, result.stderr
    web = (units / 'tld-web.service').read_text()
    api = (units / 'tld-web-api.service').read_text()
    worker = (units / 'tld-web-worker.service').read_text()
    assert 'User=operator' in web
    assert 'HOSTNAME=127.0.0.1 PORT=8181' in web
    assert '--host 127.0.0.1 --port 8182' in api
    assert 'app.rq_worker' in worker
    assert '0.0.0.0' not in web + api + worker


def test_external_redis_has_no_local_systemctl_or_configuration_changes(tmp_path):
    log = tmp_path / 'commands'
    result = shell('''
collect_options
systemctl() { echo "$*" >> "$COMMAND_LOG"; }
configure_redis
''', tmp_path, INSTALL_REDIS=0, REDIS_URL='redis://external.test:6379/2', COMMAND_LOG=log)
    assert result.returncode == 0, result.stderr
    assert not log.exists()


def test_runtime_configuration_preserves_secret_and_does_not_infer_auth_url(tmp_path):
    env = tmp_path / 'existing.env'
    env.write_text('AUTH_SECRET=keep-session-key\nAUTHENTIK_CLIENT_SECRET=keep-client-secret\n'
                   'AUTHENTIK_CLIENT_ID=client\nAUTHENTIK_ISSUER=https://identity.test/application/o/tdl/\n'
                   'DOWNLOADS_DIR=/mnt/existing\n')
    candidate = tmp_path / 'candidate.env'
    result = shell('collect_options\nwrite_environment "$CANDIDATE"', tmp_path,
        ENV_FILE=env, CANDIDATE=candidate, SOURCE_DIR=ROOT, PUBLIC_URL='https://reference.test',
        NODE_BINARY='/opt/node/bin/node', APP_UID='10001', APP_GID='10001')
    assert result.returncode == 0, result.stderr
    values = dict(line.split('=', 1) for line in candidate.read_text().splitlines())
    assert values['AUTH_SECRET'] == 'keep-session-key'
    assert values['AUTHENTIK_CLIENT_SECRET'] == 'keep-client-secret'
    assert values['DOWNLOADS_DIR'] == '/mnt/existing'
    assert values['PUBLIC_URL'] == 'https://reference.test'
    assert values['AUTH_URL'] == 'http://localhost:8080'
    assert values['REDIS_URL'] == 'redis://127.0.0.1:6379/0'
    assert 'WEB_PASSWORD' not in values
    assert 'SECRET_KEY' not in values


def test_release_extraction_rejects_traversal(tmp_path):
    import io
    import tarfile

    archive = tmp_path / 'malicious.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        entry = tarfile.TarInfo('../escaped')
        entry.size = 4
        tar.addfile(entry, io.BytesIO(b'bad!'))
    result = shell('extract_release "$ARCHIVE" "$DESTINATION"', tmp_path,
                   ARCHIVE=archive, DESTINATION=tmp_path / 'extract')
    assert result.returncode != 0
    assert not (tmp_path / 'escaped').exists()


def test_defaults_file_never_contains_oidc_secret(tmp_path):
    result = shell('collect_options\nwrite_defaults "$INSTALL_CONF"', tmp_path,
                   AUTHENTIK_CLIENT_SECRET='not-an-install-default')
    assert result.returncode == 0, result.stderr
    content = (tmp_path / 'etc' / 'install.conf').read_text()
    assert 'not-an-install-default' not in content
    assert 'AUTHENTIK_CLIENT_SECRET' not in content
    assert 'APP_PORT=8080' in content


def test_candidate_native_values_are_explicit(tmp_path):
    result = shell('collect_options\noptions_json', tmp_path, PUBLIC_URL='https://reference.test')
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values['APP_HOST'] == '127.0.0.1'
    assert values['PUBLIC_URL'] == 'https://reference.test'


@pytest.mark.parametrize('failure', ['backup', 'health'])
def test_activation_failure_recovers_environment_units_and_services(tmp_path, failure):
    root = tmp_path / 'app-root'
    (root / 'old').mkdir(parents=True)
    (root / 'new').mkdir()
    (root / 'current').symlink_to(root / 'old')
    config = tmp_path / 'etc'
    config.mkdir()
    (config / 'tld-web.env').write_text('AUTH_SECRET=original\n')
    units = tmp_path / 'units'
    units.mkdir()
    (units / 'tld-web.service').write_text('old web unit')
    candidate = tmp_path / 'candidate'
    candidate.write_text('AUTH_SECRET=new\n')
    log = tmp_path / 'commands'
    result = shell('''
collect_options
APP_GROUP="$(id -gn)"
NODE_BINARY=/usr/bin/node
WORK="$APP_ROOT/work"; mkdir -p "$WORK"
RELEASE="$APP_ROOT/new"
CANDIDATE="$TEST_CANDIDATE"
systemctl() { echo "$*" >> "$COMMAND_LOG"; }
data_admin() {
    if [[ "$1" == backup ]]; then
        [[ "$FAILURE" != backup ]] || return 1
        mkdir -p "$APP_ROOT/backups/snapshot"
        echo "$APP_ROOT/backups/snapshot"
    fi
}
configure_redis() { :; }
health_check() { [[ "$FAILURE" != health ]]; }
activate_release
''', tmp_path, TEST_CANDIDATE=candidate, COMMAND_LOG=log, FAILURE=failure, INSTALL_REDIS=0)
    assert result.returncode != 0
    assert (config / 'tld-web.env').read_text() == 'AUTH_SECRET=original\n'
    assert (units / 'tld-web.service').read_text() == 'old web unit'
    assert (root / 'current').resolve() == root / 'old'
    assert 'start tld-web-api tld-web-worker tld-web' in log.read_text()


def test_repair_does_not_fetch_or_build(tmp_path):
    result = shell('''
collect_options
ACTION=repair
preflight() { :; }
prepare_layout() { :; }
check_service_ports() { :; }
ensure_oidc() { :; }
prepare_candidate() { :; }
prepare_repair() { echo repaired; }
activate_release() { :; }
resolve_source() { exit 91; }
build_release() { exit 92; }
run_installation
''', tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'repaired' in result.stdout


def test_empty_input_accepts_prompt_default_using_pty(tmp_path):
    import pty

    master, terminal = pty.openpty()
    try:
        process = subprocess.Popen(['bash', '-c', f'source "{MASTER}"; prompt_default Puerto 8080'],
                                   stdin=terminal, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.write(master, b'\n')
        stdout, _ = process.communicate(timeout=5)
        assert stdout == b'8080'
    finally:
        os.close(master)
        os.close(terminal)


def test_checksum_rejects_corrupted_binary(tmp_path):
    artifact = tmp_path / 'binary.tar.gz'
    artifact.write_bytes(b'corrupt')
    manifest = tmp_path / 'SHA256SUMS'
    manifest.write_text(f'{"0" * 64}  binary.tar.gz\n')
    result = shell('verify_checksum "$ARTIFACT" "$MANIFEST"', tmp_path,
                   ARTIFACT=artifact, MANIFEST=manifest)
    assert result.returncode != 0
    assert 'Checksum' in result.stderr


def test_master_refuses_overlapping_data_and_code(tmp_path):
    config = tmp_path / 'etc'
    config.mkdir()
    (config / 'tld-web.env').write_text('DATA_DIR=/etc\n')
    result = shell('collect_options\nvalidate_data_paths', tmp_path)
    assert result.returncode != 0
    assert 'datos' in result.stderr.lower()
