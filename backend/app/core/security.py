import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("utf-8"))


def hash_password(password: str) -> str:
    iterations = 260000
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64_encode(salt)}${_b64_encode(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = _b64_decode(salt_raw)
        expected = _b64_decode(digest_raw)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def create_access_token(payload: dict[str, Any], expires_in_seconds: int = 86400) -> str:
    body = {**payload, "exp": int(time.time()) + expires_in_seconds}
    body_raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body_b64 = _b64_encode(body_raw)
    signature = hmac.new(settings.SECRET_KEY.encode("utf-8"), body_b64.encode("utf-8"), hashlib.sha256).digest()
    return f"{body_b64}.{_b64_encode(signature)}"


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        body_b64, signature_b64 = token.split(".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode("utf-8"), body_b64.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64_decode(signature_b64), expected):
            return None
        payload = json.loads(_b64_decode(body_b64).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None
