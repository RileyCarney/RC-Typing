"""FastAPI main application entrypoint for rc-typing Registry."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse

from rctyping_registry.api.routes import router as registry_api_router
from rctyping_registry.config import registry_settings
from rctyping_registry.core.registry_keystore import RegistryKeyStore
from rctyping_registry.db.session import get_registry_session, init_registry_db
from rctyping_registry.services.log_service import LogService

registry_keystore: RegistryKeyStore | None = None
registry_log_service: LogService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global registry_keystore, registry_log_service
    # 1. Init DB
    init_registry_db()

    # 2. Init Keystore
    keys_dir = registry_settings.data_dir / "keys"
    registry_keystore = RegistryKeyStore(keys_dir=keys_dir, passphrase=registry_settings.key_passphrase)

    # 3. Init Log Service and sync from database
    registry_log_service = LogService(keystore=registry_keystore)
    with get_registry_session() as db:
        registry_log_service.sync_from_db(db)

    yield


def create_registry_app() -> FastAPI:
    app = FastAPI(
        title="rc-typing-registry",
        description="Public transparency log and verification registry for rc-typing certificates",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(registry_api_router, prefix="/v1")

    @app.get("/.well-known/rctyping-registry.json")
    def get_registry_info():
        if registry_keystore is None or registry_log_service is None:
            return Response("Registry initializing", status_code=503)
        return {
            "name": "rc-typing public registry",
            "version": "0.1.0",
            "registry_key_id": registry_keystore.key_id,
            "registry_public_key_b64": registry_keystore.get_public_key_b64(),
            "tree_size": registry_log_service.tree.size,
            "tree_root_hex": registry_log_service.tree.root_hex(),
        }

    @app.get("/", response_class=HTMLResponse)
    @app.get("/verify", response_class=HTMLResponse)
    def registry_ui():
        return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>rc-typing Public Registry</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; max-width: 800px; margin: 0 auto; line-height: 1.6; }
    h1 { color: #38bdf8; }
    .card { background: #1e293b; padding: 1.5rem; border-radius: 8px; border: 1px solid #334155; margin-top: 1.5rem; }
    input { background: #0f172a; border: 1px solid #334155; color: #fff; padding: 0.6rem; border-radius: 4px; width: 70%; font-family: monospace; }
    button { background: #38bdf8; color: #0f172a; border: none; padding: 0.6rem 1.2rem; font-weight: bold; border-radius: 4px; cursor: pointer; }
    pre { background: #0f172a; padding: 1rem; border-radius: 4px; overflow-x: auto; color: #4ade80; }
  </style>
</head>
<body>
  <h1>rc-typing Public Transparency Registry</h1>
  <p>Cryptographic transparency log recording verified typing speed benchmark certificates.</p>

  <div class="card">
    <h3>Lookup Certificate Record by ID</h3>
    <div style="margin: 1rem 0;">
      <input type="text" id="cert-id-input" placeholder="Enter Certificate UUID...">
      <button onclick="lookupCert()">Lookup Record</button>
    </div>
    <div id="result-box" style="display:none;">
      <h4>Registry Record & Inclusion Proof</h4>
      <pre id="json-display"></pre>
    </div>
  </div>

  <script>
    async function lookupCert() {
      const id = document.getElementById('cert-id-input').value.trim();
      if (!id) return;
      const res = await fetch(`/v1/certificates/${id}`);
      const data = await res.json();
      document.getElementById('result-box').style.display = 'block';
      document.getElementById('json-display').innerText = JSON.stringify(data, null, 2);
    }
  </script>
</body>
</html>"""

    return app


app = create_registry_app()
