from collections.abc import Generator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast
import uuid
import httpx
import pytest
from fastapi.testclient import TestClient

from rctyping_app.core.anticheat import evaluate_keystroke_integrity
from rctyping_app.core.scoring import compute_metrics, replay_keystrokes
from rctyping_app.main import app
from rctyping_common.certificate import verify_certificate_envelope
from rctyping_common.models import CertificateEnvelope, KeystrokeEvent


@contextmanager
def _test_client() -> Generator[httpx.Client, None, None]:
    with TestClient(app) as client:
        yield cast(httpx.Client, client)


@pytest.fixture(autouse=True)
def isolated_app_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import rctyping_app.db.session as app_db_session
    from rctyping_app.config import settings

    app_db_session.reset_db()
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    yield
    app_db_session.reset_db()


def test_keystroke_replay_and_metrics():
    target = "def hello():\n    return 42"
    # Generate realistic keystrokes matching target
    events: list[KeystrokeEvent] = []
    t = 0
    for char in target:
        if char == "\n":
            events.append(KeystrokeEvent(t_ms=t, key="Enter", type="keydown"))
        else:
            events.append(KeystrokeEvent(t_ms=t, key=char, type="keydown"))
        t += 100

    metrics, text = compute_metrics(target, events, server_duration_ms=t)
    assert text == target
    assert metrics.chars_correct == len(target)
    assert metrics.chars_incorrect == 0
    assert metrics.accuracy == 1.0
    assert metrics.net_wpm > 0


def test_compute_metrics_with_tab():
    target = "def foo():\n    return 42"
    events: list[KeystrokeEvent] = []
    t = 0
    for ch in "def foo():\n":
        key = "Enter" if ch == "\n" else ch
        events.append(KeystrokeEvent(t_ms=t, key=key, type="keydown"))
        t += 100
    events.append(KeystrokeEvent(t_ms=t, key="Tab", type="keydown"))
    t += 100
    for ch in "return 42":
        events.append(KeystrokeEvent(t_ms=t, key=ch, type="keydown"))
        t += 100

    metrics, text = compute_metrics(target, events, server_duration_ms=t)
    assert text == target
    assert metrics.chars_correct == len(target)
    assert metrics.accuracy == 1.0
    assert metrics.accuracy <= 1.0
    assert metrics.raw_wpm >= metrics.net_wpm


def test_tab_followed_by_backspaces_replay_and_metrics():
    target = "def foo():\n    return 42"
    events: list[KeystrokeEvent] = []
    t = 0
    for ch in "def foo():\n":
        key = "Enter" if ch == "\n" else ch
        events.append(KeystrokeEvent(t_ms=t, key=key, type="keydown"))
        t += 100
    events.append(KeystrokeEvent(t_ms=t, key="Tab", type="keydown"))
    t += 100
    for _ in range(4):
        events.append(KeystrokeEvent(t_ms=t, key="Backspace", type="keydown"))
        t += 100
    events.append(KeystrokeEvent(t_ms=t, key="Tab", type="keydown"))
    t += 100
    for ch in "return 42":
        events.append(KeystrokeEvent(t_ms=t, key=ch, type="keydown"))
        t += 100

    metrics, text = compute_metrics(target, events, server_duration_ms=t)
    assert text == target
    assert metrics.chars_correct == len(target)
    assert metrics.chars_incorrect == 0
    assert metrics.accuracy == 1.0

    # Partial backspace after Tab removes one space per Backspace, not all 4 at once
    partial_events = [
        KeystrokeEvent(t_ms=0, key="a", type="keydown"),
        KeystrokeEvent(t_ms=100, key="Enter", type="keydown"),
        KeystrokeEvent(t_ms=200, key="Tab", type="keydown"),
        KeystrokeEvent(t_ms=300, key="Backspace", type="keydown"),
        KeystrokeEvent(t_ms=400, key="Backspace", type="keydown"),
        KeystrokeEvent(t_ms=500, key="b", type="keydown"),
    ]
    assert replay_keystrokes(partial_events) == "a\n  b"


def test_anticheat_heuristics():
    # 1. Untrusted events
    untrusted = [
        KeystrokeEvent(t_ms=0, key="a", type="keydown", is_trusted=False),
        KeystrokeEvent(t_ms=100, key="b", type="keydown", is_trusted=True),
    ]
    status, flags = evaluate_keystroke_integrity(untrusted, server_duration_ms=200)
    assert status == "flagged"
    assert "untrusted_browser_event" in flags

    # 2. High speed (>600 WPM) is clean by default (limitless top WPM),
    #    and only flagged when min_human_iki_ms is explicitly configured > 0.
    turbo = [
        KeystrokeEvent(t_ms=i * 10 + (i % 3), key="x", type="keydown", is_trusted=True)
        for i in range(15)
    ]
    status_default, flags_default = evaluate_keystroke_integrity(turbo, server_duration_ms=150)
    assert status_default == "clean"
    assert flags_default == []

    status2, flags2 = evaluate_keystroke_integrity(
        turbo, server_duration_ms=150, min_human_iki_ms=35.0
    )
    assert status2 == "flagged"
    assert any("inhuman_speed" in f for f in flags2)

    # 3. Uniform loop macro (exact 50ms interval every key)
    uniform = [
        KeystrokeEvent(t_ms=i * 50, key="x", type="keydown", is_trusted=True)
        for i in range(25)
    ]
    status3, flags3 = evaluate_keystroke_integrity(uniform, server_duration_ms=1250)
    assert status3 == "flagged"
    assert any("uniform_timing_loop" in f for f in flags3)


