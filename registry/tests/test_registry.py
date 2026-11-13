import datetime
import hashlib
import uuid
import pytest
from fastapi.testclient import TestClient

from rctyping_common.canonical import canonical_json_dumps, canonical_json_hash
from rctyping_common.certificate import (
    b64url_encode,
    calculate_key_id,
    generate_keypair,
    public_key_to_b64url,
    sign_certificate,
)
from rctyping_common.merkle import verify_inclusion_proof
from rctyping_common.models import CertificatePayload, Metrics
from rctyping_registry.main import app


def test_registry_lifecycle_and_transparency_log():
    with TestClient(app) as client:
        # 1. Check registry info
        info_resp = client.get("/.well-known/rctyping-registry.json")
        assert info_resp.status_code == 200
        info = info_resp.json()
        assert "registry_public_key_b64" in info

        # 2. Generate issuer keypair and request registration challenge
        priv, pub = generate_keypair()
        issuer_id = calculate_key_id(pub)
        pub_b64 = public_key_to_b64url(pub)

        chal_resp = client.post("/v1/issuers/challenge")
        assert chal_resp.status_code == 200
        challenge = chal_resp.json()["challenge"]

        # 3. Sign challenge and register issuer
        sig_bytes = priv.sign(challenge.encode("utf-8"))
        reg_resp = client.post(
            "/v1/issuers",
            json={
                "public_key": pub_b64,
                "challenge": challenge,
                "signature": b64url_encode(sig_bytes),
            },
        )
        assert reg_resp.status_code == 200
        assert reg_resp.json()["issuer_id"] == issuer_id

        # 4. Create and sign a certificate
        cert_id = str(uuid.uuid4())
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        payload = CertificatePayload(
            version=1,
            cert_id=cert_id,
            issued_at=now_str,
            subject="Registry Tester",
            category="code",
            language="sql",
            passage_id="sql-001",
            passage_sha256="00" * 32,
            metrics=Metrics(
                net_wpm=92.0,
                raw_wpm=95.0,
                accuracy=0.99,
                consistency=0.95,
                duration_ms=30000,
                chars_total=250,
                chars_correct=248,
                chars_incorrect=2,
            ),
            keystroke_log_sha256="11" * 32,
            integrity="clean",
            assurance="heuristic-checked",
            nonce="22" * 16,
            issuer_id=issuer_id,
            alg="Ed25519",
        )
        envelope = sign_certificate(payload, priv)

        # 5. Publish certificate to registry with signed HTTP headers
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        body_bytes = canonical_json_dumps(envelope.model_dump())
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        sig_target = f"{issuer_id}:{ts}:{body_hash}".encode("utf-8")
        req_sig = b64url_encode(priv.sign(sig_target))

        headers = {
            "X-Issuer-Id": issuer_id,
            "X-Timestamp": ts,
            "X-Signature": req_sig,
        }

        pub_resp = client.post("/v1/certificates", json=envelope.model_dump(), headers=headers)
        assert pub_resp.status_code == 200
        receipt = pub_resp.json()
        assert receipt["cert_id"] == cert_id
        leaf_idx = receipt["leaf_index"]
        proof = receipt["inclusion_proof"]
        head = receipt["signed_tree_head"]

        # 6. Verify inclusion proof mathematically
        assert verify_inclusion_proof(
            leaf_data=body_bytes,
            leaf_index=leaf_idx,
            tree_size=receipt["tree_size"],
            audit_path=proof["audit_path"],
            expected_root_hex=head["root_hash"],
        ) is True

        # 7. Query certificate from registry
        query_resp = client.get(f"/v1/certificates/{cert_id}")
        assert query_resp.status_code == 200
        q_data = query_resp.json()
        assert q_data["envelope"]["payload"]["cert_id"] == cert_id
        assert q_data["is_revoked"] is False

        # 8. Revoke certificate
        revoke_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        revoke_target = f"revoke:{cert_id}:{revoke_ts}".encode("utf-8")
        revoke_sig = b64url_encode(priv.sign(revoke_target))
        revoke_headers = {
            "X-Issuer-Id": issuer_id,
            "X-Timestamp": revoke_ts,
            "X-Signature": revoke_sig,
        }
        rev_resp = client.post(
            f"/v1/certificates/{cert_id}/revoke",
            json={"reason": "User test revocation"},
            headers=revoke_headers,
        )
        assert rev_resp.status_code == 200
        assert rev_resp.json()["status"] == "revoked"

        # Check revoked status
        re_query = client.get(f"/v1/certificates/{cert_id}")
        assert re_query.json()["is_revoked"] is True
