"""Certificate generation, signing, and verification service."""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from typing import List, Optional
from sqlalchemy.orm import Session

from rctyping_app.config import settings
from rctyping_app.core.anticheat import evaluate_keystroke_integrity
from rctyping_app.core.keystore import KeyStore
from rctyping_app.core.scoring import compute_metrics
from rctyping_app.db.models import (
    CertificateModel,
    PublishJobModel,
    SessionModel,
    UserSettingsModel,
)
from rctyping_common.canonical import canonical_json_hash
from rctyping_common.certificate import sign_certificate
from rctyping_common.corpus import CorpusRepository
from rctyping_common.models import (
    CertificateEnvelope,
    CertificatePayload,
    KeystrokeEvent,
    Metrics,
    sanitize_display_name,
)


class CertificateService:

    def __init__(
        self,
        db: Session,
        keystore: KeyStore,
        corpus_repo: CorpusRepository,
    ) -> None:
        self.db = db
        self.keystore = keystore
        self.corpus_repo = corpus_repo

    def finish_session_and_issue_certificate(
        self,
        session_id: str,
        user_id: str,
        events: List[KeystrokeEvent],
        subject_name: Optional[str] = None,
    ) -> tuple[CertificateEnvelope, Metrics, str]:
        session = (
            self.db.query(SessionModel)
            .filter(SessionModel.id == session_id, SessionModel.user_id == user_id)
            .first()
        )
        if not session:
            raise ValueError("Session not found")
        if session.status != "in_progress":
            raise ValueError(f"Session is already in status '{session.status}'")

        finished_at = datetime.datetime.now(datetime.timezone.utc)
        server_duration_ms = int((finished_at - session.started_at.replace(tzinfo=datetime.timezone.utc)).total_seconds() * 1000)

        passage = self.corpus_repo.get_by_id(session.passage_id)
        if not passage:
            raise ValueError(f"Passage '{session.passage_id}' missing from corpus")

        # 1. Compute metrics and replay
        metrics, reconstructed_text = compute_metrics(
            passage.text,
            events,
            server_duration_ms,
            max_clock_skew_ms=settings.max_clock_skew_ms,
        )

        # 2. Evaluate anti-cheat heuristics
        integrity, flags = evaluate_keystroke_integrity(
            events,
            server_duration_ms,
            min_human_iki_ms=settings.min_human_iki_ms,
            min_iki_stddev_ms=settings.min_iki_stddev_ms,
            max_clock_skew_ms=settings.max_clock_skew_ms,
        )

        # 3. Serialized events hash
        raw_events_dict = [e.model_dump() for e in events]
        events_json = json.dumps(raw_events_dict, sort_keys=True, separators=(",", ":"))
        keystroke_log_sha256 = hashlib.sha256(events_json.encode("utf-8")).hexdigest()

        # 4. Determine subject name
        user_settings = (
            self.db.query(UserSettingsModel)
            .filter(UserSettingsModel.user_id == user_id)
            .first()
        )
        chosen_name = subject_name or (user_settings.default_cert_name if user_settings else "Anonymous Typist")
        sanitized_name = sanitize_display_name(chosen_name)

        # 5. Build certificate payload
        cert_id = str(uuid.uuid4())
        payload = CertificatePayload(
            version=1,
            cert_id=cert_id,
            issued_at=finished_at.isoformat(),
            subject=sanitized_name,
            category=session.category,
            language=session.language,
            passage_id=passage.id,
            passage_sha256=passage.sha256,
            metrics=metrics,
            keystroke_log_sha256=keystroke_log_sha256,
            integrity=integrity,
            assurance="heuristic-checked",
            nonce=session.nonce,
            issuer_id=self.keystore.key_id,
            alg="Ed25519",
        )

        # 6. Cryptographically sign the canonical JSON payload
        envelope = sign_certificate(payload, self.keystore.private_key)
        cert_sha256 = canonical_json_hash(envelope.model_dump())

        # 7. Check publish settings
        publish_enabled = user_settings.publish_to_registry if user_settings else True
        registry_status = "pending" if publish_enabled else "local_only"

        # 8. Save models
        cert_model = CertificateModel(
            id=cert_id,
            user_id=user_id,
            session_id=session.id,
            envelope=envelope.model_dump(),
            sha256=cert_sha256,
            category=session.category,
            language=session.language,
            net_wpm=metrics.net_wpm,
            accuracy=metrics.accuracy,
            integrity=integrity,
            assurance="heuristic-checked",
            registry_status=registry_status,
        )
        self.db.add(cert_model)

        if publish_enabled:
            job = PublishJobModel(
                cert_id=cert_id,
                attempts=0,
                next_attempt_at=finished_at,
                state="pending",
            )
            self.db.add(job)

        session.finished_at = finished_at
        session.status = "completed"
        session.raw_events = raw_events_dict

        self.db.commit()
        return envelope, metrics, registry_status