def test_api_session_lifecycle_and_certificate():
    with _test_client() as client:
        # 1. List categories
        resp = client.get("/api/categories")
        assert resp.status_code == 200
        cats = resp.json()
        assert "code" in cats
        assert "python" in cats["code"]

        # 2. Start session
        resp = client.post("/api/sessions", json={"category": "code", "language": "python"})
        assert resp.status_code == 200
        sess_data = resp.json()
        session_id = sess_data["session_id"]
        passage = sess_data["passage"]
        target_text = passage["text"]

        # 3. Simulate human-like keystrokes
        events: list[dict[str, Any]] = []
        t = 0
        import random
        for ch in target_text:
            key = "Enter" if ch == "\n" else ch
            events.append({"t_ms": t, "key": key, "type": "keydown", "is_trusted": True})
            # Vary interval with realistic human jitter
            t += random.randint(50, 150)
            events.append({"t_ms": t - 20, "key": key, "type": "keyup", "is_trusted": True})

        import datetime
        from rctyping_app.db.models import SessionModel
        from rctyping_app.db.session import get_app_session

        with get_app_session() as db:
            db_sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            assert db_sess is not None
            db_sess.started_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(milliseconds=t)
            db.commit()

        # 4. Finish session
        finish_resp = client.post(
            f"/api/sessions/{session_id}/finish",
            json={"events": events, "subject_name": "Test Runner"},
        )
        assert finish_resp.status_code == 200
        res_data = finish_resp.json()

        envelope = CertificateEnvelope(**res_data["certificate"])
        assert envelope.payload.subject == "Test Runner"
        assert envelope.payload.category == "code"
        assert envelope.payload.language == "python"
        assert envelope.payload.metrics.net_wpm > 0

        # 5. Offline mathematical verification of certificate
        is_valid = verify_certificate_envelope(envelope)
        assert is_valid is True

        # 6. Verify via API endpoint
        verify_resp = client.post("/api/verify", json=envelope.model_dump())
        assert verify_resp.status_code == 200
        v_result = verify_resp.json()
        assert v_result["valid"] is True
        assert v_result["status"] == "VALID_OFFLINE"

        # 7. Check stats
        stats_resp = client.get("/api/stats")
        assert stats_resp.status_code == 200
        stats = stats_resp.json()
        assert stats["total_certificates"] >= 1


def test_session_start_resets_idle_clock_for_clean_integrity():
    import datetime
    from rctyping_app.db.models import SessionModel
    from rctyping_app.db.session import get_app_session

    with _test_client() as client:
        resp = client.post("/api/sessions", json={"category": "code", "language": "python"})
        assert resp.status_code == 200
        sess_data = resp.json()
        session_id = sess_data["session_id"]
        target_text = sess_data["passage"]["text"]

        # Simulate 2 minutes of idle time before the user types their first keystroke
        with get_app_session() as db:
            db_sess = db.query(SessionModel).filter(SessionModel.id == session_id).first()
            assert db_sess is not None
            db_sess.started_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=120)
            db.commit()

        start_resp = client.post(f"/api/sessions/{session_id}/start")
        assert start_resp.status_code == 200
        assert start_resp.json() == {"status": "started"}

        # Type a prefix with realistic human jitter (~2s total, well within skew allowance)
        sample = target_text[:30]
        events: list[dict[str, Any]] = []
        t = 0
        for idx, ch in enumerate(sample):
            key = "Enter" if ch == "\n" else ch
            events.append({"t_ms": t, "key": key, "type": "keydown", "is_trusted": True})
            dwell = 15 + (idx % 4) * 5
            events.append({"t_ms": t + dwell, "key": key, "type": "keyup", "is_trusted": True})
            t += 45 if idx % 2 == 0 else 95

        expected_duration_ms = events[-2]["t_ms"] - events[0]["t_ms"]
        finish_resp = client.post(
            f"/api/sessions/{session_id}/finish",
            json={"events": events, "subject_name": "Idle Test Typist"},
        )
        assert finish_resp.status_code == 200
        cert_payload = finish_resp.json()["certificate"]["payload"]
        assert cert_payload["integrity"] == "clean"
        assert cert_payload["metrics"]["duration_ms"] == expected_duration_ms
        assert cert_payload["metrics"]["accuracy"] == 1.0


