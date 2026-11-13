"""Registry database session management."""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from rctyping_registry.config import registry_settings
from rctyping_registry.db.models import RegistryBase

_engine = None
_SessionFactory = None


def get_registry_engine(db_path: Path | None = None):
    global _engine, _SessionFactory
    if _engine is None:
        target = db_path or (registry_settings.data_dir / "registry.db")
        target.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{target.as_posix()}"
        _engine = create_engine(db_url, connect_args={"check_same_thread": False})
        _SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def init_registry_db(db_path: Path | None = None):
    eng = get_registry_engine(db_path)
    RegistryBase.metadata.create_all(bind=eng)


def get_registry_session() -> Session:
    if _SessionFactory is None:
        init_registry_db()
    assert _SessionFactory is not None
    return _SessionFactory()


def get_registry_db():
    db = get_registry_session()
    try:
        yield db
    finally:
        db.close()

