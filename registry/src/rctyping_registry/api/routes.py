"""Registry REST API routes per RFC 6962 and rc-typing architecture."""

from __future__ import annotations

import datetime
import hashlib
import secrets
from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from rctyping_common.canonical import canonical_json_dumps, canonical_json_hash
from rctyping_common.certificate import (
    b64url_decode,
    calculate_key_id,
    public_key_from_b64url,
    public_key_from_pem,
    verify_certificate_envelope,
)
from rctyping_common.models import (
    CertificateEnvelope,
    InclusionProof,
    RegistryReceipt,
    SignedTreeHead,
    TrustTier,
)
from rctyping_registry.config import registry_settings
from rctyping_registry.core.registry_keystore import RegistryKeyStore
from rctyping_registry.db.models import (
    CertificateRecordModel,
    IssuerModel,
    RegistrationChallengeModel,
)
from rctyping_registry.db.session import get_registry_db
from rctyping_registry.services.log_service import LogService

router = APIRouter()


def get_log_service() -> LogService:
    from rctyping_registry.main import registry_log_service
    if registry_log_service is None:
        raise HTTPException(status_code=503, detail="Registry log service not ready")
    return registry_log_service


def get_registry_keystore() -> RegistryKeyStore:
    from rctyping_registry.main import registry_keystore
    if registry_keystore is None:
        raise HTTPException(status_code=503, detail="Registry keystore not ready")
    return registry_keystore


class IssuerRegistrationRequest(BaseModel):
    public_key: str
    challenge: str
    signature: str


class RevocationRequest(BaseModel):
    reason: str = "User requested certificate revocation"


@router.post("/issuers/challenge")
def request_challenge(db: Session = Depends(get_registry_db)) -> dict[str, str]:
    """Generate a challenge for proof-of-possession during issuer registration."""
    now = datetime.datetime.now(datetime.timezone.utc)
    db.query(RegistrationChallengeModel).filter(RegistrationChallengeModel.expires_at < now).delete()
    token = secrets.token_hex(32)
    expires = now + datetime.timedelta(minutes=5)
    record = RegistrationChallengeModel(challenge=token, created_at=now, expires_at=expires)
    db.add(record)
    db.commit()
    return {"challenge": token, "expires_at": expires.isoformat()}


