"""SQLAlchemy database models for the rc-typing Registry."""

from __future__ import annotations

import datetime
from typing import Any, Optional
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class RegistryBase(DeclarativeBase):
    pass


class IssuerModel(RegistryBase):
    __tablename__ = "issuers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 fingerprint
    public_key: Mapped[str] = mapped_column(String(255), nullable=False)  # Base64url raw 32 bytes or PEM
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)  # active, suspended
    trust_tier: Mapped[str] = mapped_column(String(32), default="unverified", nullable=False)  # unverified, verified, official
    registered_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    certificates: Mapped[list[CertificateRecordModel]] = relationship(back_populates="issuer")


class RegistrationChallengeModel(RegistryBase):
    __tablename__ = "registration_challenges"

    challenge: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)


class CertificateRecordModel(RegistryBase):
    __tablename__ = "registry_certificates"

    cert_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    issuer_id: Mapped[str] = mapped_column(String(64), ForeignKey("issuers.id"), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    leaf_index: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    issued_at: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    received_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revocation_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)

    issuer: Mapped[IssuerModel] = relationship(back_populates="certificates")
    log_entry: Mapped[Optional[LogEntryModel]] = relationship(back_populates="certificate", uselist=False)


class LogEntryModel(RegistryBase):
    __tablename__ = "log_entries"

    leaf_index: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    cert_id: Mapped[str] = mapped_column(String(36), ForeignKey("registry_certificates.cert_id"), nullable=False)
    leaf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False)

    certificate: Mapped[CertificateRecordModel] = relationship(back_populates="log_entry")


class TreeHeadModel(RegistryBase):
    __tablename__ = "tree_heads"

    tree_size: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    root_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=False)
    signature: Mapped[str] = mapped_column(String(255), nullable=False)
