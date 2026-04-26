"""AES-256-GCM encryption and SHA-256 hashing utilities."""

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm.attributes import set_committed_value


def encrypt(plaintext: str, key: bytes) -> bytes:
    """Encrypt plaintext using AES-256-GCM.

    Returns nonce (12 bytes) || ciphertext.
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt(ciphertext: bytes | str, key: bytes) -> str:
    """Decrypt AES-256-GCM ciphertext (nonce || ct) back to plaintext.

    Returns already-decrypted strings unchanged (idempotent for identity map reuse).
    """
    if isinstance(ciphertext, str):
        return ciphertext
    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")


def encrypt_nullable(value: str | None, key: bytes) -> bytes | None:
    """Encrypt a value, passing through None unchanged."""
    if value is None:
        return None
    return encrypt(value, key)


def decrypt_nullable(value: bytes | str | None, key: bytes) -> str | None:
    """Decrypt a value, passing through None and already-decrypted strings."""
    if value is None or isinstance(value, str):
        return value
    return decrypt(value, key)


def validate_key(key: bytes) -> None:
    """Raise RuntimeError if key is not exactly 32 bytes (AES-256)."""
    if len(key) != 32:
        raise RuntimeError(f"ENCRYPTION_KEY must decode to 32 bytes, got {len(key)}")


def set_decrypted(obj: object, attr: str, value: object) -> None:
    """Set a decrypted value on a model without marking it dirty in SQLAlchemy."""
    set_committed_value(obj, attr, value)


def hash_phone(phone: str) -> str:
    """SHA-256 hex digest of a phone number for lookup."""
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()
