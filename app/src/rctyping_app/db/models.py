"""SQLAlchemy models for rc-typing application."""

from __future__ import annotations

import datetime
import uuid
from typing import Optional
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name = Column(String(64), nullable=False, default="Anonymous Typist")
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    settings = relationship("UserSettingsModel", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sessions = relationship("SessionModel", back_populates="user", cascade="all, delete-orphan")
    certificates = relationship("CertificateModel", back_populates="user", cascade="all, delete-orphan")
    thought_folders = relationship("ThoughtFolderModel", back_populates="user", cascade="all, delete-orphan")
    thoughts = relationship("ThoughtModel", back_populates="user", cascade="all, delete-orphan")


class UserSettingsModel(Base):
    __tablename__ = "user_settings"

    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    publish_to_registry = Column(Boolean, default=True, nullable=False)
    registry_url = Column(String(255), nullable=True)
    default_cert_name = Column(String(64), default="Anonymous Typist", nullable=False)

    user = relationship("UserModel", back_populates="settings")
    # Keep UserModel relationships intact below


class ThoughtFolderModel(Base):
    __tablename__ = "thought_folders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False)
    parent_id = Column(String(36), ForeignKey("thought_folders.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    user = relationship("UserModel", back_populates="thought_folders")
    thoughts = relationship("ThoughtModel", back_populates="folder")


class ThoughtModel(Base):
    __tablename__ = "thoughts"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    folder_id = Column(String(36), ForeignKey("thought_folders.id"), nullable=True)
    filename = Column(String(160), nullable=False)
    wpm = Column(Float, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    chars_typed = Column(Integer, nullable=False)
    encrypted_content = Column(Text, nullable=False)
    encryption_alg = Column(String(32), default="AES-256-GCM", nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    user = relationship("UserModel", back_populates="thoughts")
    folder = relationship("ThoughtFolderModel", back_populates="thoughts")


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    category = Column(String(32), nullable=False)
    language = Column(String(32), nullable=True)
    passage_id = Column(String(64), nullable=False)
    nonce = Column(String(64), nullable=False)
    started_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="in_progress", nullable=False)
    raw_events = Column(JSON, nullable=True)

    user = relationship("UserModel", back_populates="sessions")
    certificate = relationship("CertificateModel", back_populates="session", uselist=False)


class CertificateModel(Base):
    __tablename__ = "certificates"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    envelope = Column(JSON, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    category = Column(String(32), nullable=False)
    language = Column(String(32), nullable=True)
    net_wpm = Column(Float, nullable=False)
    accuracy = Column(Float, nullable=False)
    integrity = Column(String(32), default="clean", nullable=False)
    assurance = Column(String(32), default="heuristic-checked", nullable=False)
    registry_status = Column(String(32), default="pending", nullable=False)  # local_only, pending, published, failed
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    user = relationship("UserModel", back_populates="certificates")
    session = relationship("SessionModel", back_populates="certificate")
    publish_job = relationship("PublishJobModel", back_populates="certificate", uselist=False, cascade="all, delete-orphan")


class PublishJobModel(Base):
    __tablename__ = "publish_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cert_id = Column(String(36), ForeignKey("certificates.id"), nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    next_attempt_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)
    state = Column(String(32), default="pending", nullable=False)  # pending, processing, completed, failed
    last_error = Column(Text, nullable=True)
    receipt = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False)

    certificate = relationship("CertificateModel", back_populates="publish_job")
