"""Background worker for publishing certificates to the shared public registry."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import logging
from typing import Optional
import httpx
from sqlalchemy.orm import Session

from rctyping_app.core.keystore import KeyStore
from rctyping_app.db.models import CertificateModel, PublishJobModel, UserSettingsModel
from rctyping_app.db.session import get_app_session
from rctyping_common.canonical import canonical_json_dumps
from rctyping_common.certificate import b64url_encode

logger = logging.getLogger("rctyping.publish_worker")


class PublishWorker:

    def __init__(self, keystore: KeyStore, poll_interval_sec: float = 3.0) -> None:
        self.keystore = keystore
        self.poll_interval_sec = poll_interval_sec
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._registered_registries: set[str] = set()

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Publish worker started")

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("Publish worker stopped")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def _close_client(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _run_loop(self) -> None:
        try:
            while self._running:
                try:
                    await self.process_pending_jobs()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in publish worker loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval_sec)
        finally:
            await self._close_client()

    async def process_pending_jobs(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        pending_items: list[tuple[str, str, dict, str]] = []

        with get_app_session() as db:
            jobs = (
                db.query(PublishJobModel)
                .filter(
                    PublishJobModel.state.in_(["pending", "retrying"]),
                    PublishJobModel.next_attempt_at <= now,
                    PublishJobModel.attempts < 10,
                )
                .limit(5)
                .all()
            )
            dirty = False
            for job in jobs:
                cert = db.query(CertificateModel).filter(CertificateModel.id == job.cert_id).first()
                if not cert:
                    job.state = "failed"
                    job.last_error = "Associated certificate missing"
                    dirty = True
                    continue

                user_settings = db.query(UserSettingsModel).filter(UserSettingsModel.user_id == cert.user_id).first()
                registry_url = user_settings.registry_url if user_settings else None
                if not registry_url:
                    job.state = "failed"
                    job.last_error = "No registry_url configured"
                    cert.registry_status = "local_only"
                    dirty = True
                    continue

                pending_items.append((job.id, cert.id, cert.envelope, registry_url))

            if dirty:
                db.commit()

        for job_id, cert_id, envelope_dict, registry_url in pending_items:
            try:
                receipt = await self._publish_to_registry(registry_url, envelope_dict)
                with get_app_session() as db:
                    job = db.query(PublishJobModel).filter(PublishJobModel.id == job_id).first()
                    cert = db.query(CertificateModel).filter(CertificateModel.id == cert_id).first()
                    if job:
                        job.receipt = receipt
                        job.state = "completed"
                        job.last_error = None
                    if cert:
                        cert.registry_status = "published"
                    db.commit()
                logger.info(f"Successfully published certificate {cert_id} to registry")
            except Exception as ex:
                with get_app_session() as db:
                    job = db.query(PublishJobModel).filter(PublishJobModel.id == job_id).first()
                    cert = db.query(CertificateModel).filter(CertificateModel.id == cert_id).first()
                    if job:
                        job.attempts += 1
                        job.last_error = str(ex)
                        backoff_seconds = min(300, 2 ** job.attempts)
                        job.next_attempt_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=backoff_seconds)
                        job.state = "failed" if job.attempts >= 10 else "retrying"
                        attempts = job.attempts
                    else:
                        attempts = 0
                    if cert:
                        cert.registry_status = "failed"
                    db.commit()
                logger.warning(f"Failed to publish cert {cert_id} (attempt {attempts}): {ex}")

    async def _ensure_issuer_registered(self, client: httpx.AsyncClient, registry_url: str) -> None:
        """Register our issuer public key with the registry if not already registered."""
        normalized_url = registry_url.rstrip("/")
        if normalized_url in self._registered_registries:
            return

        issuer_id = self.keystore.key_id
        check_resp = await client.get(f"{normalized_url}/v1/issuers/{issuer_id}")
        if check_resp.status_code == 200:
            self._registered_registries.add(normalized_url)
            return

        # Request registration challenge
        chal_resp = await client.post(f"{normalized_url}/v1/issuers/challenge")
        chal_resp.raise_for_status()
        challenge_token = chal_resp.json()["challenge"]

        # Sign challenge to prove possession of private key
        sig_bytes = self.keystore.private_key.sign(challenge_token.encode("utf-8"))
        sig_b64 = b64url_encode(sig_bytes)

        reg_body = {
            "public_key": self.keystore.get_public_key_b64(),
            "challenge": challenge_token,
            "signature": sig_b64,
        }
        reg_resp = await client.post(f"{normalized_url}/v1/issuers", json=reg_body)
        reg_resp.raise_for_status()
        self._registered_registries.add(normalized_url)

    async def _publish_to_registry(self, registry_url: str, envelope_dict: dict) -> dict:
        normalized_url = registry_url.rstrip("/")
        client = await self._get_client()
        await self._ensure_issuer_registered(client, normalized_url)

        # Build signed headers
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        body_bytes = canonical_json_dumps(envelope_dict)
        body_hash = hashlib.sha256(body_bytes).hexdigest()
        sig_target = f"{self.keystore.key_id}:{ts}:{body_hash}".encode("utf-8")
        request_sig = b64url_encode(self.keystore.private_key.sign(sig_target))

        headers = {
            "X-Issuer-Id": self.keystore.key_id,
            "X-Timestamp": ts,
            "X-Signature": request_sig,
            "Content-Type": "application/json",
        }

        resp = await client.post(
            f"{normalized_url}/v1/certificates",
            content=body_bytes,
            headers=headers,
        )
        if resp.status_code == 401:
            self._registered_registries.discard(normalized_url)
        resp.raise_for_status()
        return resp.json()
