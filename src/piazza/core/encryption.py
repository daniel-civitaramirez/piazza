"""AES-256-GCM encryption and SHA-256 hashing utilities."""

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt(plaintext: str, key: bytes) -> bytes:
    """Encrypt plaintext using AES-256-GCM.

    Returns nonce (12 bytes) || ciphertext.
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt(ciphertext: bytes, key: bytes) -> str:
    """Decrypt AES-256-GCM ciphertext (nonce || ct) back to plaintext."""
    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")


def hash_phone(phone: str) -> str:
    """SHA-256 hex digest of a phone number for lookup."""
    return hashlib.sha256(phone.encode("utf-8")).hexdigest()