def test_favicon_served():
    with _test_client() as client:
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200
        assert "svg" in resp.headers.get("content-type", "")

        static_resp = client.get("/static/favicon.svg")
        assert static_resp.status_code == 200


def test_typing_thoughts_storage_encryption_folders_and_zip_export():
    import io
    import zipfile
    import rctyping_app.main as app_main
    from rctyping_app.db.models import ThoughtModel
    from rctyping_app.db.session import get_app_session

    with _test_client() as client:
        # Verify UI serves Typing Thoughts tab
        html_resp = client.get("/")
        assert html_resp.status_code == 200
        assert "Typing Thoughts" in html_resp.text
        assert "Export Storage (.zip)" in html_resp.text

        # 1. Create root folder and nested folder
        f_root_resp = client.post("/api/thoughts/folders", json={"name": "Projects"})
        assert f_root_resp.status_code == 200
        projects_folder = f_root_resp.json()
        assert projects_folder["path"] == "Projects"

        f_sub_resp = client.post(
            "/api/thoughts/folders",
            json={"name": "Ideas", "parent_id": projects_folder["id"]},
        )
        assert f_sub_resp.status_code == 200
        ideas_folder = f_sub_resp.json()
        assert ideas_folder["path"] == "Projects/Ideas"

        # 2. Push thoughts (one in root, one in Projects)
        thought_text = "Build a fast local-first encrypted storage for typing thoughts."
        t1_resp = client.post(
            "/api/thoughts",
            json={
                "content": thought_text,
                "duration_ms": 6000,
                "filename": "storage-architecture",
            },
        )
        assert t1_resp.status_code == 200
        t1 = t1_resp.json()
        assert t1["filename"] == "storage-architecture.md"
        assert t1["wpm"] > 0
        assert t1["duration_ms"] == 6000
        assert t1["total_time"] == "6.0s"
        assert t1["encryption_alg"] == "AES-256-GCM"
        assert f"wpm: {t1['wpm']}" in t1["markdown"]
        assert "total_time: 6.0s" in t1["markdown"]

        t2_resp = client.post(
            "/api/thoughts",
            json={
                "content": "Second thought inside projects folder",
                "duration_ms": 3500,
                "wpm": 82.4,
                "folder_id": projects_folder["id"],
            },
        )
        assert t2_resp.status_code == 200
        t2 = t2_resp.json()
        assert t2["filename"].endswith(".md")
        assert t2["folder_path"] == "Projects"
        assert t2["wpm"] == 82.4

        # 3. Verify encrypted at rest in SQLite
        with get_app_session() as db:
            row = db.query(ThoughtModel).filter(ThoughtModel.id == t1["id"]).first()
            assert row is not None
            assert thought_text not in row.encrypted_content
            assert app_main.app_keystore is not None
            assert app_main.app_keystore.decrypt_text(row.encrypted_content) == thought_text

        # 4. Drag/move thought t1 into Projects/Ideas
        move_resp = client.patch(
            f"/api/thoughts/{t1['id']}",
            json={"folder_id": ideas_folder["id"]},
        )
        assert move_resp.status_code == 200
        moved = move_resp.json()
        assert moved["folder_id"] == ideas_folder["id"]
        assert moved["folder_path"] == "Projects/Ideas"
        assert 'folder: "Projects/Ideas"' in moved["markdown"]

        # 5. Export Storage as .zip and verify .md files and folder structure
        zip_resp = client.get("/api/thoughts/export-zip")
        assert zip_resp.status_code == 200
        assert "application/zip" in zip_resp.headers.get("content-type", "")

        with zipfile.ZipFile(io.BytesIO(zip_resp.content), "r") as zf:
            names = zf.namelist()
            assert f"Projects/Ideas/{t1['filename']}" in names
            assert f"Projects/{t2['filename']}" in names
            exported_md = zf.read(f"Projects/Ideas/{t1['filename']}").decode("utf-8")
            assert thought_text in exported_md
            assert f"wpm: {t1['wpm']}" in exported_md
            assert "total_time: 6.0s" in exported_md

        # 6. Deleting a folder preserves thoughts by moving them up to parent and updates markdown frontmatter
        del_sub = client.delete(f"/api/thoughts/folders/{ideas_folder['id']}")
        assert del_sub.status_code == 200
        storage_resp = client.get("/api/thoughts/storage")
        assert storage_resp.status_code == 200
        storage_data = storage_resp.json()
        t1_after = next(t for t in storage_data["thoughts"] if t["id"] == t1["id"])
        assert t1_after["folder_id"] == projects_folder["id"]
        assert 'folder: "Projects"' in t1_after["markdown"]

        zip_after_resp = client.get("/api/thoughts/export-zip")
        assert zip_after_resp.status_code == 200
        with zipfile.ZipFile(io.BytesIO(zip_after_resp.content), "r") as zf_after:
            exported_after = zf_after.read(f"Projects/{t1['filename']}").decode("utf-8")
            assert 'folder: "Projects"' in exported_after

        # Cleanup created test thoughts & folder
        assert client.delete(f"/api/thoughts/{t1['id']}").status_code == 200
        assert client.delete(f"/api/thoughts/{t2['id']}").status_code == 200
        assert client.delete(f"/api/thoughts/folders/{projects_folder['id']}").status_code == 200


