"""Database session and initialization."""

from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from rctyping_app.config import settings
from rctyping_app.db.models import Base, UserModel, UserSettingsModel

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def reset_db() -> None:
    """Dispose and clear cached engine/session factory."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None


def get_engine(db_path: Path | None = None):
    global _engine, _SessionFactory
    if _engine is None:
        target = db_path or (settings.data_dir / "rctyping.db")
        target.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{target.as_posix()}"
        _engine = create_engine(db_url, connect_args={"check_same_thread": False})
        _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def get_app_session() -> Session:
    if _SessionFactory is None:
        init_db()
    assert _SessionFactory is not None
    return _SessionFactory()


def _migrate_schema(eng: Engine) -> None:
    """Apply lightweight, idempotent schema migrations for existing SQLite databases."""
    inspector = inspect(eng)
    if inspector.has_table("thoughts"):
        thought_columns = {col["name"] for col in inspector.get_columns("thoughts")}
        if "encrypted_markdown" in thought_columns:
            with eng.begin() as conn:
                conn.execute(text("ALTER TABLE thoughts DROP COLUMN encrypted_markdown"))


def init_db(db_path: Path | None = None):
    eng = get_engine(db_path)
    Base.metadata.create_all(bind=eng)
    _migrate_schema(eng)

    # Seed default user if not present
    with get_app_session() as db:
        user = db.query(UserModel).filter(UserModel.id == DEFAULT_USER_ID).first()
        if not user:
            user = UserModel(id=DEFAULT_USER_ID, display_name="Anonymous Typist")
            user_settings = UserSettingsModel(
                user_id=DEFAULT_USER_ID,
                publish_to_registry=settings.publish_default,
                registry_url=settings.registry_url,
                default_cert_name="Anonymous Typist",
            )
            db.add(user)
            db.add(user_settings)
            db.commit()


def get_db():
    db = get_app_session()
    try:
        yield db
    finally:
        db.close()

