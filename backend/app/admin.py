"""Offline Linux root recovery. No web server, password argv, or shell evaluation."""
from __future__ import annotations

import argparse
import os
import re
import shlex
import stat
import sys
from pathlib import Path


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes unrecognized argv, which may contain secrets.
        self.exit(2, "Invalid administration arguments; use --help.\n")


def _private_file(path: Path, limit: int) -> str:
    """Open every path component without following symlinks, then check the FD."""
    path = path.absolute()
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            next_directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o077:
                raise ValueError("Input must be a root-owned private regular file")
            value = stream.read(limit + 1)
            if len(value) > limit:
                raise ValueError("Input too large")
            return value.decode("utf-8")
    finally:
        os.close(directory)


def _load_environment(path: Path) -> None:
    values = {}
    for line in _private_file(path, 65536).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key.strip()):
            raise ValueError("Invalid environment file")
        value = value.strip()
        if value[:1] in {"'", '"'}:
            # Same quoting rules as scripts/configure-env.py.
            parts = shlex.split(value, comments=False)
            if len(parts) != 1:
                raise ValueError("Invalid quoted environment value")
            value = parts[0]
        values[key.strip()] = value  # Literal data; never source/eval/expand.
    os.environ.update(values)


def main(argv=None) -> int:
    parser = _Parser(description="Root-only offline local administrator recovery.", allow_abbrev=False)
    parser.add_argument("command", choices=("create-admin", "reset-password"))
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--docker-maintenance", action="store_true",
                        help="Explicitly authorize root maintenance inside Docker (exec --user 0).")
    args = parser.parse_args(argv)
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        parser.exit(1, "Root access on the Linux host or maintenance container is required.\n")
    if Path("/.dockerenv").exists() and not args.docker_maintenance:
        parser.exit(1, "Docker recovery requires --docker-maintenance and exec --user 0.\n")
    try:
        if args.env_file:
            _load_environment(args.env_file)
        # Configuration/database imports must follow the explicit environment file.
        from sqlalchemy import select, text

        from app.database import SessionLocal, check_schema
        from app.models import User
        from app.services.accounts import canonical_username, create_local_user, reset_password
        from app.services.audit import audit

        username = canonical_username(args.username)
        password = _private_file(args.password_file, 1024)
        if password.endswith("\n"):
            password = password[:-1].removesuffix("\r")
        if "\n" in password or "\r" in password:
            raise ValueError("Password file must contain one line")
        check_schema()
        with SessionLocal.begin() as db:
            db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 0x54444C41444D494E})
            user = db.scalar(select(User).where(User.username == username).with_for_update())
            if args.command == "create-admin":
                if user is None:
                    user = create_local_user(db, username, password, must_change_password=True)
                    outcome = "success"
                else:
                    if user.password_hash is None:
                        raise ValueError("External account cannot become local")
                    outcome = "unchanged"
                audit(db, None, "cli.create_admin", user.id, outcome)
            else:
                if user is None:
                    raise ValueError("Local account not found")
                user = reset_password(db, user.id, password)
                # Explicit root recovery of an existing local account restores access.
                user.active = True
                db.flush()
                audit(db, None, "cli.reset_password", user.id, "success")
        print("Administration completed. A changed password requires a new login.")
        return 0
    except Exception:
        print("Administration failed. Check the protected input, account, database and schema.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