def test_clock_skew_cannot_shrink_duration_or_inflate_wpm():
    target = "The quick brown fox jumps over the lazy dog."
    events = [
        KeystrokeEvent(t_ms=i * 120, key=ch, type="keydown", is_trusted=True)
        for i, ch in enumerate(target)
    ]
    metrics, text = compute_metrics(target, events, server_duration_ms=5)
    assert text == target
    client_span = events[-1].t_ms - events[0].t_ms
    assert metrics.duration_ms == client_span
    assert metrics.net_wpm < 150.0


def test_short_keystroke_submission_is_flagged():
    short_fast = [
        KeystrokeEvent(t_ms=i * 10, key=ch, type="keydown", is_trusted=True)
        for i, ch in enumerate("hello")
    ]
    status, flags = evaluate_keystroke_integrity(short_fast, server_duration_ms=40)
    assert status == "flagged"
    assert "insufficient_events" in flags

    status_capped, flags_capped = evaluate_keystroke_integrity(
        short_fast, server_duration_ms=40, min_human_iki_ms=35.0
    )
    assert status_capped == "flagged"
    assert "insufficient_events" in flags_capped
    assert any("inhuman_speed" in f for f in flags_capped)

    one_key = [KeystrokeEvent(t_ms=0, key="a", type="keydown", is_trusted=True)]
    metrics, _ = compute_metrics("abc", one_key, server_duration_ms=10)
    assert metrics.consistency == 0.0


def test_stats_exclude_flagged_and_publish_retry_resets_backoff():
    import datetime
    from rctyping_app.db.models import PublishJobModel, SessionModel
    from rctyping_app.db.session import get_app_session

    with _test_client() as client:
        # 1. Finish a flagged session (<10 untrusted events)
        sess1 = client.post("/api/sessions", json={"category": "prose"}).json()
        flagged_events = [
            {"t_ms": i * 100, "key": ch, "type": "keydown", "is_trusted": False}
            for i, ch in enumerate(sess1["passage"]["text"][:5])
        ]
        f1 = client.post(
            f"/api/sessions/{sess1['session_id']}/finish",
            json={"events": flagged_events, "subject_name": "Cheater"},
        )
        assert f1.status_code == 200
        assert f1.json()["certificate"]["payload"]["integrity"] == "flagged"

        stats_before = client.get("/api/stats").json()
        assert stats_before["total_certificates"] == 0
        assert stats_before["by_category"] == {}

        # 2. Finish a clean session
        sess2 = client.post("/api/sessions", json={"category": "prose"}).json()
        clean_text = sess2["passage"]["text"]
        clean_events: list[dict[str, Any]] = []
        t = 0
        for idx, ch in enumerate(clean_text):
            key = "Enter" if ch == "\n" else ch
            clean_events.append({"t_ms": t, "key": key, "type": "keydown", "is_trusted": True})
            clean_events.append({"t_ms": t + 20 + (idx % 3) * 5, "key": key, "type": "keyup", "is_trusted": True})
            t += 65 if idx % 2 == 0 else 105
        with get_app_session() as db:
            db_sess = db.query(SessionModel).filter(SessionModel.id == sess2["session_id"]).first()
            assert db_sess is not None
            db_sess.started_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(milliseconds=t)
            db.commit()
        f2 = client.post(
            f"/api/sessions/{sess2['session_id']}/finish",
            json={"events": clean_events, "subject_name": "Honest"},
        )
        assert f2.status_code == 200
        cert_id = f2.json()["certificate"]["payload"]["cert_id"]
        assert f2.json()["certificate"]["payload"]["integrity"] == "clean"

        stats_after = client.get("/api/stats").json()
        assert stats_after["total_certificates"] == 1
        assert "best_raw_wpm" not in stats_after["by_category"]["prose"]

        # 3. Publish retry: 404 on missing cert, resets backoff & status on existing cert
        assert client.post(f"/api/certificates/{uuid.uuid4()}/publish").status_code == 404

        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)
        with get_app_session() as db:
            job = db.query(PublishJobModel).filter(PublishJobModel.cert_id == cert_id).first()
            assert job is not None
            job.state = "retrying"
            job.attempts = 4
            job.next_attempt_at = future
            db.commit()

        before_retry = datetime.datetime.now(datetime.timezone.utc)
        retry_resp = client.post(f"/api/certificates/{cert_id}/publish")
        assert retry_resp.status_code == 200

        with get_app_session() as db:
            job = db.query(PublishJobModel).filter(PublishJobModel.cert_id == cert_id).first()
            assert job is not None
            assert job.state == "pending"
            assert job.attempts == 0
            next_at = job.next_attempt_at.replace(tzinfo=datetime.timezone.utc)
            assert next_at <= datetime.datetime.now(datetime.timezone.utc)
            assert next_at >= before_retry - datetime.timedelta(seconds=2)


