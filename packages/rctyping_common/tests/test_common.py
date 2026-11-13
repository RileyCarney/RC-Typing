import uuid
from datetime import datetime, timezone
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from rctyping_common.canonical import canonical_json_dumps, canonical_json_hash
from rctyping_common.certificate import (
    calculate_key_id,
    generate_keypair,
    private_key_from_pem,
    private_key_to_pem,
    public_key_from_b64url,
    public_key_from_pem,
    public_key_to_b64url,
    public_key_to_pem,
    sign_certificate,
    verify_certificate_envelope,
)
from rctyping_common.corpus import CorpusRepository, Passage
from rctyping_common.merkle import (
    MerkleTree,
    leaf_hash,
    verify_consistency_proof,
    verify_inclusion_proof,
)
from rctyping_common.models import (
    CertificateEnvelope,
    CertificatePayload,
    Metrics,
    sanitize_display_name,
)


def test_sanitize_display_name():
    # Empty / whitespace
    assert sanitize_display_name("") == "Anonymous Typist"
    assert sanitize_display_name("   ") == "Anonymous Typist"

    # Normal name
    assert sanitize_display_name("Alice Developer") == "Alice Developer"

    # Bidi override and control characters
    evil = "Alice\u202E\u200B\x00Hacker"
    sanitized = sanitize_display_name(evil)
    assert "\u202E" not in sanitized
    assert "\u200B" not in sanitized
    assert "\x00" not in sanitized
    assert "AliceHacker" in sanitized

    # Length capping at 64 chars
    long_name = "A" * 100
    assert len(sanitize_display_name(long_name)) == 64


def test_canonical_json_determinism():
    dict1 = {"b": 2, "a": 1, "nested": {"y": [3, 2, 1], "x": True}}
    dict2 = {"nested": {"x": True, "y": [3, 2, 1]}, "a": 1, "b": 2}

    bytes1 = canonical_json_dumps(dict1)
    bytes2 = canonical_json_dumps(dict2)

    assert bytes1 == bytes2
    assert bytes1 == b'{"a":1,"b":2,"nested":{"x":true,"y":[3,2,1]}}'
    assert canonical_json_hash(dict1) == canonical_json_hash(dict2)


def test_ed25519_key_serialization():
    priv, pub = generate_keypair()
    key_id = calculate_key_id(pub)
    assert len(key_id) == 64

    # Public PEM
    pub_pem = public_key_to_pem(pub)
    assert "-----BEGIN PUBLIC KEY-----" in pub_pem
    pub_recovered = public_key_from_pem(pub_pem)
    assert calculate_key_id(pub_recovered) == key_id

    # Public Base64URL
    pub_b64 = public_key_to_b64url(pub)
    assert len(pub_b64) == 43  # 32 bytes unpadded base64url is 43 chars
    pub_recovered_b64 = public_key_from_b64url(pub_b64)
    assert calculate_key_id(pub_recovered_b64) == key_id

    # Private PEM with passphrase
    priv_pem = private_key_to_pem(priv, passphrase="secret-passphrase")
    assert "-----BEGIN ENCRYPTED PRIVATE KEY-----" in priv_pem
    priv_recovered = private_key_from_pem(priv_pem, passphrase="secret-passphrase")
    assert calculate_key_id(priv_recovered.public_key()) == key_id

    with pytest.raises(Exception):
        private_key_from_pem(priv_pem, passphrase="wrong-passphrase")


