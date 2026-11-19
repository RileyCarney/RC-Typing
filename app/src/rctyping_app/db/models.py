"""SQLAlchemy models for rc-typing application."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name: Mapped[str] = mapped_column(String(64), nullable=False, default="Anonymous Typist")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    settings: Mapped[Optional[UserSettingsModel]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sessions: Mapped[list[SessionModel]] = relationship(back_populates="user", cascade="all, delete-orphan")
    certificates: Mapped[list[CertificateModel]] = relationship(back_populates="user", cascade="all, delete-orphan")
    thought_folders: Mapped[list[ThoughtFolderModel]] = relationship(back_populates="user", cascade="all, delete-orphan")
    thoughts: Mapped[list[ThoughtModel]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSettingsModel(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    publish_to_registry: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    registry_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    default_cert_name: Mapped[str] = mapped_column(String(64), default="Anonymous Typist", nullable=False)

    user: Mapped[UserModel] = relationship(back_populates="settings")


class ThoughtFolderModel(Base):
    __tablename__ = "thought_folders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("thought_folders.id"), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    user: Mapped[UserModel] = relationship(back_populates="thought_folders")
    thoughts: Mapped[list[ThoughtModel]] = relationship(back_populates="folder")


class ThoughtModel(Base):
    __tablename__ = "thoughts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    folder_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("thought_folders.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(160), nullable=False)
    wpm: Mapped[float] = mapped_column(Float, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    chars_typed: Mapped[int] = mapped_column(Integer, nullable=False)
    encrypted_content: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_alg: Mapped[str] = mapped_column(String(32), default="AES-256-GCM", nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    user: Mapped[UserModel] = relationship(back_populates="thoughts")
    folder: Mapped[Optional[ThoughtFolderModel]] = relationship(back_populates="thoughts")


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    passage_id: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    finished_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="in_progress", nullable=False)
    raw_events: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)

    user: Mapped[UserModel] = relationship(back_populates="sessions")
    certificate: Mapped[Optional[CertificateModel]] = relationship(back_populates="session", uselist=False)


class CertificateModel(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False)
    envelope: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    net_wpm: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    integrity: Mapped[str] = mapped_column(String(32), default="clean", nullable=False)
    assurance: Mapped[str] = mapped_column(String(32), default="heuristic-checked", nullable=False)
    registry_status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )  # local_only, pending, published, failed
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    user: Mapped[UserModel] = relationship(back_populates="certificates")
    session: Mapped[SessionModel] = relationship(back_populates="certificate")
    publish_job: Mapped[Optional[PublishJobModel]] = relationship(
        back_populates="certificate", uselist=False, cascade="all, delete-orphan"
    )


class PublishJobModel(Base):
    __tablename__ = "publish_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    cert_id: Mapped[str] = mapped_column(String(36), ForeignKey("certificates.id"), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )
    state: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )  # pending, processing, completed, failed
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receipt: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), nullable=False
    )

    certificate: Mapped[CertificateModel] = relationship(back_populates="publish_job")