def test_certificate_service_uses_configured_anticheat_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rctyping_app.config import settings

    with _test_client() as client:
        monkeypatch.setattr(settings, "min_human_iki_ms", 200.0)
        sess = client.post("/api/sessions", json={"category": "prose"}).json()
        sample = sess["passage"]["text"][:20]
        events: list[dict[str, Any]] = []
        t = 0
        for idx, ch in enumerate(sample):
            events.append({"t_ms": t, "key": ch, "type": "keydown", "is_trusted": True})
            events.append({"t_ms": t + 15 + (idx % 3) * 5, "key": ch, "type": "keyup", "is_trusted": True})
            t += 90 if idx % 2 == 0 else 120
        res = client.post(
            f"/api/sessions/{sess['session_id']}/finish",
            json={"events": events, "subject_name": "Settings Check"},
        )
        assert res.status_code == 200
        # Mean IKI ~105ms is below overridden min_human_iki_ms=200.0 -> flagged
        assert res.json()["certificate"]["payload"]["integrity"] == "flagged"


@pytest.mark.asyncio
async def test_publish_worker_caches_registration_and_releases_db(tmp_path: Path) -> None:
    import json
    from rctyping_app.core.keystore import KeyStore
    from rctyping_app.db.models import CertificateModel, PublishJobModel, SessionModel
    from rctyping_app.db.session import DEFAULT_USER_ID, get_app_session, init_db
    from rctyping_app.services.publish_worker import PublishWorker

    init_db()
    ks = KeyStore(keys_dir=tmp_path / "data" / "keys")

    with get_app_session() as db:
        for _ in range(2):
            sid = str(uuid.uuid4())
            cid = str(uuid.uuid4())
            db.add(
                SessionModel(
                    id=sid,
                    user_id=DEFAULT_USER_ID,
                    category="prose",
                    passage_id="prose-001",
                    nonce="a" * 32,
                    status="completed",
                )
            )
            db.add(
                CertificateModel(
                    id=cid,
                    user_id=DEFAULT_USER_ID,
                    session_id=sid,
                    envelope={"payload": {"cert_id": cid}, "signature": "sig", "issuer_public_key": "pub"},
                    sha256="0" * 64,
                    category="prose",
                    net_wpm=80.0,
                    accuracy=1.0,
                )
            )
            db.add(PublishJobModel(cert_id=cid, state="pending"))
        db.commit()

    seen_requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path.startswith("/v1/issuers/"):
            return httpx.Response(200, json={"issuer_id": ks.key_id})
        if request.method == "POST" and request.url.path == "/v1/certificates":
            body = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"cert_id": body["payload"]["cert_id"]})
        return httpx.Response(404)

    worker = PublishWorker(
        keystore=ks,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        await worker.process_pending_jobs()
    finally:
        await worker.close()

    # Registration lookup ran only once for both pending certificates
    get_issuer_calls = [r for r in seen_requests if r[0] == "GET"]
    post_cert_calls = [r for r in seen_requests if r[0] == "POST" and r[1] == "/v1/certificates"]
    assert len(get_issuer_calls) == 1
    assert len(post_cert_calls) == 2

    with get_app_session() as db:
        assert db.query(PublishJobModel).filter(PublishJobModel.state == "completed").count() == 2


def test_cli_verify_rejects_revoked_registry_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse
    import datetime
    import json
    from rctyping_app.cli import cmd_verify
    from rctyping_common.canonical import canonical_json_dumps
    from rctyping_common.certificate import calculate_key_id, generate_keypair, sign_certificate
    from rctyping_common.merkle import MerkleTree
    from rctyping_common.models import CertificatePayload, Metrics

    priv, pub = generate_keypair()
    key_id = calculate_key_id(pub)
    payload = CertificatePayload(
        version=1,
        cert_id=str(uuid.uuid4()),
        issued_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        subject="CLI Tester",
        category="prose",
        language=None,
        passage_id="prose-001",
        passage_sha256="00" * 32,
        metrics=Metrics(
            net_wpm=80.0,
            raw_wpm=82.0,
            accuracy=0.98,
            consistency=0.95,
            duration_ms=20000,
            chars_total=150,
            chars_correct=147,
            chars_incorrect=3,
        ),
        keystroke_log_sha256="aa" * 32,
        integrity="clean",
        assurance="heuristic-checked",
        nonce="bb" * 16,
        issuer_id=key_id,
        alg="Ed25519",
    )
    envelope = sign_certificate(payload, priv)
    cert_path = tmp_path / "cert.json"
    cert_path.write_text(json.dumps(envelope.model_dump()), encoding="utf-8")

    tree = MerkleTree([canonical_json_dumps(envelope.model_dump())])

    class _MockResp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "envelope": envelope.model_dump(),
                "leaf_index": 0,
                "tree_size": 1,
                "trust_tier": "unverified",
                "is_revoked": True,
                "revocation_reason": "revoked in test",
                "inclusion_proof": {"leaf_index": 0, "tree_size": 1, "audit_path": tree.get_inclusion_proof(0)},
                "signed_tree_head": {
                    "tree_size": 1,
                    "root_hash": tree.root_hex(),
                    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "signature": "sig",
                },
            }

    def _mock_get(*args: Any, **kwargs: Any) -> _MockResp:
        return _MockResp()

    monkeypatch.setattr(httpx, "get", _mock_get)
    args = argparse.Namespace(certificate_file=str(cert_path), pubkey=None, registry="http://registry.local")
    with pytest.raises(SystemExit) as exc:
        cmd_verify(args)
    assert exc.value.code == 2


