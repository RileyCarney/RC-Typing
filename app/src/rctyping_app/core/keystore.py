"""Issuer cryptographic key store."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from rctyping_common.certificate import (
    b64url_decode,
    b64url_encode,
    calculate_key_id,
    generate_keypair,
    private_key_from_pem,
    private_key_to_pem,
    public_key_to_b64url,
    public_key_to_pem,
)


class KeyStore:
    """Manages the local Ed25519 signing keypair and local AES-256-GCM encryption key."""

    def __init__(self, keys_dir: Path, passphrase: Optional[str] = None) -> None:
        self.keys_dir = Path(keys_dir)
        self.passphrase = passphrase
        self.key_file = self.keys_dir / "issuer.key"
        self.brain_key_file = self.keys_dir / "brain.key"
        self._private_key: Optional[ed25519.Ed25519PrivateKey] = None
        self._public_key: Optional[ed25519.Ed25519PublicKey] = None
        self._key_id: Optional[str] = None
        self._brain_key: Optional[bytes] = None
        self._load_or_generate()

    def _load_or_generate(self) -> None:
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        if self.key_file.exists():
            with open(self.key_file, "r", encoding="utf-8") as f:
                pem_data = f.read()
            self._private_key = private_key_from_pem(pem_data, passphrase=self.passphrase)
        else:
            self._private_key, self._public_key = generate_keypair()
            pem_data = private_key_to_pem(self._private_key, passphrase=self.passphrase)
            with open(self.key_file, "w", encoding="utf-8") as f:
                f.write(pem_data)
            self._secure_file_permissions(self.key_file)

        self._public_key = self._private_key.public_key()
        self._key_id = calculate_key_id(self._public_key)

        if self.brain_key_file.exists():
            with open(self.brain_key_file, "r", encoding="utf-8") as f:
                self._brain_key = b64url_decode(f.read().strip())
        else:
            self._brain_key = AESGCM.generate_key(bit_length=256)
            with open(self.brain_key_file, "w", encoding="utf-8") as f:
                f.write(b64url_encode(self._brain_key))
            self._secure_file_permissions(self.brain_key_file)

    @staticmethod
    def _secure_file_permissions(path: Path) -> None:
        if sys.platform != "win32":
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass

    @property
    def private_key(self) -> ed25519.Ed25519PrivateKey:
        assert self._private_key is not None
        return self._private_key

    @property
    def public_key(self) -> ed25519.Ed25519PublicKey:
        assert self._public_key is not None
        return self._public_key

    @property
    def key_id(self) -> str:
        assert self._key_id is not None
        return self._key_id

    def get_public_key_pem(self) -> str:
        return public_key_to_pem(self.public_key)

    def get_public_key_b64(self) -> str:
        return public_key_to_b64url(self.public_key)

    def encrypt_text(self, plaintext: str) -> str:
        """Encrypt UTF-8 plaintext using local AES-256-GCM key."""
        assert self._brain_key is not None
        nonce = os.urandom(12)
        aesgcm = AESGCM(self._brain_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return b64url_encode(nonce + ciphertext)

    def decrypt_text(self, token: str) -> str:
        """Decrypt base64url AES-256-GCM token back to UTF-8 plaintext."""
        assert self._brain_key is not None
        raw = b64url_decode(token)
        nonce, ciphertext = raw[:12], raw[12:]
        aesgcm = AESGCM(self._brain_key)
        return aesgcm.decrypt(nonce, ciphertext, None).decode("utf-8")
