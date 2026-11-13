import uuid
import pytest
from fastapi.testclient import TestClient

from rctyping_app.core.anticheat import evaluate_keystroke_integrity
from rctyping_app.core.scoring import compute_metrics, replay_keystrokes
from rctyping_app.main import app
from rctyping_common.certificate import verify_certificate_envelope
from rctyping_common.models import CertificateEnvelope, KeystrokeEvent


def test_keystroke_replay_and_metrics():
    target = "def hello():\n    return 42"
    # Generate realistic keystrokes matching target
    events = []
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
    events = []
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


def test_anticheat_heuristics():
    # 1. Untrusted events
    untrusted = [
        KeystrokeEvent(t_ms=0, key="a", type="keydown", is_trusted=False),
        KeystrokeEvent(t_ms=100, key="b", type="keydown", is_trusted=True),
    ]
    status, flags = evaluate_keystroke_integrity(untrusted, server_duration_ms=200)
    assert status == "flagged"
    assert "untrusted_browser_event" in flags

    # 2. Inhuman speed (< 35ms per keystroke)
    turbo = [
        KeystrokeEvent(t_ms=i * 10, key="x", type="keydown", is_trusted=True)
        for i in range(15)
    ]
    status2, flags2 = evaluate_keystroke_integrity(turbo, server_duration_ms=150)
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
    with TestClient(app) as client:
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
        events = []
        t = 0
        import random
        for ch in target_text:
            key = "Enter" if ch == "\n" else ch
            events.append({"t_ms": t, "key": key, "type": "keydown", "is_trusted": True})
            # Vary interval with realistic human jitter
            t += random.randint(50, 150)
            events.append({"t_ms": t - 20, "key": key, "type": "keyup", "is_trusted": True})

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


def test_favicon_served():
    with TestClient(app) as client:
        resp = client.get("/favicon.ico")
        assert resp.status_code == 200
        assert "svg" in resp.headers.get("content-type", "")

        static_resp = client.get("/static/favicon.svg")
        assert static_resp.status_code == 200


def test_typing_thoughts_brain_encryption_folders_and_zip_export():
    import io
    import zipfile
    from rctyping_app.db.models import ThoughtModel
    from rctyping_app.db.session import get_app_session
    from rctyping_app.main import app_keystore

    with TestClient(app) as client:
        # Verify UI serves Typing Thoughts tab
        html_resp = client.get("/")
        assert html_resp.status_code == 200
        assert "Typing Thoughts" in html_resp.text
        assert "Export Brain (.zip)" in html_resp.text

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
        thought_text = "Build a fast local-first encrypted brain for typing thoughts."
        t1_resp = client.post(
            "/api/thoughts",
            json={
                "content": thought_text,
                "duration_ms": 6000,
                "filename": "brain-architecture",
            },
        )
        assert t1_resp.status_code == 200
        t1 = t1_resp.json()
        assert t1["filename"] == "brain-architecture.md"
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
            assert thought_text not in row.encrypted_markdown
            assert app_keystore is not None
            assert app_keystore.decrypt_text(row.encrypted_content) == thought_text

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

        # 5. Export Brain as .zip and verify .md files and folder structure
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

        # 6. Deleting a folder preserves thoughts by moving them up to parent
        del_sub = client.delete(f"/api/thoughts/folders/{ideas_folder['id']}")
        assert del_sub.status_code == 200
        brain_resp = client.get("/api/thoughts/brain")
        assert brain_resp.status_code == 200
        brain_data = brain_resp.json()
        t1_after = next(t for t in brain_data["thoughts"] if t["id"] == t1["id"])
        assert t1_after["folder_id"] == projects_folder["id"]

        # Cleanup created test thoughts & folder
        assert client.delete(f"/api/thoughts/{t1['id']}").status_code == 200
        assert client.delete(f"/api/thoughts/{t2['id']}").status_code == 200
        assert client.delete(f"/api/thoughts/folders/{projects_folder['id']}").status_code == 200