def test_notebook_ui_menu_settings_info_and_footer():
    import re
    from html.parser import HTMLParser

    class _UIParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_header = False
            self.in_nav = False
            self.in_footer = False
            self.in_button = False
            self.in_settings = False
            self.settings_depth = 0
            self.header_text_parts: list[str] = []
            self.nav_buttons: list[str] = []
            self.nav_button_circle_paths = 0
            self.current_btn_parts: list[str] = []
            self.footer_text_parts: list[str] = []
            self.footer_links: list[str] = []
            self.settings_text_parts: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attr_map = dict(attrs)
            if tag == "header":
                self.in_header = True
            elif tag == "nav" and self.in_header:
                self.in_nav = True
            elif tag == "button" and self.in_nav:
                self.in_button = True
                self.current_btn_parts = []
            elif tag == "path" and self.in_button and "pencil-circle-path" in (attr_map.get("class") or ""):
                self.nav_button_circle_paths += 1
            elif tag == "section" and attr_map.get("id") == "tab-settings":
                self.in_settings = True
                self.settings_depth = 1
            elif self.in_settings and tag == "section":
                self.settings_depth += 1
            elif tag == "footer":
                self.in_footer = True
            elif tag == "a" and self.in_footer:
                href = attr_map.get("href")
                if href is not None:
                    self.footer_links.append(href)

        def handle_endtag(self, tag: str) -> None:
            if tag == "button" and self.in_button:
                self.in_button = False
                self.nav_buttons.append(" ".join("".join(self.current_btn_parts).split()))
            elif tag == "nav" and self.in_nav:
                self.in_nav = False
            elif tag == "header" and self.in_header:
                self.in_header = False
            elif tag == "section" and self.in_settings:
                self.settings_depth -= 1
                if self.settings_depth == 0:
                    self.in_settings = False
            elif tag == "footer" and self.in_footer:
                self.in_footer = False

        def handle_data(self, data: str) -> None:
            if self.in_header:
                self.header_text_parts.append(data)
            if self.in_button:
                self.current_btn_parts.append(data)
            if self.in_settings:
                self.settings_text_parts.append(data)
            if self.in_footer:
                self.footer_text_parts.append(data)

    with _test_client() as client:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text

        parser = _UIParser()
        parser.feed(html)

        expected_menu = ["Typing Test", "Typing Thoughts", "Verify Certificate", "Settings"]
        assert parser.nav_buttons == expected_menu
        assert parser.nav_button_circle_paths == len(expected_menu)

        header_text = " ".join("".join(parser.header_text_parts).split())
        assert header_text == " ".join(expected_menu)
        assert "Stats & History" not in html
        assert "notebook-sheet" in html
        assert "notebook-holes" in html
        assert "notebook-margin-line" in html

        settings_text = " ".join("".join(parser.settings_text_parts).split())
        assert settings_text.index("Typing Performance History") < settings_text.index("Application Settings")
        for info_item in [
            "Application Information",
            "rc-typing",
            "Standalone Containerized Benchmark",
            "RFC 8785 Canonical JSON",
            "Ed25519",
            "RFC 6962 Transparency Log",
        ]:
            assert info_item in settings_text

        footer_text = " ".join("".join(parser.footer_text_parts).split())
        assert footer_text == "https://carn.si"
        assert parser.footer_links == ["https://carn.si"]

        css_resp = client.get("/static/styles.css")
        assert css_resp.status_code == 200
        assert ".pencil-circle-path" in css_resp.text
        assert re.search(r"\.nav-btn\.active\s+\.pencil-circle-path", css_resp.text)
        assert re.search(r"\.nav-btn:hover\s+\.pencil-circle-path", css_resp.text)
        assert "prefers-reduced-motion" in css_resp.text


