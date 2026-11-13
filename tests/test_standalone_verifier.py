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
