import os

from cryptography.fernet import Fernet, InvalidToken

TOKEN_ENCRYPTION_KEY_ENV = "AAP_BRIDGE_TOKEN_ENCRYPTION_KEY"
ENCRYPTED_TOKEN_PREFIX = "enc:v1:"


class TokenCryptoError(RuntimeError):
    pass


def _get_fernet() -> Fernet:
    key = os.environ.get(TOKEN_ENCRYPTION_KEY_ENV, "").strip()
    if not key:
        raise TokenCryptoError(
            f"{TOKEN_ENCRYPTION_KEY_ENV} must be set to create or read encrypted API tokens"
        )
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise TokenCryptoError(f"{TOKEN_ENCRYPTION_KEY_ENV} is not a valid Fernet key") from exc


def is_encrypted_token(token: str | None) -> bool:
    return bool(token and token.startswith(ENCRYPTED_TOKEN_PREFIX))


def encrypt_token(token: str | None) -> str | None:
    if token is None:
        return None
    if token == "":
        return ""
    if is_encrypted_token(token):
        return token
    encrypted = _get_fernet().encrypt(token.encode()).decode()
    return f"{ENCRYPTED_TOKEN_PREFIX}{encrypted}"


def decrypt_token(token: str | None) -> str | None:
    if token is None or token == "":
        return token
    if not is_encrypted_token(token):
        return token
    encrypted_value = token[len(ENCRYPTED_TOKEN_PREFIX) :]
    try:
        return _get_fernet().decrypt(encrypted_value.encode()).decode()
    except InvalidToken as exc:
        raise TokenCryptoError(
            "Stored API token could not be decrypted with the configured key"
        ) from exc