def test_sign_and_verify_certificate():
    priv, pub = generate_keypair()
    key_id = calculate_key_id(pub)

    payload = CertificatePayload(
        version=1,
        cert_id=str(uuid.uuid4()),
        issued_at=datetime.now(timezone.utc).isoformat(),
        subject="Dev User",
        category="code",
        language="python",
        passage_id="py-001",
        passage_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        metrics=Metrics(
            net_wpm=85.5,
            raw_wpm=88.0,
            accuracy=0.985,
            consistency=0.92,
            duration_ms=45000,
            chars_total=320,
            chars_correct=315,
            chars_incorrect=5,
        ),
        keystroke_log_sha256="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        integrity="clean",
        assurance="heuristic-checked",
        nonce="a" * 32,
        issuer_id=key_id,
        alg="Ed25519",
    )

    envelope = sign_certificate(payload, priv)
    assert verify_certificate_envelope(envelope) is True
    assert verify_certificate_envelope(envelope, expected_public_key=pub) is True

    # Tamper test 1: Modify net_wpm
    tampered_payload_data = envelope.payload.model_dump()
    tampered_payload_data["metrics"]["net_wpm"] = 85.6
    tampered_envelope = CertificateEnvelope(
        payload=CertificatePayload(**tampered_payload_data),
        signature=envelope.signature,
        issuer_public_key=envelope.issuer_public_key,
    )
    assert verify_certificate_envelope(tampered_envelope) is False

    # Tamper test 2: Modify subject
    tampered_payload_data2 = envelope.payload.model_dump()
    tampered_payload_data2["subject"] = "Imposter"
    tampered_envelope2 = CertificateEnvelope(
        payload=CertificatePayload(**tampered_payload_data2),
        signature=envelope.signature,
        issuer_public_key=envelope.issuer_public_key,
    )
    assert verify_certificate_envelope(tampered_envelope2) is False

    # Tamper test 3: Signature from different key
    other_priv, other_pub = generate_keypair()
    assert verify_certificate_envelope(envelope, expected_public_key=other_pub) is False


def test_merkle_tree_and_proofs():
    tree = MerkleTree()
    leaves = [f"certificate-data-{i}".encode("utf-8") for i in range(10)]

    for l in leaves:
        tree.append(l)

    assert tree.size == 10
    root_hex = tree.root_hex()
    assert len(root_hex) == 64

    # Verify inclusion proofs for every leaf
    for i in range(10):
        proof = tree.get_inclusion_proof(i)
        is_valid = verify_inclusion_proof(
            leaf_data=leaves[i],
            leaf_index=i,
            tree_size=10,
            audit_path=proof,
            expected_root_hex=root_hex,
        )
        assert is_valid is True

    # Tampered leaf data
    assert (
        verify_inclusion_proof(
            leaf_data=b"fake-certificate-data",
            leaf_index=0,
            tree_size=10,
            audit_path=tree.get_inclusion_proof(0),
            expected_root_hex=root_hex,
        )
        is False
    )

    # Consistency proofs
    small_tree = MerkleTree(leaves[:4])
    small_root = small_tree.root_hex()
    consistency_proof = tree.get_consistency_proof(4)
    assert verify_consistency_proof(
        prior_size=4,
        current_size=10,
        prior_root_hex=small_root,
        current_root_hex=root_hex,
        consistency_path=consistency_proof,
    ) is True


def test_corpus_repository(tmp_path):
    passages = [
        Passage(
            id="p1",
            category="code",
            language="python",
            title="Py Test",
            text="print('hello')",
            license="MIT",
            source="test",
            author="test",
            sha256="d04b98f48e8f8bcc15c6ae5ac050801cd6dcfd428fb5f9e65c4e16e7807340fa",
        ),
        Passage(
            id="p2",
            category="prose",
            language=None,
            title="Prose Test",
            text="Once upon a time.",
            license="Public Domain",
            source="test",
            author="test",
            sha256="6f30a9cb481e18d61240ce4aa69a3746c820b0b8c8d83935ee57f6d3f2ec8de3",
        ),
    ]
    repo = CorpusRepository(passages)
    assert repo.get_by_id("p1") is not None
    assert repo.get_random_passage("code", "python").id == "p1"
    assert repo.get_random_passage("prose").id == "p2"
    cats = repo.list_categories()
    assert "code" in cats and "python" in cats["code"]
    assert "prose" in cats


def test_production_corpus_integrity():
    corpus_dir = Path(__file__).resolve().parents[3] / "corpus" / "data"
    repo = CorpusRepository.load_from_dir(corpus_dir)

    assert len(repo._passages) == 1125
    assert len({p.id for p in repo._passages}) == 1125
    assert len({p.text for p in repo._passages}) == 1125
    assert len({(p.category, p.language, p.title) for p in repo._passages}) == 1125

    for p in repo._passages:
        assert repo.verify_passage_text(p.id, p.text) is True
        assert all(c == "\n" or (32 <= ord(c) <= 126) for c in p.text), (
            f"Non-ASCII or disallowed control char in passage {p.id}"
        )
        assert all(line == line.rstrip() for line in p.text.split("\n")), (
            f"Trailing whitespace in passage {p.id}"
        )


