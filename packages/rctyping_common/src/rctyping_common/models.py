"""Data models shared across rc-typing app, registry, and verifiers."""

from __future__ import annotations

import enum
import re
import unicodedata
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


def sanitize_display_name(name: str) -> str:
    """Sanitize subject display name:

    - Normalize to NFC unicode
    - Strip control characters and bidirectional override characters
    - Strip leading/trailing whitespace
    - Clamp length to 64 characters
    - Fallback to 'Anonymous Typist' if empty
    """
    if not name:
        return "Anonymous Typist"

    # Normalize unicode
    normalized = unicodedata.normalize("NFC", str(name))

    # Strip control chars, bidi overrides (U+202A to U+202E, U+2066 to U+2069), zero-width chars
    cleaned_chars: List[str] = []
    for ch in normalized:
        category = unicodedata.category(ch)
        cp = ord(ch)
        # Disallow control characters (Cc, Cf) except plain spaces
        if category in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        # Specific check for bidi overrides
        if 0x202A <= cp <= 0x202E or 0x2066 <= cp <= 0x2069 or cp in (0x200B, 0x200C, 0x200D, 0xFEFF):
            continue
        cleaned_chars.append(ch)

    result = "".join(cleaned_chars).strip()
    # Replace multiple internal spaces with a single space
    result = re.sub(r"\s+", " ", result)
    if not result:
        return "Anonymous Typist"
    return result[:64]


class Metrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    net_wpm: float = Field(..., ge=0.0, description="Net Words Per Minute ((correct_chars / 5) / minutes)")
    raw_wpm: float = Field(..., ge=0.0, description="Raw Words Per Minute ((total_chars / 5) / minutes)")
    accuracy: float = Field(..., ge=0.0, le=1.0, description="Accuracy ratio 0.0 to 1.0")
    consistency: float = Field(..., ge=0.0, le=1.0, description="Keystroke interval consistency score 0.0 to 1.0")
    duration_ms: int = Field(..., ge=0, description="Test elapsed duration in milliseconds")
    chars_total: int = Field(..., ge=0, description="Total characters entered")
    chars_correct: int = Field(..., ge=0, description="Correct characters entered")
    chars_incorrect: int = Field(..., ge=0, description="Incorrect/error characters")


class KeystrokeEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    t_ms: int = Field(..., ge=0, description="Timestamp offset relative to start in milliseconds")
    key: str = Field(..., description="Key value (e.g. 'a', 'Enter', 'Backspace')")
    type: str = Field(..., description="'keydown' or 'keyup'")
    is_trusted: bool = Field(default=True, description="Whether isTrusted was true in the browser event")


class TrustTier(str, enum.Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    OFFICIAL = "official"


class CertificatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(default=1, description="Certificate schema version")
    cert_id: str = Field(..., description="Unique UUID for this certificate")
    issued_at: str = Field(..., description="ISO 8601 UTC timestamp of certificate generation")
    subject: str = Field(..., max_length=64, description="User-supplied display name")
    category: str = Field(..., description="Category: code, prose, reading, technical, formal, conversational")
    language: Optional[str] = Field(default=None, description="Subcategory/language for code: python, cpp, sql, etc.")
    passage_id: str = Field(..., description="Identifier of the passage typed")
    passage_sha256: str = Field(..., min_length=64, max_length=64, description="SHA-256 of canonical passage text")
    metrics: Metrics = Field(..., description="Computed speed and accuracy metrics")
    keystroke_log_sha256: str = Field(..., min_length=64, max_length=64, description="SHA-256 of keystroke JSON log")
    integrity: str = Field(default="clean", description="'clean' or 'flagged' by anti-cheat heuristics")
    assurance: str = Field(default="heuristic-checked", description="'self-attested', 'heuristic-checked', or 'proctored'")
    nonce: str = Field(..., min_length=16, description="Cryptographic server nonce for this session")
    issuer_id: str = Field(..., description="SHA-256 fingerprint of issuer public key")
    alg: str = Field(default="Ed25519", description="Signature algorithm")

    @field_validator("subject", mode="before")
    @classmethod
    def validate_and_sanitize_name(cls, v: Any) -> str:
        return sanitize_display_name(str(v))


class CertificateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: CertificatePayload
    signature: str = Field(..., description="Base64url encoded Ed25519 signature over canonical payload")
    issuer_public_key: str = Field(..., description="Base64url or PEM encoded Ed25519 public key")


class InclusionProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leaf_index: int = Field(..., ge=0)
    tree_size: int = Field(..., ge=1)
    audit_path: List[str] = Field(default_factory=list, description="List of sibling hex hashes")


class SignedTreeHead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tree_size: int = Field(..., ge=0)
    root_hash: str = Field(..., min_length=64, max_length=64)
    timestamp: str
    signature: str = Field(..., description="Base64url signature by the registry over canonical head data")


class RegistryReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cert_id: str
    cert_sha256: str
    leaf_index: int
    tree_size: int
    inclusion_proof: InclusionProof
    signed_tree_head: SignedTreeHead
    registered_at: str


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    status: str = Field(..., description="VALID, VALID_OFFLINE, REVOKED, ISSUER_SUSPENDED, TAMPERED, INVALID_SIGNATURE")
    trust_tier: str = "unverified"
    details: str
    payload: Optional[CertificatePayload] = None
    receipt: Optional[RegistryReceipt] = None
    disclaimer: str = "The subject display name is self-asserted and unverified."
