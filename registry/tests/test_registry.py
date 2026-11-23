from collections.abc import Generator, Iterator
from contextlib import contextmanager
import datetime
import hashlib
from pathlib import Path
from typing import cast
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient

from rctyping_common.canonical import canonical_json_dumps
from rctyping_common.certificate import (
    b64url_decode,
    b64url_encode,
    calculate_key_id,
    generate_keypair,
    public_key_from_b64url,
    public_key_to_b64url,
    sign_certificate,
)
from rctyping_common.merkle import verify_inclusion_proof
from rctyping_common.models import CertificatePayload, Metrics
from rctyping_registry.main import app


@contextmanager
def _test_client() -> Generator[httpx.Client, None, None]:
    with TestClient(app) as client:
        yield cast(httpx.Client, client)


@pytest.fixture(autouse=True)
def isolated_registry_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import rctyping_registry.db.session as reg_db_session
    from rctyping_registry.config import registry_settings

    reg_db_session.reset_registry_db()
    monkeypatch.setattr(registry_settings, "data_dir", tmp_path / "registry_data")
    yield
    reg_db_session.reset_registry_db()


def test_registry_lifecycle_and_transparency_log():
    with _test_client() as client:
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

        # 3b. Reusing the same challenge fails even though issuer is registered
        reuse_resp = client.post(
            "/v1/issuers",
            json={
                "public_key": pub_b64,
                "challenge": challenge,
                "signature": b64url_encode(sig_bytes),
            },
        )
        assert reuse_resp.status_code == 400

        # Re-registering with a fresh challenge deletes the challenge on early return too
        chal2 = client.post("/v1/issuers/challenge").json()["challenge"]
        sig2 = b64url_encode(priv.sign(chal2.encode("utf-8")))
        rereg_resp = client.post(
            "/v1/issuers",
            json={"public_key": pub_b64, "challenge": chal2, "signature": sig2},
        )
        assert rereg_resp.status_code == 200
        assert (
            client.post(
                "/v1/issuers",
                json={"public_key": pub_b64, "challenge": chal2, "signature": sig2},
            ).status_code
            == 400
        )

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

        # 7. Query certificate and tree head from registry and verify SignedTreeHead signature
        query_resp = client.get(f"/v1/certificates/{cert_id}")
        assert query_resp.status_code == 200
        q_data = query_resp.json()
        assert q_data["envelope"]["payload"]["cert_id"] == cert_id
        assert q_data["is_revoked"] is False

        reg_pub = public_key_from_b64url(info["registry_public_key_b64"])
        sth = q_data["signed_tree_head"]
        sth_msg = f"{sth['tree_size']}:{sth['root_hash']}:{sth['timestamp']}".encode("utf-8")
        reg_pub.verify(b64url_decode(sth["signature"]), sth_msg)

        head_resp = client.get("/v1/log/head")
        assert head_resp.status_code == 200
        head_data = head_resp.json()
        head_msg = f"{head_data['tree_size']}:{head_data['root_hash']}:{head_data['timestamp']}".encode("utf-8")
        reg_pub.verify(b64url_decode(head_data["signature"]), head_msg)

        # 7b. Invalid issued_at rolls back cleanly without corrupting tree size
        bad_payload = payload.model_copy(
            update={"cert_id": str(uuid.uuid4()), "issued_at": "not-a-timestamp"}
        )
        bad_env = sign_certificate(bad_payload, priv)
        bad_bytes = canonical_json_dumps(bad_env.model_dump())
        bad_hash = hashlib.sha256(bad_bytes).hexdigest()
        bad_sig = b64url_encode(priv.sign(f"{issuer_id}:{ts}:{bad_hash}".encode("utf-8")))
        bad_resp = client.post(
            "/v1/certificates",
            json=bad_env.model_dump(),
            headers={"X-Issuer-Id": issuer_id, "X-Timestamp": ts, "X-Signature": bad_sig},
        )
        assert bad_resp.status_code == 400
        assert client.get("/.well-known/rctyping-registry.json").json()["tree_size"] == 1

        # 8. Revoke certificate: bad signature or wrong reason must return 401
        revoke_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        revoke_reason = "User test revocation"
        revoke_target = f"revoke:{cert_id}:{revoke_ts}:{revoke_reason}".encode("utf-8")
        revoke_sig = b64url_encode(priv.sign(revoke_target))

        bad_sig_resp = client.post(
            f"/v1/certificates/{cert_id}/revoke",
            json={"reason": revoke_reason},
            headers={"X-Issuer-Id": issuer_id, "X-Timestamp": revoke_ts, "X-Signature": "not-valid-sig"},
        )
        assert bad_sig_resp.status_code == 401

        tampered_reason_resp = client.post(
            f"/v1/certificates/{cert_id}/revoke",
            json={"reason": "Tampered reason"},
            headers={"X-Issuer-Id": issuer_id, "X-Timestamp": revoke_ts, "X-Signature": revoke_sig},
        )
        assert tampered_reason_resp.status_code == 401

        revoke_headers = {
            "X-Issuer-Id": issuer_id,
            "X-Timestamp": revoke_ts,
            "X-Signature": revoke_sig,
        }
        rev_resp = client.post(
            f"/v1/certificates/{cert_id}/revoke",
            json={"reason": revoke_reason},
            headers=revoke_headers,
        )
        assert rev_resp.status_code == 200
        assert rev_resp.json()["status"] == "revoked"

        # Check revoked status
        re_query = client.get(f"/v1/certificates/{cert_id}")
        assert re_query.json()["is_revoked"] is True


