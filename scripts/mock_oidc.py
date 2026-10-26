"""OIDC test provider with RS256, authorization code + PKCE, and refresh rotation.

Only included in compose.test.yml. No production authentication bypass.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

app = FastAPI()
issuer = os.getenv("MOCK_OIDC_ISSUER", "http://oidc:9000/application/o/tdl-console/")
origin = issuer.split("/application/")[0]
client_id = "tdl-console"
client_secret = "test-client-secret"
redirect_uri = "http://web:3000/api/auth/callback/authentik"
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_key = {**jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True), "kid": "test-key", "use": "sig", "alg": "RS256"}
codes: dict[str, dict] = {}
refresh_tokens: set[str] = set()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/application/o/tdl-console/.well-known/openid-configuration")
def discovery():
    return {
        "issuer": issuer, "authorization_endpoint": f"{origin}/application/o/authorize/",
        "token_endpoint": f"{origin}/application/o/token/", "userinfo_endpoint": f"{origin}/application/o/userinfo/",
        "jwks_uri": f"{issuer}jwks/", "response_types_supported": ["code"],
        "subject_types_supported": ["public"], "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
    }


@app.get("/application/o/tdl-console/jwks/")
def jwks():
    return {"keys": [public_key]}


@app.get("/application/o/authorize/")
def authorize(request: Request):
    params = dict(request.query_params)
    if (params.get("client_id") != client_id or params.get("redirect_uri") != redirect_uri
            or params.get("response_type") != "code" or params.get("code_challenge_method") != "S256"):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    code = secrets.token_urlsafe(24)
    codes[code] = {**params, "created_at": time.time()}
    return RedirectResponse(f"{redirect_uri}?{urlencode({'code': code, 'state': params.get('state', '')})}")


@app.post("/application/o/token/")
async def token(request: Request):
    params = {name: values[0] for name, values in parse_qs((await request.body()).decode()).items()}
    credentials = (params.get("client_id"), params.get("client_secret"))
    if request.headers.get("authorization", "").startswith("Basic "):
        credentials = tuple(base64.b64decode(request.headers["authorization"][6:]).decode().split(":", 1))
    if credentials != (client_id, client_secret):
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    if params.get("grant_type") == "authorization_code":
        code = codes.pop(params.get("code", ""), None)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(params.get("code_verifier", "").encode()).digest()).decode().rstrip("=")
        if not code or time.time() - code["created_at"] > 120 or challenge != code.get("code_challenge") or params.get("redirect_uri") != redirect_uri:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
    elif params.get("grant_type") == "refresh_token":
        refresh = params.get("refresh_token", "")
        if refresh not in refresh_tokens:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        refresh_tokens.remove(refresh)
    else:
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    now = int(time.time())
    claims = {"iss": issuer, "aud": client_id, "sub": "test-operator", "iat": now, "exp": now + 300,
              "name": "Operador de pruebas", "email": "operator@example.test", "email_verified": True,
              "preferred_username": "operator", "groups": ["tdl-admin"]}
    signed = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
    refresh = secrets.token_urlsafe(32)
    refresh_tokens.add(refresh)
    return JSONResponse({"access_token": signed, "id_token": signed, "token_type": "Bearer", "expires_in": 300,
                         "refresh_token": refresh, "scope": "openid profile email offline_access tdl-groups"},
                        headers={"Cache-Control": "no-store"})


@app.get("/application/o/userinfo/")
def userinfo(request: Request):
    try:
        return jwt.decode(request.headers.get("authorization", "").removeprefix("Bearer "), key.public_key(),
                          algorithms=["RS256"], audience=client_id, issuer=issuer)
    except jwt.PyJWTError:
        return JSONResponse({"error": "invalid_token"}, status_code=401)
