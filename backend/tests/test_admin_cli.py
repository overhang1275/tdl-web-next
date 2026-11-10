import os
import subprocess
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_accounts import PASSWORD
from test_accounts import accounts as accounts

from app.models import AuditEvent, User

pytestmark = pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() != 0,
                                reason="Offline recovery integration requires explicit test-container root")

def cli(test_engine, tmp_path, *args, root=True):
    envfile = tmp_path / "admin.env"
    envfile.write_text("DATABASE_URL=" + test_engine.url.render_as_string(hide_password=False) + "\n", encoding="utf8")
    envfile.chmod(0o600)
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    # The disposable schema is supplied as libpq options, never shell-evaluated.
    with test_engine.connect() as connection:
        schema = connection.exec_driver_sql("select current_schema()").scalar_one()
    env["PGOPTIONS"] = f"-csearch_path={schema}"
    command = [sys.executable, "-m", "app.admin", *args, "--env-file", str(envfile), "--docker-maintenance"]
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30,
                          user=0 if root else 65534)


def secret(tmp_path, mode=0o600):
    path = tmp_path / "password"
    path.write_text(PASSWORD + "\n", encoding="utf8")
    path.chmod(mode)
    return path


def test_environment_loader_unescapes_quoted_values(tmp_path, monkeypatch):
    from app import admin
    envfile = tmp_path / "quoted.env"
    envfile.write_text('AUTHENTIK_CLIENT_SECRET="a\\\\b\\"c"\n', encoding="utf8")
    envfile.chmod(0o600)
    monkeypatch.setattr(os, "environ", dict(os.environ))
    admin._load_environment(envfile)
    assert os.environ["AUTHENTIK_CLIENT_SECRET"] == 'a\\b"c'


def test_root_cli_bootstrap_idempotent_reset_without_web(test_engine, tmp_path):
    path = secret(tmp_path)
    args = ("--username", "ADMIN", "--password-file", str(path))
    result = cli(test_engine, tmp_path, "create-admin", *args)
    assert result.returncode == 0, result.stderr
    with Session(test_engine) as db:
        original = db.scalar(select(User)).password_hash
    path.write_text("a different password 123\n", encoding="utf8")
    assert cli(test_engine, tmp_path, "create-admin", *args).returncode == 0
    with Session(test_engine) as db:
        assert db.scalar(select(User)).password_hash == original
        user = db.scalar(select(User))
        user.active = False
        db.commit()
    assert cli(test_engine, tmp_path, "create-admin", *args).returncode == 0
    with Session(test_engine) as db:
        assert not db.scalar(select(User)).active
    assert cli(test_engine, tmp_path, "reset-password", *args).returncode == 0
    with Session(test_engine) as db:
        user = db.scalar(select(User))
        assert user.password_hash != original and user.must_change_password
        assert {e.action for e in db.scalars(select(AuditEvent))} >= {"cli.create_admin", "cli.reset_password"}
    assert PASSWORD not in result.stdout + result.stderr and original not in result.stdout + result.stderr


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_cli_rejects_exposed_password_file(test_engine, tmp_path, mode):
    result = cli(test_engine, tmp_path, "create-admin", "--username", "admin", "--password-file", str(secret(tmp_path, mode)))
    assert result.returncode != 0
    assert PASSWORD not in result.stdout + result.stderr


def test_cli_rejects_nonroot_and_argv_password(test_engine, tmp_path):
    result = cli(test_engine, tmp_path, "create-admin", "--username", "admin", "--password-file", str(secret(tmp_path)), root=False)
    assert result.returncode != 0
    assert "root" in result.stderr.lower()
    result = cli(test_engine, tmp_path, "create-admin", "--username", "admin", "--password", PASSWORD)
    assert result.returncode != 0 and PASSWORD not in result.stdout + result.stderr


def test_cli_external_account_not_converted_or_enabled(test_engine, db_session, tmp_path):
    db_session.add(User(username="external", active=False))
    db_session.commit()
    result = cli(test_engine, tmp_path, "reset-password", "--username", "external", "--password-file", str(secret(tmp_path)))
    assert result.returncode != 0
    db_session.expire_all()
    user = db_session.scalar(select(User))
    assert not user.active and user.password_hash is None


def test_cli_rejects_symlink_password_file(test_engine, tmp_path):
    path = secret(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(path)
    assert cli(test_engine, tmp_path, "create-admin", "--username", "admin", "--password-file", str(link)).returncode != 0


def test_cli_reset_disabled_local_explicitly_recovers_and_revokes(test_engine, db_session, accounts, tmp_path):
    from datetime import UTC, datetime, timedelta

    from app.models import AuthSession

    user = accounts.create_local_user(db_session, "admin", PASSWORD)
    user.active = False
    row = AuthSession(user_id=user.id, refresh_token_hash="a" * 64, absolute_expires_at=datetime.now(UTC) + timedelta(hours=1), idle_expires_at=datetime.now(UTC) + timedelta(minutes=10))
    db_session.add(row)
    db_session.commit()
    result = cli(test_engine, tmp_path, "reset-password", "--username", "admin", "--password-file", str(secret(tmp_path)))
    assert result.returncode == 0, result.stderr
    db_session.expire_all()
    assert db_session.get(User, user.id).active and db_session.get(AuthSession, row.id).revoked_at is not None


def test_private_env_is_literal_and_rejects_exposed_file(tmp_path, monkeypatch):
    from app.admin import _load_environment

    path = tmp_path / "settings.env"
    marker = tmp_path / "must-not-exist"
    value = f"$(touch {marker})"
    path.write_text("ADMIN_TEST_LITERAL='" + value + "'\n", encoding="utf8")
    path.chmod(0o600)
    monkeypatch.setenv("ADMIN_TEST_LITERAL", "before")
    _load_environment(path)
    assert os.environ["ADMIN_TEST_LITERAL"] == value and not marker.exists()
    path.chmod(0o644)
    with pytest.raises(ValueError):
        _load_environment(path)


@pytest.mark.parametrize("kind", ["parent_link", "wrong_owner", "fifo"])
def test_cli_rejects_unsafe_secret_paths(test_engine, tmp_path, kind):
    path = secret(tmp_path)
    if kind == "parent_link":
        link = tmp_path / "parent"
        link.symlink_to(tmp_path, target_is_directory=True)
        path = link / path.name
    elif kind == "wrong_owner":
        os.chown(path, 65534, 65534)
    else:
        path.unlink()
        os.mkfifo(path, 0o600)
    assert cli(test_engine, tmp_path, "create-admin", "--username", "admin", "--password-file", str(path)).returncode != 0


def test_cli_requires_explicit_docker_maintenance(test_engine, tmp_path):
    result = subprocess.run([sys.executable, "-m", "app.admin", "reset-password", "--username", "admin", "--password-file", str(secret(tmp_path))], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and "--docker-maintenance" in result.stderr
