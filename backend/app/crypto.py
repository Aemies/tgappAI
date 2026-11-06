"""Шифрование пользовательских секретов (AES-256-GCM).

Мастер-ключ живёт только в переменных окружения, в базе лежит шифротекст.
AAD привязывает шифротекст к пользователю и провайдеру: чужую запись нельзя
подставить другому пользователю.
"""
import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import get_settings


class CryptoError(RuntimeError):
    pass


def _key() -> bytes:
    raw = get_settings().encryption_master_key
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception:
        key = b""
    if len(key) != 32:
        raise CryptoError("ENCRYPTION_MASTER_KEY должен быть 32 байта в base64")
    return key


def encrypt(plaintext: str, aad: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), aad.encode())
    return base64.b64encode(nonce + ct).decode()


def decrypt(token: str, aad: str) -> str:
    data = base64.b64decode(token)
    return AESGCM(_key()).decrypt(data[:12], data[12:], aad.encode()).decode()
