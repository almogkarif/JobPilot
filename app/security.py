from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import settings

_CREDENTIAL_PREFIX = "jpenc:v1:"


def _credential_secret_material() -> str:
    candidates = (
        settings.credential_encryption_key,
        settings.supabase_secret_key,
        settings.supabase_service_role_key,
        settings.cron_secret,
        settings.agent_token,
    )
    for value in candidates[:-1]:
        value = str(value or "").strip()
        if value and value != "change-me":
            return value
    agent_token = str(settings.agent_token or "").strip()
    if agent_token and (settings.auth_mode != "supabase" or agent_token != "change-me"):
        # Local installs need deterministic encryption without extra setup. Cloud
        # deployments must not silently rely on the public/default development token.
        return f"{agent_token}|{settings.database_url}"
    return ""


def credential_encryption_available() -> bool:
    return bool(_credential_secret_material())


def _fernet() -> Fernet:
    material = _credential_secret_material()
    if not material:
        raise RuntimeError(
            "Credential encryption is not configured. Set JOBPILOT_CREDENTIAL_ENCRYPTION_KEY "
            "to a stable random secret before storing application passwords."
        )
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def is_encrypted_credential(value: str | None) -> bool:
    return str(value or "").startswith(_CREDENTIAL_PREFIX)


def encrypt_credential(value: str | None) -> str:
    plain = str(value or "")
    if not plain:
        return ""
    if is_encrypted_credential(plain):
        return plain
    token = _fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return _CREDENTIAL_PREFIX + token


def decrypt_credential(value: str | None) -> str:
    stored = str(value or "")
    if not stored:
        return ""
    if not is_encrypted_credential(stored):
        # Backward compatibility during rollout: legacy plaintext remains readable
        # until startup/write migration replaces it with an encrypted value.
        return stored
    try:
        return _fernet().decrypt(stored[len(_CREDENTIAL_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError("Stored application password cannot be decrypted with the configured credential key") from exc
