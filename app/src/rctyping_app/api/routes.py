"""FastAPI routes for rc-typing application."""

from __future__ import annotations

import datetime
import io
import re
import uuid
import zipfile
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from rctyping_app.core.keystore import KeyStore
from rctyping_app.db.models import (
    CertificateModel,
    PublishJobModel,
    ThoughtFolderModel,
    ThoughtModel,
    UserSettingsModel,
)
from rctyping_app.db.session import DEFAULT_USER_ID, get_db
from rctyping_app.services.certificate_service import CertificateService
from rctyping_app.services.session_service import SessionService
from rctyping_common.certificate import verify_certificate_envelope
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


@router.post("/sessions/{session_id}/start")
def start_session_typing(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    corpus_repo: CorpusRepository = Depends(get_corpus_repo),
):
    service = SessionService(db, corpus_repo)
    session = service.mark_session_started(session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "started"}


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
    cert = db.query(CertificateModel).filter(CertificateModel.id == cert_id).first()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    now = datetime.datetime.now(datetime.timezone.utc)
    job = db.query(PublishJobModel).filter(PublishJobModel.cert_id == cert_id).first()
    if not job:
        job = PublishJobModel(cert_id=cert_id, state="pending", next_attempt_at=now)
        db.add(job)
    else:
        job.state = "pending"
        job.attempts = 0
        job.next_attempt_at = now
    cert.registry_status = "pending"
    db.commit()
    return {"status": "publish_queued"}


