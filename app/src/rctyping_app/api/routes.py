"""FastAPI routes for rc-typing application."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from rctyping_app.core.keystore import KeyStore
from rctyping_app.db.models import (
    CertificateModel,
    PublishJobModel,
    SessionModel,
    UserModel,
    UserSettingsModel,
)
from rctyping_app.db.session import DEFAULT_USER_ID, get_db
from rctyping_app.services.certificate_service import CertificateService
from rctyping_app.services.session_service import SessionService
from rctyping_common.certificate import (
    calculate_key_id,
    public_key_from_b64url,
    public_key_from_pem,
    verify_certificate_envelope,
)
from rctyping_common.corpus import CorpusRepository
from rctyping_common.models import (
    CertificateEnvelope,
    KeystrokeEvent,
    Metrics,
    VerificationResult,
)

router = APIRouter()


# Multi-user readiness: current_user dependency
def get_current_user_id() -> str:
    """Dependency returning current user ID.

    In v1, returns default user ID.
    Can be easily swapped to session cookies, JWTs, or OIDC tokens later.
    """
    return DEFAULT_USER_ID


# Request / Response Schemas
class StartSessionRequest(BaseModel):
    category: str
    language: Optional[str] = None


class StartSessionResponse(BaseModel):
    session_id: str
    category: str
    language: Optional[str] = None
    nonce: str
    passage: Dict[str, Any]


class FinishSessionRequest(BaseModel):
    events: List[KeystrokeEvent]
    subject_name: Optional[str] = None


class FinishSessionResponse(BaseModel):
    certificate: CertificateEnvelope
    metrics: Metrics
    registry_status: str


class SettingsUpdateRequest(BaseModel):
    publish_to_registry: Optional[bool] = None
    default_cert_name: Optional[str] = None
    registry_url: Optional[str] = None


def get_corpus_repo() -> CorpusRepository:
    from rctyping_app.main import app_corpus
    if app_corpus is None:
        raise HTTPException(status_code=503, detail="Corpus repository not initialized")
    return app_corpus


def get_keystore() -> KeyStore:
    from rctyping_app.main import app_keystore
    if app_keystore is None:
        raise HTTPException(status_code=503, detail="KeyStore not initialized")
    return app_keystore


@router.get("/categories")
def get_categories(corpus_repo: CorpusRepository = Depends(get_corpus_repo)) -> Dict[str, List[str]]:
    return corpus_repo.list_categories()


@router.post("/sessions", response_model=StartSessionResponse)
def start_session(
    req: StartSessionRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    corpus_repo: CorpusRepository = Depends(get_corpus_repo),
):
    service = SessionService(db, corpus_repo)
    try:
        session, passage = service.start_session(user_id, req.category, req.language)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return StartSessionResponse(
        session_id=session.id,
        category=session.category,
        language=session.language,
        nonce=session.nonce,
        passage={
            "id": passage.id,
            "title": passage.title,
            "text": passage.text,
            "difficulty": passage.difficulty,
            "license": passage.license,
            "author": passage.author,
            "source": passage.source,
        },
    )


@router.post("/sessions/{session_id}/finish", response_model=FinishSessionResponse)
def finish_session(
    session_id: str,
    req: FinishSessionRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    keystore: KeyStore = Depends(get_keystore),
    corpus_repo: CorpusRepository = Depends(get_corpus_repo),
):
    service = CertificateService(db, keystore, corpus_repo)
    try:
        envelope, metrics, reg_status = service.finish_session_and_issue_certificate(
            session_id=session_id,
            user_id=user_id,
            events=req.events,
            subject_name=req.subject_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return FinishSessionResponse(
        certificate=envelope,
        metrics=metrics,
        registry_status=reg_status,
    )


@router.get("/certificates/{cert_id}")
def get_certificate(cert_id: str, db: Session = Depends(get_db)):
    cert = db.query(CertificateModel).filter(CertificateModel.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    job = db.query(PublishJobModel).filter(PublishJobModel.cert_id == cert_id).first()
    return {
        "envelope": cert.envelope,
        "registry_status": cert.registry_status,
        "receipt": job.receipt if job else None,
        "created_at": cert.created_at.isoformat(),
    }


@router.get("/certificates/{cert_id}/download")
def download_certificate(cert_id: str, db: Session = Depends(get_db)):
    cert = db.query(CertificateModel).filter(CertificateModel.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    import json
    content = json.dumps(cert.envelope, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=certificate-{cert_id}.json"},
    )


@router.post("/certificates/{cert_id}/publish")
def retry_publish(cert_id: str, db: Session = Depends(get_db)):
    job = db.query(PublishJobModel).filter(PublishJobModel.cert_id == cert_id).first()
    if not job:
        job = PublishJobModel(cert_id=cert_id, state="pending")
        db.add(job)
    else:
        job.state = "pending"
        job.attempts = 0
    db.commit()
    return {"status": "publish_queued"}


@router.get("/stats")
def get_stats(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    certs = db.query(CertificateModel).filter(CertificateModel.user_id == user_id).all()
    categories_stats: Dict[str, Any] = {}

    for c in certs:
        cat_key = f"{c.category}_{c.language}" if c.language else c.category
        if cat_key not in categories_stats:
            categories_stats[cat_key] = {
                "category": c.category,
                "language": c.language,
                "tests_completed": 0,
                "best_net_wpm": 0.0,
                "best_raw_wpm": 0.0,
                "total_wpm": 0.0,
                "total_accuracy": 0.0,
            }
        stat = categories_stats[cat_key]
        stat["tests_completed"] += 1
        stat["best_net_wpm"] = max(stat["best_net_wpm"], c.net_wpm)
        stat["total_wpm"] += c.net_wpm
        stat["total_accuracy"] += c.accuracy

    for cat_key, stat in categories_stats.items():
        count = stat["tests_completed"]
        stat["avg_net_wpm"] = round(stat["total_wpm"] / count, 1)
        stat["avg_accuracy"] = round(stat["total_accuracy"] / count, 3)
        del stat["total_wpm"]
        del stat["total_accuracy"]

    return {
        "total_certificates": len(certs),
        "by_category": categories_stats,
    }


@router.get("/settings")
def get_settings(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    s = db.query(UserSettingsModel).filter(UserSettingsModel.user_id == user_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")
    return {
        "publish_to_registry": s.publish_to_registry,
        "registry_url": s.registry_url,
        "default_cert_name": s.default_cert_name,
    }


@router.put("/settings")
def update_settings(
    req: SettingsUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    s = db.query(UserSettingsModel).filter(UserSettingsModel.user_id == user_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Settings not found")
    if req.publish_to_registry is not None:
        s.publish_to_registry = req.publish_to_registry
    if req.default_cert_name is not None:
        s.default_cert_name = req.default_cert_name
    if req.registry_url is not None:
        s.registry_url = req.registry_url
    db.commit()
    return {
        "publish_to_registry": s.publish_to_registry,
        "registry_url": s.registry_url,
        "default_cert_name": s.default_cert_name,
    }


@router.post("/verify", response_model=VerificationResult)
def verify_certificate_endpoint(envelope: CertificateEnvelope):
    """Verify an uploaded or pasted certificate envelope mathematically."""
    is_valid = verify_certificate_envelope(envelope)
    if not is_valid:
        return VerificationResult(
            valid=False,
            status="INVALID_SIGNATURE",
            trust_tier="unverified",
            details="Cryptographic signature verification failed or payload has been tampered with.",
            payload=envelope.payload,
        )

    return VerificationResult(
        valid=True,
        status="VALID_OFFLINE",
        trust_tier="unverified",
        details="Ed25519 signature verified successfully over canonical certificate payload.",
        payload=envelope.payload,
    )
