"""Ed25519 key management, canonical signing, and certificate verification."""

from __future__ import annotations

import base64
import hashlib
from typing import Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from rctyping_common.canonical import canonical_json_dumps
from rctyping_common.models import CertificateEnvelope, CertificatePayload


def b64url_encode(data: bytes) -> str:
    """Encode bytes to unpadded base64url string."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(data: str) -> bytes:
    """Decode unpadded or padded base64url string to bytes."""
    padding = len(data) % 4
    if padding != 0:
        data += "=" * (4 - padding)
    return base64.urlsafe_b64decode(data.encode("ascii"))


def generate_keypair() -> Tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    """Generate a new Ed25519 private/public keypair."""
    priv = ed25519.Ed25519PrivateKey.generate()
    return priv, priv.public_key()


def public_key_to_raw_bytes(public_key: ed25519.Ed25519PublicKey) -> bytes:
    """Export public key as 32 raw bytes."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def public_key_from_raw_bytes(raw_bytes: bytes) -> ed25519.Ed25519PublicKey:
    """Import public key from 32 raw bytes."""
    return ed25519.Ed25519PublicKey.from_public_bytes(raw_bytes)


def public_key_to_pem(public_key: ed25519.Ed25519PublicKey) -> str:
    """Export public key to SubjectPublicKeyInfo PEM string."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")


def public_key_from_pem(pem_str: str) -> ed25519.Ed25519PublicKey:
    """Import public key from SubjectPublicKeyInfo PEM string."""
    loaded = serialization.load_pem_public_key(pem_str.encode("utf-8"))
    if not isinstance(loaded, ed25519.Ed25519PublicKey):
        raise ValueError("Provided PEM is not an Ed25519 public key")
    return loaded


def public_key_to_b64url(public_key: ed25519.Ed25519PublicKey) -> str:
    """Export public key as 32-byte base64url string."""
    return b64url_encode(public_key_to_raw_bytes(public_key))


def public_key_from_b64url(b64_str: str) -> ed25519.Ed25519PublicKey:
    """Import public key from 32-byte base64url string."""
    return public_key_from_raw_bytes(b64url_decode(b64_str))


def private_key_to_pem(
    private_key: ed25519.Ed25519PrivateKey,
    passphrase: str | None = None,
) -> str:
    """Export private key to PKCS8 PEM string, with optional password encryption."""
    if passphrase:
        encryption = serialization.BestAvailableEncryption(passphrase.encode("utf-8"))
    else:
        encryption = serialization.NoEncryption()

    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    ).decode("utf-8")


def private_key_from_pem(
    pem_str: str,
    passphrase: str | None = None,
) -> ed25519.Ed25519PrivateKey:
    """Import private key from PKCS8 PEM string."""
    password_bytes = passphrase.encode("utf-8") if passphrase else None
    loaded = serialization.load_pem_private_key(pem_str.encode("utf-8"), password=password_bytes)
    if not isinstance(loaded, ed25519.Ed25519PrivateKey):
        raise ValueError("Provided PEM is not an Ed25519 private key")
    return loaded


def calculate_key_id(public_key: ed25519.Ed25519PublicKey) -> str:
    """Calculate key_id fingerprint: hex SHA-256 of 32-byte raw public key."""
    raw = public_key_to_raw_bytes(public_key)
    return hashlib.sha256(raw).hexdigest()


def sign_certificate(
    payload: CertificatePayload,
    private_key: ed25519.Ed25519PrivateKey,
) -> CertificateEnvelope:
    """Sign canonical JSON representation of CertificatePayload with Ed25519 private key."""
    pub = private_key.public_key()
    pub_key_id = calculate_key_id(pub)
    if payload.issuer_id != pub_key_id:
        raise ValueError(
            f"Payload issuer_id '{payload.issuer_id}' does not match signing key fingerprint '{pub_key_id}'"
        )

    canonical_bytes = canonical_json_dumps(payload)
    sig_bytes = private_key.sign(canonical_bytes)

    return CertificateEnvelope(
        payload=payload,
        signature=b64url_encode(sig_bytes),
        issuer_public_key=public_key_to_b64url(pub),
    )


def verify_certificate_envelope(
    envelope: CertificateEnvelope,
    expected_public_key: ed25519.Ed25519PublicKey | None = None,
) -> bool:
    """Verify cryptographic signature on CertificateEnvelope.

    Checks:
    1. Public key parses validly
    2. Payload issuer_id matches public key fingerprint
    3. Ed25519 signature over canonical JSON matches
    """
    try:
        # Load public key
        if expected_public_key is not None:
            pub = expected_public_key
        else:
            pub_str = envelope.issuer_public_key
            if pub_str.startswith("-----BEGIN"):
                pub = public_key_from_pem(pub_str)
            else:
                pub = public_key_from_b64url(pub_str)

        # Check key ID matches
        actual_key_id = calculate_key_id(pub)
        if envelope.payload.issuer_id != actual_key_id:
            return False

        # Canonicalize payload and verify
        canonical_bytes = canonical_json_dumps(envelope.payload)
        sig_bytes = b64url_decode(envelope.signature)
        pub.verify(sig_bytes, canonical_bytes)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False
