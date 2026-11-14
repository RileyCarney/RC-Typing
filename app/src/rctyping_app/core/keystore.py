"""Issuer cryptographic key store."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from rctyping_common.certificate import (
    Ed25519KeyStore,
    b64url_decode,
    b64url_encode,
)


class KeyStore(Ed25519KeyStore):
    """Manages the local Ed25519 signing keypair and local AES-256-GCM encryption key."""

    def __init__(self, keys_dir: Path, passphrase: Optional[str] = None) -> None:
        self.brain_key_file = Path(keys_dir) / "brain.key"
        self._brain_key: Optional[bytes] = None
        super().__init__(keys_dir=keys_dir, passphrase=passphrase, key_filename="issuer.key")

    def _load_or_generate(self) -> None:
        super()._load_or_generate()
        if self.brain_key_file.exists():
            with open(self.brain_key_file, "r", encoding="utf-8") as f:
                self._brain_key = b64url_decode(f.read().strip())
        else:
            self._brain_key = AESGCM.generate_key(bit_length=256)
            with open(self.brain_key_file, "w", encoding="utf-8") as f:
                f.write(b64url_encode(self._brain_key))
            self._secure_file_permissions(self.brain_key_file)

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