def test_sync_from_db_restores_merkle_root_from_leaf_hashes():
    from rctyping_registry.core.registry_keystore import RegistryKeyStore
    from rctyping_registry.db.models import IssuerModel
    from rctyping_registry.db.session import get_registry_session, init_registry_db
    from rctyping_registry.services.log_service import LogService
    from rctyping_registry.config import registry_settings

    init_registry_db()
    ks = RegistryKeyStore(keys_dir=registry_settings.data_dir / "keys")
    svc1 = LogService(keystore=ks)

    priv, pub = generate_keypair()
    issuer_id = calculate_key_id(pub)
    payload = CertificatePayload(
        version=1,
        cert_id=str(uuid.uuid4()),
        issued_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        subject="Sync Tester",
        category="prose",
        language=None,
        passage_id="prose-001",
        passage_sha256="00" * 32,
        metrics=Metrics(
            net_wpm=80.0,
            raw_wpm=82.0,
            accuracy=0.98,
            consistency=0.9,
            duration_ms=20000,
            chars_total=150,
            chars_correct=147,
            chars_incorrect=3,
        ),
        keystroke_log_sha256="11" * 32,
        integrity="clean",
        assurance="heuristic-checked",
        nonce="22" * 16,
        issuer_id=issuer_id,
        alg="Ed25519",
    )
    env = sign_certificate(payload, priv)

    with get_registry_session() as db:
        db.add(IssuerModel(id=issuer_id, public_key=public_key_to_b64url(pub)))
        db.flush()
        _, _, _, head = svc1.append_certificate(payload.cert_id, env.model_dump(), db)

    svc2 = LogService(keystore=ks)
    with get_registry_session() as db:
        svc2.sync_from_db(db)
    assert svc2.tree.size == 1
    assert svc2.tree.root_hex() == head.root_hash


def test_expired_registration_challenges_are_purged():
    from rctyping_registry.db.models import RegistrationChallengeModel
    from rctyping_registry.db.session import get_registry_session

    with _test_client() as client:
        with get_registry_session() as db:
            old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10)
            db.add(RegistrationChallengeModel(challenge="expired-token", created_at=old_time, expires_at=old_time))
            db.commit()

        resp = client.post("/v1/issuers/challenge")
        assert resp.status_code == 200
        with get_registry_session() as db:
            tokens = [c.challenge for c in db.query(RegistrationChallengeModel).all()]
            assert "expired-token" not in tokens
            assert resp.json()["challenge"] in tokens
