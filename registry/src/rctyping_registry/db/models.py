"""SQLAlchemy database models for the rc-typing Registry."""

from __future__ import annotations

import datetime
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

RegistryBase = declarative_base()


class IssuerModel(RegistryBase):
    __tablename__ = "issuers"

    id = Column(String(64), primary_key=True)  # SHA-256 fingerprint
    public_key = Column(String(255), nullable=False)  # Base64url raw 32 bytes or PEM
    status = Column(String(32), default="active", nullable=False)  # active, suspended
    trust_tier = Column(String(32), default="unverified", nullable=False)  # unverified, verified, official
    registered_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    certificates = relationship("CertificateRecordModel", back_populates="issuer")


class RegistrationChallengeModel(RegistryBase):
    __tablename__ = "registration_challenges"

    challenge = Column(String(64), primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False)


class CertificateRecordModel(RegistryBase):
    __tablename__ = "registry_certificates"

    cert_id = Column(String(36), primary_key=True)
    issuer_id = Column(String(64), ForeignKey("issuers.id"), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    envelope = Column(JSON, nullable=False)
    leaf_index = Column(BigInteger, nullable=False, unique=True)
    issued_at = Column(DateTime, nullable=False)
    received_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    revocation_reason = Column(String(255), nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    issuer = relationship("IssuerModel", back_populates="certificates")
    log_entry = relationship("LogEntryModel", back_populates="certificate", uselist=False)


class LogEntryModel(RegistryBase):
    __tablename__ = "log_entries"

    leaf_index = Column(BigInteger, primary_key=True)
    cert_id = Column(String(36), ForeignKey("registry_certificates.cert_id"), nullable=False)
    leaf_hash = Column(String(64), nullable=False)
    data = Column(Text, nullable=False)

    certificate = relationship("CertificateRecordModel", back_populates="log_entry")


class TreeHeadModel(RegistryBase):
    __tablename__ = "tree_heads"

    tree_size = Column(BigInteger, primary_key=True)
    root_hash = Column(String(64), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    signature = Column(String(255), nullable=False)