def test_live_test_stat_values_use_pixel_font_exclusively():
    import re
    from html.parser import HTMLParser

    class _StatParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.pixel_elements: list[str] = []
            self.card_stack: list[dict[str, str]] = []
            self.cards: list[dict[str, str]] = []
            self.in_value = False
            self.in_label = False
            self.current_label: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attr_map = dict(attrs)
            class_attr = attr_map.get("class") or ""
            classes = class_attr.split()
            el_id = attr_map.get("id") or ""
            if "pixel-stat-value" in classes:
                self.pixel_elements.append(el_id)
            if "stat-card" in classes:
                self.card_stack.append({"value_id": "", "value_classes": "", "label": ""})
            elif self.card_stack and "stat-value" in classes:
                self.in_value = True
                self.card_stack[-1]["value_id"] = el_id
                self.card_stack[-1]["value_classes"] = class_attr
            elif self.card_stack and "stat-label" in classes:
                self.in_label = True
                self.current_label = []

        def handle_endtag(self, tag: str) -> None:
            if self.in_value and tag == "div":
                self.in_value = False
            elif self.in_label and tag == "div":
                self.in_label = False
                if self.card_stack:
                    self.card_stack[-1]["label"] = " ".join("".join(self.current_label).split())
            elif self.card_stack and tag == "div" and not self.in_value and not self.in_label:
                self.cards.append(self.card_stack.pop())

        def handle_data(self, data: str) -> None:
            if self.in_label:
                self.current_label.append(data)

    with _test_client() as client:
        html_resp = client.get("/")
        assert html_resp.status_code == 200
        html = html_resp.text
        assert "Press+Start+2P" in html

        parser = _StatParser()
        parser.feed(html)

        assert parser.pixel_elements == [
            "live-wpm",
            "live-accuracy",
            "live-time",
            "thought-live-wpm",
            "thought-live-time",
            "thought-live-chars",
        ]
        pixel_labels = [c["label"] for c in parser.cards if "pixel-stat-value" in c["value_classes"].split()]
        assert pixel_labels == [
            "Net WPM",
            "Accuracy",
            "Time",
            "Speed (WPM)",
            "Total Time",
            "Characters",
        ]

        non_pixel_ids = [c["value_id"] for c in parser.cards if "pixel-stat-value" not in c["value_classes"].split()]
        assert non_pixel_ids == [
            "thought-active-folder-label",
        ]

        css_resp = client.get("/static/styles.css")
        assert css_resp.status_code == 200
        assert "--font-pixel: 'Press Start 2P', monospace;" in css_resp.text
        assert re.search(r"\.stat-value\.pixel-stat-value\s*\{[^}]*font-family:\s*var\(--font-pixel\)", css_resp.text)


