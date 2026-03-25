"""Tests for core encryption utilities."""

import os

import pytest
from cryptography.exceptions import InvalidTag

from piazza.core.encryption import (
    decrypt,
    decrypt_nullable,
    encrypt,
    encrypt_nullable,
    hash_phone,
    validate_key,
)


@pytest.fixture
def key() -> bytes:
    return os.urandom(32)


class TestEncryptDecrypt:
    def test_round_trip(self, key: bytes):
        plaintext = "Hello, Piazza!"
        ct = encrypt(plaintext, key)
        assert decrypt(ct, key) == plaintext

    def test_round_trip_unicode(self, key: bytes):
        plaintext = "I paid \u20ac50 for dinner \U0001f355"
        ct = encrypt(plaintext, key)
        assert decrypt(ct, key) == plaintext

    def test_round_trip_empty_string(self, key: bytes):
        ct = encrypt("", key)
        assert decrypt(ct, key) == ""

    def test_different_plaintexts_produce_different_ciphertexts(self, key: bytes):
        """GCM nonce uniqueness: encrypting the same plaintext twice
        should produce different ciphertexts."""
        ct1 = encrypt("same text", key)
        ct2 = encrypt("same text", key)
        assert ct1 != ct2

    def test_decrypt_with_wrong_key_raises(self, key: bytes):
        ct = encrypt("secret", key)
        wrong_key = os.urandom(32)
        with pytest.raises(InvalidTag):
            decrypt(ct, wrong_key)


class TestNullableHelpers:
    def test_encrypt_nullable_none(self, key: bytes):
        assert encrypt_nullable(None, key) is None

    def test_decrypt_nullable_none(self, key: bytes):
        assert decrypt_nullable(None, key) is None

    def test_encrypt_decrypt_nullable_round_trip(self, key: bytes):
        ct = encrypt_nullable("hello", key)
        assert ct is not None
        assert decrypt_nullable(ct, key) == "hello"


class TestValidateKey:
    def test_wrong_length_raises(self):
        with pytest.raises(RuntimeError, match="32 bytes"):
            validate_key(os.urandom(16))

    def test_correct_length_passes(self):
        validate_key(os.urandom(32))


class TestHashPhone:
    def test_consistent_output(self):
        phone = "5511999999999@s.whatsapp.net"
        assert hash_phone(phone) == hash_phone(phone)

    def test_produces_64_char_hex(self):
        result = hash_phone("5511999999999@s.whatsapp.net")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_different_inputs_produce_different_hashes(self):
        h1 = hash_phone("5511111111111@s.whatsapp.net")
        h2 = hash_phone("5522222222222@s.whatsapp.net")
        assert h1 != h2
