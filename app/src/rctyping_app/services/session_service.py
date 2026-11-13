"""Session management service."""

from __future__ import annotations

import datetime
import secrets
import uuid
from typing import Optional
from sqlalchemy.orm import Session

from rctyping_app.db.models import SessionModel
from rctyping_common.corpus import CorpusRepository, Passage


class SessionService:

    def __init__(self, db: Session, corpus_repo: CorpusRepository) -> None:
        self.db = db
        self.corpus_repo = corpus_repo

    def start_session(
        self,
        user_id: str,
        category: str,
        language: Optional[str] = None,
    ) -> tuple[SessionModel, Passage]:
        passage = self.corpus_repo.get_random_passage(category, language)
        if not passage:
            raise ValueError(f"No passage found for category '{category}', language '{language}'")

        nonce = secrets.token_hex(16)
        session_id = str(uuid.uuid4())
        session = SessionModel(
            id=session_id,
            user_id=user_id,
            category=category,
            language=passage.language,
            passage_id=passage.id,
            nonce=nonce,
            started_at=datetime.datetime.now(datetime.timezone.utc),
            status="in_progress",
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session, passage

    def get_session(self, session_id: str, user_id: str) -> Optional[SessionModel]:
        return (
            self.db.query(SessionModel)
            .filter(SessionModel.id == session_id, SessionModel.user_id == user_id)
            .first()
        )