def test_migrate_legacy_thoughts_encrypted_markdown_column():
    import sqlite3
    from rctyping_app.config import settings

    db_path = settings.data_dir / "rctyping.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE thoughts (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL,
                folder_id VARCHAR(36),
                filename VARCHAR(160) NOT NULL,
                wpm FLOAT NOT NULL,
                duration_ms INTEGER NOT NULL,
                chars_typed INTEGER NOT NULL,
                encrypted_content TEXT NOT NULL,
                encrypted_markdown TEXT NOT NULL,
                encryption_alg VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )

    with _test_client() as client:
        resp = client.post(
            "/api/thoughts",
            json={"content": "test", "duration_ms": 472, "filename": "test.md"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "test.md"
        assert data["content"] == "test"

    with sqlite3.connect(db_path) as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(thoughts)").fetchall()}
        assert "encrypted_markdown" not in cols
        assert "encrypted_content" in cols


def test_scoring_supports_over_600_wpm_and_limitless_speed():
    # 1. >600 WPM sustained typing (100 chars in 1500ms = 800.0 WPM)
    target_100 = "a" * 100
    events_800 = [
        KeystrokeEvent(t_ms=int(i * (1500 / 99)), key="a", type="keydown", is_trusted=True)
        for i in range(100)
    ]
    metrics_800, text_800 = compute_metrics(target_100, events_800, server_duration_ms=1500)
    assert text_800 == target_100
    assert metrics_800.duration_ms == 1500
    assert metrics_800.net_wpm == 800.0
    assert metrics_800.net_wpm > 600.0

    # 2. Sub-100ms duration (5 chars in 50ms = 1200.0 WPM, previously capped at 600 WPM by 100ms floor)
    target_5 = "hello"
    events_1200 = [
        KeystrokeEvent(t_ms=i * 12 if i < 4 else 50, key=ch, type="keydown", is_trusted=True)
        for i, ch in enumerate(target_5)
    ]
    metrics_1200, _ = compute_metrics(target_5, events_1200, server_duration_ms=50)
    assert metrics_1200.duration_ms == 50
    assert metrics_1200.net_wpm == 1200.0

    # 3. Ultra-high / limitless WPM (100 chars in 10ms = 120,000.0 WPM)
    events_ultra = [
        KeystrokeEvent(t_ms=(i * 10) // 99, key="a", type="keydown", is_trusted=True)
        for i in range(100)
    ]
    metrics_ultra, _ = compute_metrics(target_100, events_ultra, server_duration_ms=10)
    assert metrics_ultra.duration_ms == 10
    assert metrics_ultra.net_wpm == 120000.0


def test_end_to_end_over_600_wpm_and_limitless_top_wpm_stats():
    import datetime
    from rctyping_app.db.models import SessionModel
    from rctyping_app.db.session import get_app_session

    with _test_client() as client:
        # Run 1: >600 WPM (~800+ WPM with natural jitter)
        sess1 = client.post("/api/sessions", json={"category": "prose"}).json()
        text1 = sess1["passage"]["text"]
        events1: list[dict[str, Any]] = []
        t1 = 0
        for idx, ch in enumerate(text1):
            key = "Enter" if ch == "\n" else ch
            events1.append({"t_ms": t1, "key": key, "type": "keydown", "is_trusted": True})
            events1.append({"t_ms": t1 + 3 + (idx % 3), "key": key, "type": "keyup", "is_trusted": True})
            t1 += 10 if idx % 2 == 0 else 18  # mean IKI ~14ms (~857 WPM)

        with get_app_session() as db:
            db_sess = db.query(SessionModel).filter(SessionModel.id == sess1["session_id"]).first()
            assert db_sess is not None
            db_sess.started_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(milliseconds=t1)
            db.commit()

        f1 = client.post(
            f"/api/sessions/{sess1['session_id']}/finish",
            json={"events": events1, "subject_name": "Speedster"},
        )
        assert f1.status_code == 200
        env1 = CertificateEnvelope(**f1.json()["certificate"])
        assert env1.payload.integrity == "clean"
        assert env1.payload.metrics.net_wpm > 600.0
        assert verify_certificate_envelope(env1) is True

        stats1 = client.get("/api/stats").json()
        assert stats1["total_certificates"] == 1
        assert stats1["by_category"]["prose"]["best_net_wpm"] > 600.0

        # Run 2: Limitless ultra-high WPM (~4000+ WPM with relative jitter)
        sess2 = client.post("/api/sessions", json={"category": "prose"}).json()
        text2 = sess2["passage"]["text"]
        events2: list[dict[str, Any]] = []
        t2 = 0
        for idx, ch in enumerate(text2):
            key = "Enter" if ch == "\n" else ch
            events2.append({"t_ms": t2, "key": key, "type": "keydown", "is_trusted": True})
            events2.append({"t_ms": t2 + 1 + (idx % 2), "key": key, "type": "keyup", "is_trusted": True})
            t2 += 2 if idx % 2 == 0 else 4  # mean IKI ~3ms (~4000 WPM)

        with get_app_session() as db:
            db_sess = db.query(SessionModel).filter(SessionModel.id == sess2["session_id"]).first()
            assert db_sess is not None
            db_sess.started_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(milliseconds=t2)
            db.commit()

        f2 = client.post(
            f"/api/sessions/{sess2['session_id']}/finish",
            json={"events": events2, "subject_name": "Limitless"},
        )
        assert f2.status_code == 200
        env2 = CertificateEnvelope(**f2.json()["certificate"])
        assert env2.payload.integrity == "clean"
        assert env2.payload.metrics.net_wpm > 3000.0
        assert verify_certificate_envelope(env2) is True

        stats2 = client.get("/api/stats").json()
        assert stats2["total_certificates"] == 2
        assert stats2["by_category"]["prose"]["best_net_wpm"] == env2.payload.metrics.net_wpm
        assert stats2["by_category"]["prose"]["best_net_wpm"] > 3000.0


def test_typing_thoughts_uncapped_wpm():
    with _test_client() as client:
        # 50 chars in 10ms = (50 / 5) / (10 / 60000) = 60,000.0 WPM (no 0.001 min / 60ms cap)
        resp = client.post(
            "/api/thoughts",
            json={"content": "a" * 50, "duration_ms": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["wpm"] == 60000.0


def test_file_explorer_labels():
    with _test_client() as client:
        html = client.get("/").text
        assert 'id="thought-active-folder-label">./</div>' in html
        assert "<h2>File Explorer</h2>" in html
        assert "Brain Explorer" not in html
        assert 'id="brain-current-path-heading">All Thoughts</span>' in html
        assert "Brain / (All Thoughts)" not in html

        js = client.get("/static/app.js").text
        assert "activeFolder ? `./${activeFolder.path}` : './'" in js
        assert 'class="tree-folder-name">/ (Root)</span>' in js
        assert "rootOpt.innerText = '/ (Root)';" in js
        assert "activeFolder ? `/${activeFolder.path}` : 'All Thoughts'" in js
        assert "Brain /" not in js



