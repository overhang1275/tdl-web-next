"""Isolated compose.test fixture; never run against an operational installation."""
import os

if os.environ.get("APP_ENV") != "test" or os.environ.get("E2E_INTEGRATION") != "1":
    raise RuntimeError("Test fixture requires isolated test configuration")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select
from app.config import settings
from app.database import SessionLocal
from app.models import User
from app.services.accounts import create_local_user

private = settings.jwt_private_key_file
public = settings.jwt_public_key_file
private.parent.mkdir(parents=True, exist_ok=True)
if not private.exists():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private.chmod(0o600)
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))

with SessionLocal.begin() as db:
    for username in ("local-admin", "idle-probe"):
        if db.scalar(select(User).where(User.username == username)) is None:
            user = create_local_user(db, username, os.environ["E2E_LOCAL_PASSWORD"])
            user.display_name = "Administrador local de pruebas"
print("Isolated test authentication ready")
