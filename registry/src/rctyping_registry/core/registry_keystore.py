"""Registry authority signing key store."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import ed25519

from rctyping_common.certificate import (
    calculate_key_id,
    generate_keypair,
    private_key_from_pem,
    private_key_to_pem,
    public_key_to_b64url,
    public_key_to_pem,
)


class RegistryKeyStore:
    """Manages the registry root signing keypair for signing tree heads."""

    def __init__(self, keys_dir: Path, passphrase: Optional[str] = None) -> None:
        self.keys_dir = Path(keys_dir)
        self.passphrase = passphrase
        self.key_file = self.keys_dir / "registry.key"
        self._private_key: Optional[ed25519.Ed25519PrivateKey] = None
        self._public_key: Optional[ed25519.Ed25519PublicKey] = None
        self._key_id: Optional[str] = None
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
            if sys.platform != "win32":
                try:
                    os.chmod(self.key_file, 0o600)
                except OSError:
                    pass

        self._public_key = self._private_key.public_key()
        self._key_id = calculate_key_id(self._public_key)

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
