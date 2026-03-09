from __future__ import annotations

import hashlib
import hmac
import secrets


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign_token(secret: str, token: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(secret: str, token: str, signature_hex: str) -> bool:
    expected = sign_token(secret, token)
    return secrets.compare_digest(expected, signature_hex)