@router.get("/stats")
def get_stats(user_id: str = Depends(get_current_user_id), db: Session = Depends(get_db)):
    certs = (
        db.query(CertificateModel)
        .filter(CertificateModel.user_id == user_id, CertificateModel.integrity == "clean")
        .all()
    )
    categories_stats: Dict[str, Any] = {}

    for c in certs:
        cat_key = f"{c.category}_{c.language}" if c.language else c.category
        if cat_key not in categories_stats:
            categories_stats[cat_key] = {
                "category": c.category,
                "language": c.language,
                "tests_completed": 0,
                "best_net_wpm": 0.0,
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


# --- Typing Thoughts & Brain Schemas/Helpers ---


class CreateFolderRequest(BaseModel):
    name: str
    parent_id: Optional[str] = None


class CreateThoughtRequest(BaseModel):
    content: str
    duration_ms: int = Field(..., ge=1)
    wpm: Optional[float] = Field(None, ge=0.0)
    folder_id: Optional[str] = None
    filename: Optional[str] = None


class UpdateThoughtRequest(BaseModel):
    folder_id: Optional[str] = None
    move_to_root: bool = False
    filename: Optional[str] = None


def _sanitize_folder_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name.strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(". ")
    if not cleaned or cleaned in (".", ".."):
        raise HTTPException(status_code=400, detail="Folder name must be a valid non-empty name")
    return cleaned[:128]


def slugify_filename(text: str, custom_name: Optional[str] = None) -> str:
    raw = (custom_name or "").strip()
    if raw:
        base = re.sub(r"\.md$", "", raw, flags=re.IGNORECASE)
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("-._")
    else:
        words = re.findall(r"[a-zA-Z0-9]+", text.lower())[:6]
        slug = "-".join(words)
    if not slug or slug in (".", ".."):
        slug = f"thought-{uuid.uuid4().hex[:8]}"
    return f"{slug[:120]}.md"


def format_duration_human(duration_ms: int) -> str:
    seconds = max(0.0, duration_ms / 1000.0)
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins = int(seconds // 60)
    rem = seconds % 60
    return f"{mins}m {rem:.1f}s"


def resolve_folder_path(folder_id: Optional[str], folders_by_id: Dict[str, ThoughtFolderModel]) -> str:
    if not folder_id:
        return ""
    parts: List[str] = []
    seen = set()
    curr_id: Optional[str] = folder_id
    while curr_id and curr_id in folders_by_id and curr_id not in seen:
        seen.add(curr_id)
        folder = folders_by_id[curr_id]
        parts.append(folder.name)
        curr_id = folder.parent_id
    parts.reverse()
    return "/".join(parts)


def build_thought_markdown(
    filename: str,
    content: str,
    wpm: float,
    duration_ms: int,
    folder_path: str,
    created_at_iso: str,
) -> str:
    title = filename[:-3] if filename.endswith(".md") else filename
    total_time = format_duration_human(duration_ms)
    folder_display = folder_path or "/"
    return (
        "---\n"
        f'title: "{title}"\n'
        f"created_at: {created_at_iso}\n"
        f"wpm: {wpm}\n"
        f"duration_ms: {duration_ms}\n"
        f"total_time: {total_time}\n"
        f'folder: "{folder_display}"\n'
        "---\n\n"
        f"{content}\n"
    )


def _utc_iso(dt: datetime.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.isoformat()


def _serialize_thought(
    thought: ThoughtModel,
    folders_by_id: Dict[str, ThoughtFolderModel],
    keystore: KeyStore,
) -> Dict[str, Any]:
    content = keystore.decrypt_text(thought.encrypted_content)
    folder_path = resolve_folder_path(thought.folder_id, folders_by_id)
    created_at_iso = _utc_iso(thought.created_at)
    markdown = build_thought_markdown(
        filename=thought.filename,
        content=content,
        wpm=thought.wpm,
        duration_ms=thought.duration_ms,
        folder_path=folder_path,
        created_at_iso=created_at_iso,
    )
    return {
        "id": thought.id,
        "filename": thought.filename,
        "folder_id": thought.folder_id,
        "folder_path": folder_path,
        "content": content,
        "markdown": markdown,
        "wpm": thought.wpm,
        "duration_ms": thought.duration_ms,
        "total_time": format_duration_human(thought.duration_ms),
        "chars_typed": thought.chars_typed,
        "encryption_alg": thought.encryption_alg,
        "created_at": created_at_iso,
    }


@router.get("/thoughts/brain")
def get_thoughts_brain(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    keystore: KeyStore = Depends(get_keystore),
):
    folders = (
        db.query(ThoughtFolderModel)
        .filter(ThoughtFolderModel.user_id == user_id)
        .order_by(ThoughtFolderModel.name.asc())
        .all()
    )
    folders_by_id = {f.id: f for f in folders}
    thoughts = (
        db.query(ThoughtModel)
        .filter(ThoughtModel.user_id == user_id)
        .order_by(ThoughtModel.created_at.desc())
        .all()
    )
    return {
        "encryption": {
            "enabled": True,
            "algorithm": "AES-256-GCM",
            "key_id": keystore.key_id,
        },
        "folders": [
            {
                "id": f.id,
                "name": f.name,
                "parent_id": f.parent_id,
                "path": resolve_folder_path(f.id, folders_by_id),
                "created_at": f.created_at.isoformat(),
            }
            for f in folders
        ],
        "thoughts": [_serialize_thought(t, folders_by_id, keystore) for t in thoughts],
    }


@router.post("/thoughts/folders")
def create_thought_folder(
    req: CreateFolderRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    clean_name = _sanitize_folder_name(req.name)
    parent_id = req.parent_id if req.parent_id and req.parent_id != "root" else None
    if parent_id:
        parent = (
            db.query(ThoughtFolderModel)
            .filter(ThoughtFolderModel.id == parent_id, ThoughtFolderModel.user_id == user_id)
            .first()
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")

    folder = ThoughtFolderModel(user_id=user_id, name=clean_name, parent_id=parent_id)
    db.add(folder)
    db.commit()
    db.refresh(folder)

    all_folders = db.query(ThoughtFolderModel).filter(ThoughtFolderModel.user_id == user_id).all()
    folders_by_id = {f.id: f for f in all_folders}
    return {
        "id": folder.id,
        "name": folder.name,
        "parent_id": folder.parent_id,
        "path": resolve_folder_path(folder.id, folders_by_id),
        "created_at": folder.created_at.isoformat(),
    }


@router.delete("/thoughts/folders/{folder_id}")
def delete_thought_folder(
    folder_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    folder = (
        db.query(ThoughtFolderModel)
        .filter(ThoughtFolderModel.id == folder_id, ThoughtFolderModel.user_id == user_id)
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    # Re-parent contained thoughts and subfolders so nothing is lost
    db.query(ThoughtModel).filter(
        ThoughtModel.user_id == user_id, ThoughtModel.folder_id == folder.id
    ).update({"folder_id": folder.parent_id})
    db.query(ThoughtFolderModel).filter(
        ThoughtFolderModel.user_id == user_id, ThoughtFolderModel.parent_id == folder.id
    ).update({"parent_id": folder.parent_id})
    db.delete(folder)
    db.commit()
    return {"deleted": folder_id}


@router.post("/thoughts")
def push_thought(
    req: CreateThoughtRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    keystore: KeyStore = Depends(get_keystore),
):
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Thought content cannot be empty")

    folder_id = req.folder_id if req.folder_id and req.folder_id != "root" else None
    all_folders = db.query(ThoughtFolderModel).filter(ThoughtFolderModel.user_id == user_id).all()
    folders_by_id = {f.id: f for f in all_folders}
    if folder_id and folder_id not in folders_by_id:
        raise HTTPException(status_code=404, detail="Target folder not found")

    chars_typed = len(content)
    computed_wpm = (
        round(req.wpm, 1)
        if req.wpm is not None
        else round((chars_typed / 5.0) / max(req.duration_ms / 60000.0, 0.001), 1)
    )
    filename = slugify_filename(content, req.filename)
    created_at = datetime.datetime.now(datetime.timezone.utc)

    thought = ThoughtModel(
        user_id=user_id,
        folder_id=folder_id,
        filename=filename,
        wpm=computed_wpm,
        duration_ms=req.duration_ms,
        chars_typed=chars_typed,
        encrypted_content=keystore.encrypt_text(content),
        encryption_alg="AES-256-GCM",
        created_at=created_at,
    )
    db.add(thought)
    db.commit()
    db.refresh(thought)
    return _serialize_thought(thought, folders_by_id, keystore)


@router.patch("/thoughts/{thought_id}")
def update_thought(
    thought_id: str,
    req: UpdateThoughtRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    keystore: KeyStore = Depends(get_keystore),
):
    thought = (
        db.query(ThoughtModel)
        .filter(ThoughtModel.id == thought_id, ThoughtModel.user_id == user_id)
        .first()
    )
    if not thought:
        raise HTTPException(status_code=404, detail="Thought not found")

    all_folders = db.query(ThoughtFolderModel).filter(ThoughtFolderModel.user_id == user_id).all()
    folders_by_id = {f.id: f for f in all_folders}

    if req.move_to_root or req.folder_id == "root":
        thought.folder_id = None
    elif req.folder_id is not None:
        if req.folder_id not in folders_by_id:
            raise HTTPException(status_code=404, detail="Target folder not found")
        thought.folder_id = req.folder_id

    if req.filename is not None:
        content = keystore.decrypt_text(thought.encrypted_content)
        thought.filename = slugify_filename(content, req.filename)

    db.commit()
    db.refresh(thought)
    return _serialize_thought(thought, folders_by_id, keystore)


@router.delete("/thoughts/{thought_id}")
def delete_thought(
    thought_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    thought = (
        db.query(ThoughtModel)
        .filter(ThoughtModel.id == thought_id, ThoughtModel.user_id == user_id)
        .first()
    )
    if not thought:
        raise HTTPException(status_code=404, detail="Thought not found")
    db.delete(thought)
    db.commit()
    return {"deleted": thought_id}


@router.get("/thoughts/export-zip")
def export_thoughts_zip(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
    keystore: KeyStore = Depends(get_keystore),
):
    folders = db.query(ThoughtFolderModel).filter(ThoughtFolderModel.user_id == user_id).all()
    folders_by_id = {f.id: f for f in folders}
    thoughts = (
        db.query(ThoughtModel)
        .filter(ThoughtModel.user_id == user_id)
        .order_by(ThoughtModel.created_at.asc())
        .all()
    )

    buf = io.BytesIO()
    used_paths: set[str] = set()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in folders:
            fpath = resolve_folder_path(f.id, folders_by_id)
            if fpath:
                zf.writestr(f"{fpath}/", "")

        for t in thoughts:
            folder_path = resolve_folder_path(t.folder_id, folders_by_id)
            rel_path = f"{folder_path}/{t.filename}" if folder_path else t.filename
            if rel_path in used_paths:
                stem = t.filename[:-3] if t.filename.endswith(".md") else t.filename
                rel_path = (
                    f"{folder_path}/{stem}-{t.id[:6]}.md"
                    if folder_path
                    else f"{stem}-{t.id[:6]}.md"
                )
            used_paths.add(rel_path)
            content = keystore.decrypt_text(t.encrypted_content)
            markdown = build_thought_markdown(
                filename=t.filename,
                content=content,
                wpm=t.wpm,
                duration_ms=t.duration_ms,
                folder_path=folder_path,
                created_at_iso=_utc_iso(t.created_at),
            )
            zf.writestr(rel_path, markdown.encode("utf-8"))

    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=typing-thoughts-brain.zip"},
    )
