"""Registry authority signing key store."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rctyping_common.certificate import Ed25519KeyStore


class RegistryKeyStore(Ed25519KeyStore):
    """Manages the registry root signing keypair for signing tree heads."""

    def __init__(self, keys_dir: Path, passphrase: Optional[str] = None) -> None:
        super().__init__(keys_dir=keys_dir, passphrase=passphrase, key_filename="registry.key")