@router.post("/issuers")
def register_issuer(req: IssuerRegistrationRequest, db: Session = Depends(get_registry_db)) -> dict[str, str]:
    """Register an issuer's public key by verifying proof of possession of the private key."""
    # 1. Verify challenge exists and not expired
    now = datetime.datetime.now(datetime.timezone.utc)
    chal_record = (
        db.query(RegistrationChallengeModel)
        .filter(RegistrationChallengeModel.challenge == req.challenge, RegistrationChallengeModel.expires_at >= now)
        .first()
    )
    if not chal_record:
        raise HTTPException(status_code=400, detail="Invalid or expired registration challenge")

    # 2. Parse public key
    try:
        if req.public_key.startswith("-----BEGIN"):
            pub = public_key_from_pem(req.public_key)
        else:
            pub = public_key_from_b64url(req.public_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid public key format: {e}")

    # 3. Verify signature over challenge
    try:
        sig_bytes = b64url_decode(req.signature)
        pub.verify(sig_bytes, req.challenge.encode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Signature over challenge failed verification")

    # 4. Check if already registered
    key_id = calculate_key_id(pub)
    existing = db.query(IssuerModel).filter(IssuerModel.id == key_id).first()
    if existing:
        db.delete(chal_record)
        db.commit()
        return {"issuer_id": key_id, "status": existing.status, "trust_tier": existing.trust_tier}

    issuer = IssuerModel(
        id=key_id,
        public_key=req.public_key,
        status="active",
        trust_tier="unverified",
    )
    db.add(issuer)
    db.delete(chal_record)
    db.commit()

    return {"issuer_id": key_id, "status": "active", "trust_tier": "unverified"}


@router.get("/issuers/{issuer_id}")
def get_issuer(issuer_id: str, db: Session = Depends(get_registry_db)) -> dict[str, str]:
    issuer = db.query(IssuerModel).filter(IssuerModel.id == issuer_id).first()
    if not issuer:
        raise HTTPException(status_code=404, detail="Issuer not found")
    return {
        "issuer_id": issuer.id,
        "status": issuer.status,
        "trust_tier": issuer.trust_tier,
        "registered_at": issuer.registered_at.isoformat(),
    }


@router.post("/certificates", response_model=RegistryReceipt)
def publish_certificate(
    envelope: CertificateEnvelope,
    x_issuer_id: str = Header(..., alias="X-Issuer-Id"),
    x_timestamp: str = Header(..., alias="X-Timestamp"),
    x_signature: str = Header(..., alias="X-Signature"),
    db: Session = Depends(get_registry_db),
    log_service: LogService = Depends(get_log_service),
) -> RegistryReceipt:
    """Publish a signed certificate to the transparency log."""
    # 1. Lookup issuer
    issuer = db.query(IssuerModel).filter(IssuerModel.id == x_issuer_id).first()
    if not issuer:
        raise HTTPException(status_code=401, detail=f"Issuer '{x_issuer_id}' not registered")
    if issuer.status != "active":
        raise HTTPException(status_code=403, detail=f"Issuer status is '{issuer.status}'")

    # 2. Verify HTTP request signature
    try:
        pub = public_key_from_b64url(issuer.public_key) if not issuer.public_key.startswith("-----BEGIN") else public_key_from_pem(issuer.public_key)
        body_bytes = canonical_json_dumps(envelope.model_dump())
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        sig_target = f"{x_issuer_id}:{x_timestamp}:{body_hash}".encode("utf-8")
        req_sig_bytes = b64url_decode(x_signature)
        pub.verify(req_sig_bytes, sig_target)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid issuer HTTP message signature")

    # 3. Verify certificate internal signature
    if not verify_certificate_envelope(envelope, expected_public_key=pub):
        raise HTTPException(status_code=400, detail="Invalid cryptographic certificate envelope signature")

    cert_id = envelope.payload.cert_id
    cert_sha256 = canonical_json_hash(envelope.model_dump())

    try:
        issued_at_dt = datetime.datetime.fromisoformat(envelope.payload.issued_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid issued_at timestamp")

    with log_service.lock:
        # 4. Check idempotency: if already recorded, return existing receipt
        existing = db.query(CertificateRecordModel).filter(CertificateRecordModel.cert_id == cert_id).first()
        if existing:
            proof = log_service.get_inclusion_proof(existing.leaf_index)
            head = log_service.get_latest_tree_head(db)
            if head is None:
                raise HTTPException(status_code=500, detail="Missing signed tree head for existing certificate")
            return RegistryReceipt(
                cert_id=cert_id,
                cert_sha256=existing.sha256,
                leaf_index=existing.leaf_index,
                tree_size=log_service.tree.size,
                inclusion_proof=proof,
                signed_tree_head=head,
                registered_at=existing.received_at.isoformat(),
            )

        # 5. Append to transparency log and save certificate record atomically
        prev_len = log_service.tree.size
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            leaf_idx, tree_size, proof, signed_head = log_service.append_certificate(
                cert_id=cert_id,
                envelope_dict=envelope.model_dump(),
                db=db,
                commit=False,
            )

            rec = CertificateRecordModel(
                cert_id=cert_id,
                issuer_id=x_issuer_id,
                sha256=cert_sha256,
                envelope=envelope.model_dump(),
                leaf_index=leaf_idx,
                issued_at=issued_at_dt,
                received_at=now,
            )
            db.add(rec)
            db.commit()
        except Exception:
            db.rollback()
            del log_service.tree.leaf_hashes[prev_len:]
            raise

    return RegistryReceipt(
        cert_id=cert_id,
        cert_sha256=cert_sha256,
        leaf_index=leaf_idx,
        tree_size=tree_size,
        inclusion_proof=proof,
        signed_tree_head=signed_head,
        registered_at=now.isoformat(),
    )


@router.get("/certificates/{cert_id}")
def get_certificate_record(
    cert_id: str,
    db: Session = Depends(get_registry_db),
    log_service: LogService = Depends(get_log_service),
) -> dict[str, Any]:
    rec = db.query(CertificateRecordModel).filter(CertificateRecordModel.cert_id == cert_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Certificate not found in registry")

    with log_service.lock:
        proof = log_service.get_inclusion_proof(rec.leaf_index)
        head = log_service.get_latest_tree_head(db)
        tree_size = log_service.tree.size

    return {
        "envelope": rec.envelope,
        "leaf_index": rec.leaf_index,
        "tree_size": tree_size,
        "trust_tier": rec.issuer.trust_tier,
        "issuer_status": rec.issuer.status,
        "is_revoked": rec.is_revoked,
        "revocation_reason": rec.revocation_reason,
        "inclusion_proof": proof.model_dump(),
        "signed_tree_head": head.model_dump() if head else None,
        "registered_at": rec.received_at.isoformat(),
    }


@router.post("/certificates/{cert_id}/revoke")
def revoke_certificate(
    cert_id: str,
    req: RevocationRequest,
    x_issuer_id: str = Header(..., alias="X-Issuer-Id"),
    x_timestamp: str = Header(..., alias="X-Timestamp"),
    x_signature: str = Header(..., alias="X-Signature"),
    db: Session = Depends(get_registry_db),
) -> dict[str, str]:
    rec = db.query(CertificateRecordModel).filter(CertificateRecordModel.cert_id == cert_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if rec.issuer_id != x_issuer_id:
        raise HTTPException(status_code=403, detail="Only issuing authority can revoke this certificate")

    # Verify signature
    try:
        issuer = rec.issuer
        pub = (
            public_key_from_b64url(issuer.public_key)
            if not issuer.public_key.startswith("-----BEGIN")
            else public_key_from_pem(issuer.public_key)
        )
        sig_target = f"revoke:{cert_id}:{x_timestamp}:{req.reason}".encode("utf-8")
        sig_bytes = b64url_decode(x_signature)
        pub.verify(sig_bytes, sig_target)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid revocation signature")

    rec.is_revoked = True
    rec.revocation_reason = req.reason
    rec.revoked_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()

    return {"status": "revoked", "cert_id": cert_id}


@router.get("/log/head", response_model=SignedTreeHead)
def get_tree_head(db: Session = Depends(get_registry_db), log_service: LogService = Depends(get_log_service)) -> SignedTreeHead:
    head = log_service.get_latest_tree_head(db)
    if not head:
        raise HTTPException(status_code=404, detail="No log entries present")
    return head


@router.get("/log/proof/inclusion", response_model=InclusionProof)
def get_inclusion_proof_endpoint(
    leaf_index: int = Query(..., ge=0),
    log_service: LogService = Depends(get_log_service),
) -> InclusionProof:
    try:
        return log_service.get_inclusion_proof(leaf_index)
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/log/proof/consistency")
def get_consistency_proof_endpoint(
    from_size: int = Query(..., ge=0),
    log_service: LogService = Depends(get_log_service),
) -> dict[str, Any]:
    try:
        path = log_service.get_consistency_proof(from_size)
        return {"from_size": from_size, "to_size": log_service.tree.size, "consistency_path": path}
    except IndexError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/issuers/{issuer_id}/tier")
def update_issuer_tier(
    issuer_id: str,
    tier: TrustTier,
    x_admin_token: str = Header(..., alias="X-Admin-Token"),
    db: Session = Depends(get_registry_db),
) -> dict[str, str]:
    if not secrets.compare_digest(x_admin_token, registry_settings.admin_token):
        raise HTTPException(status_code=403, detail="Invalid admin token")
    issuer = db.query(IssuerModel).filter(IssuerModel.id == issuer_id).first()
    if not issuer:
        raise HTTPException(status_code=404, detail="Issuer not found")
    issuer.trust_tier = tier.value
    db.commit()
    return {"issuer_id": issuer_id, "trust_tier": issuer.trust_tier}
