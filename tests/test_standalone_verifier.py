import json
import uuid
import datetime
from pathlib import Path
import pytest

from rctyping_common.certificate import calculate_key_id, generate_keypair, sign_certificate
from rctyping_common.models import CertificatePayload, Metrics
from verifier.verify_certificate import verify_certificate


def test_standalone_verifier_script(tmp_path):
    priv, pub = generate_keypair()
    key_id = calculate_key_id(pub)
    cert_id = str(uuid.uuid4())

    payload = CertificatePayload(
        version=1,
        cert_id=cert_id,
        issued_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        subject="Standalone Typist",
        category="code",
        language="python",
        passage_id="py-001",
        passage_sha256="00" * 32,
        metrics=Metrics(
            net_wpm=105.2,
            raw_wpm=108.0,
            accuracy=0.98,
            consistency=0.91,
            duration_ms=25000,
            chars_total=220,
            chars_correct=215,
            chars_incorrect=5,
        ),
        keystroke_log_sha256="aa" * 32,
        integrity="clean",
        assurance="heuristic-checked",
        nonce="bb" * 16,
        issuer_id=key_id,
        alg="Ed25519",
    )

    envelope = sign_certificate(payload, priv)

    cert_file = tmp_path / "valid_cert.json"
    with open(cert_file, "w", encoding="utf-8") as f:
        json.dump(envelope.model_dump(), f, indent=2)

    # Test valid certificate
    assert verify_certificate(str(cert_file)) is True

    # Tamper certificate
    tampered_dict = envelope.model_dump()
    tampered_dict["payload"]["metrics"]["net_wpm"] = 150.0
    tampered_file = tmp_path / "tampered_cert.json"
    with open(tampered_file, "w", encoding="utf-8") as f:
        json.dump(tampered_dict, f, indent=2)

    assert verify_certificate(str(tampered_file)) is False


def test_standalone_verifier_rejects_revoked_and_bad_proof(tmp_path, monkeypatch):
    import io
    import urllib.request
    from rctyping_common.canonical import canonical_json_dumps
    from rctyping_common.merkle import MerkleTree

    priv, pub = generate_keypair()
    key_id = calculate_key_id(pub)
    cert_id = str(uuid.uuid4())
    payload = CertificatePayload(
        version=1,
        cert_id=cert_id,
        issued_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        subject="Registry Verifier Test",
        category="prose",
        language=None,
        passage_id="prose-001",
        passage_sha256="00" * 32,
        metrics=Metrics(
            net_wpm=90.0,
            raw_wpm=92.0,
            accuracy=0.99,
            consistency=0.95,
            duration_ms=20000,
            chars_total=150,
            chars_correct=148,
            chars_incorrect=2,
        ),
        keystroke_log_sha256="aa" * 32,
        integrity="clean",
        assurance="heuristic-checked",
        nonce="bb" * 16,
        issuer_id=key_id,
        alg="Ed25519",
    )
    envelope = sign_certificate(payload, priv)
    cert_file = tmp_path / "cert.json"
    cert_file.write_text(json.dumps(envelope.model_dump()), encoding="utf-8")

    tree = MerkleTree([canonical_json_dumps(envelope.model_dump())])

    class _FakeResp:
        def __init__(self, body: dict):
            self._buf = json.dumps(body).encode("utf-8")

        def read(self):
            return self._buf

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    base_record = {
        "envelope": envelope.model_dump(),
        "leaf_index": 0,
        "tree_size": 1,
        "trust_tier": "unverified",
        "is_revoked": False,
        "revocation_reason": None,
        "inclusion_proof": {"leaf_index": 0, "tree_size": 1, "audit_path": tree.get_inclusion_proof(0)},
        "signed_tree_head": {
            "tree_size": 1,
            "root_hash": tree.root_hex(),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "signature": "sig",
        },
    }

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=5: _FakeResp(base_record))
    assert verify_certificate(str(cert_file), registry_url="http://registry.local") is True

    revoked_record = {**base_record, "is_revoked": True, "revocation_reason": "compromised"}
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=5: _FakeResp(revoked_record))
    assert verify_certificate(str(cert_file), registry_url="http://registry.local") is False

    bad_proof_record = {
        **base_record,
        "signed_tree_head": {**base_record["signed_tree_head"], "root_hash": "ff" * 32},
    }
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=5: _FakeResp(bad_proof_record))
    assert verify_certificate(str(cert_file), registry_url="http://registry.local") is False
