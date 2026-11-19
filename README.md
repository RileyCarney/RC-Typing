# rc-typing

A local-first typing speed benchmark across categories of thought with **Ed25519 cryptographically signed certificates** (RFC 8785 canonical JSON), an **RFC 6962 Merkle transparency log registry**, server-side keystroke replay & anti-cheat heuristics, and an **AES-256-GCM encrypted markdown thought capture workspace** (**Typing Thoughts / Brain Explorer**).

---

## Features

- **Categories of Thought**: 1,125 curated offline passages across 12 tracks: `code` (`python`, `powershell`, `cpp`, `csharp`, `javascript`, `typescript`, `sql`), `prose`, `reading`, `technical`, `formal`, and `conversational`.
- **Verifiable Cryptographic Certificates**: Server-replayed keystroke scoring (`Net WPM`, `Raw WPM`, `Accuracy`, `Consistency`) signed with Ed25519 over canonical JSON (`CertificateEnvelope`), verifiable offline or against the transparency log.
- **Anti-Cheat Heuristics**: Evaluates browser `isTrusted` event flags, client-server clock skew, minimum mean inter-keystroke interval (IKI), IKI standard deviation, and uniform key dwell macro detection (`clean` vs `flagged`).
- **Public Transparency Registry (`rctyping-registry`)**: RFC 6962 Merkle tree log and issuer directory with proof-of-possession issuer registration, background auto-publishing with exponential backoff (`PublishWorker`), signed tree heads (STH), inclusion/consistency proofs, certificate revocation, and issuer trust tiers (`unverified`, `verified`, `official`).
- **Typing Thoughts (Brain Explorer)**: Draft notes with live WPM, elapsed time, and character telemetry (`Enter` to push `.md`, `Shift+Enter` for newline), organize into nested folders via drag-and-drop, store encrypted locally with `AES-256-GCM` at rest in SQLite (plus a browser WebCrypto `AES-GCM` mirror in `localStorage`), download individual `.md` files with YAML frontmatter, or export the whole Brain as a `.zip`.
- **Offline & Standalone Verification**: Verify certificates in the Web UI, via `rctyping-app verify`, or using the zero-app-dependency script [verifier/verify_certificate.py](verifier/verify_certificate.py) (Python stdlib + `cryptography`).

---

## Repository Structure

```text
rc-typing/
├── app/                         # FastAPI web app, static UI, SQLite DB, keystore, CLI (rctyping-app, port 8000)
├── registry/                    # Public transparency log & issuer registry service, CLI (rctyping-registry, port 8001)
├── packages/rctyping_common/    # Shared Pydantic models, canonical JSON, Ed25519 crypto, Merkle tree, corpus loader
├── corpus/                      # Passage definitions (build_corpus.py) and attribution/license docs (ATTRIBUTION.md)
├── verifier/                    # Standalone certificate verifier (verify_certificate.py)
├── tests/                       # Top-level standalone verifier tests
├── docker-compose.yml           # Multi-container setup for app + registry
└── pyproject.toml               # uv workspace & pytest configuration
```

---

## Quick Start

### Prerequisites

- **Docker & Docker Compose**, or
- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)**

> **Note:** Generated corpus files (`corpus/data/`) are gitignored (`data/` in `.gitignore`) and copied into the `app` image by `app/Dockerfile`. Generate them before running locally or building with Docker.

### Option 1: Docker Compose

1. Generate the bundled typing corpus:
   ```bash
   python corpus/build_corpus.py
   ```
2. Build and start both `app` (`http://localhost:8000`) and `registry` (`http://localhost:8001`):
   ```bash
   docker compose up --build
   ```
3. Open [http://localhost:8000](http://localhost:8000). Keys (`issuer.key`, `brain.key`, `registry.key`) and SQLite databases persist in the `app-data` and `registry-data` Docker volumes mounted at `/data`.

### Option 2: Local Development (`uv`)

1. Install workspace packages and dev dependencies (`pytest`, `pytest-asyncio`, `httpx`):
   ```bash
   uv sync --all-extras
   ```
2. Generate the typing corpus:
   ```bash
   uv run python corpus/build_corpus.py
   ```
3. Start the transparency registry (Terminal 1):
   ```bash
   uv run rctyping-registry serve --port 8001
   ```
4. Start the typing web application (Terminal 2):
   ```bash
   uv run rctyping-app serve --port 8000
   ```
5. Open [http://localhost:8000](http://localhost:8000). Keys and SQLite databases auto-initialize under `./data` on first run.

---

## Web UI Workflow

- **Typing Test**: Choose a category (and language for `code`), click inside the passage viewport or start typing to begin, and press `Ctrl + Enter` (or click **New Passage**) to load a new passage. Completing a passage opens the certificate modal to download the `.json` certificate or send it to the verifier.
- **Typing Thoughts**: Type markdown thoughts with live WPM, duration, and character count. Press `Enter` to push to the active folder (`Shift+Enter` inserts a newline), drag cards or tree items across folders in the Brain Explorer, download single `.md` notes, or click **Export Brain (.zip)**.
- **Verify Certificate**: Paste JSON or upload a `.json` certificate file to verify its Ed25519 signature over canonical JSON.
- **Stats & History**: View personal bests, test counts, average Net WPM, and average accuracy grouped by category and language.
- **Settings**: Toggle automatic registry publishing, set a default certificate display name, and configure the target public registry URL.

---

## CLI & Standalone Verification

```bash
# Run servers (supports --host, --port, --reload)
uv run rctyping-app serve --host 0.0.0.0 --port 8000
uv run rctyping-registry serve --host 0.0.0.0 --port 8001

# Print the app issuer Key ID, Base64URL, and PEM public key
uv run rctyping-app pubkey

# Verify a certificate using the app CLI (offline or with optional pinned PEM / registry lookup)
uv run rctyping-app verify path/to/certificate.json
uv run rctyping-app verify path/to/certificate.json --pubkey issuer.pem --registry http://localhost:8001

# Standalone third-party verification (requires only Python stdlib + cryptography)
pip install cryptography
python verifier/verify_certificate.py path/to/certificate.json --registry http://localhost:8001
```

When `--registry` is provided, `verify_certificate.py` also verifies the RFC 6962 Merkle inclusion proof against the registry's signed tree root and reports trust tier and revocation status.

---

## API Overview

Interactive OpenAPI docs are served at `/docs` on both services (`http://localhost:8000/docs` and `http://localhost:8001/docs`).

### Typing App (`:8000`)

- `GET /` — Single-page Web UI
- `GET /.well-known/rctyping-pubkey.pem` — Issuer Ed25519 public key (PEM)
- `GET /api/categories` — Available categories and code languages
- `POST /api/sessions` — Start a typing session and receive passage + server nonce
- `POST /api/sessions/{session_id}/finish` — Submit keystrokes, evaluate metrics/anti-cheat, and issue a signed `CertificateEnvelope`
- `GET /api/certificates/{cert_id}`, `GET /api/certificates/{cert_id}/download`, `POST /api/certificates/{cert_id}/publish` — Fetch, download JSON, or re-queue registry publication
- `POST /api/verify` — Verify an uploaded/pasted `CertificateEnvelope`
- `GET /api/stats`, `GET /api/settings`, `PUT /api/settings` — Category stats and user settings
- `GET /api/thoughts/brain`, `POST /api/thoughts`, `PATCH /api/thoughts/{thought_id}`, `DELETE /api/thoughts/{thought_id}`, `POST /api/thoughts/folders`, `DELETE /api/thoughts/folders/{folder_id}`, `GET /api/thoughts/export-zip` — Local encrypted Brain CRUD and `.zip` markdown export

### Public Registry (`:8001`)

- `GET /`, `GET /verify` — Registry lookup Web UI
- `GET /.well-known/rctyping-registry.json` — Registry public key and current Merkle tree root/size
- `POST /v1/issuers/challenge`, `POST /v1/issuers`, `GET /v1/issuers/{issuer_id}` — Proof-of-possession issuer registration and lookup
- `POST /v1/certificates`, `GET /v1/certificates/{cert_id}`, `POST /v1/certificates/{cert_id}/revoke` — Signed certificate submission, record/inclusion-proof lookup, and issuer-signed revocation
- `GET /v1/log/head`, `GET /v1/log/proof/inclusion`, `GET /v1/log/proof/consistency` — RFC 6962 signed tree head and Merkle proofs
- `POST /v1/admin/issuers/{issuer_id}/tier` — Update issuer trust tier (`unverified`, `verified`, `official`) with `X-Admin-Token`

---

## Development, Configuration & Testing

### Running Tests & Hot Reload

```bash
# Run pytest across tests/, packages/rctyping_common/tests, app/tests, and registry/tests
uv run pytest

# Start services with auto-reload
uv run rctyping-registry serve --reload
uv run rctyping-app serve --reload

# Rebuild corpus JSON files and index.json after editing corpus/build_corpus.py
uv run python corpus/build_corpus.py
```

### Configuration

Both services read environment variables or a `.env` file via `pydantic-settings`.

#### App Settings (`RCTYPING_*`)

| Variable | Default | Description |
|---|---|---|
| `RCTYPING_DATA_DIR` | `./data` | Directory for `rctyping.db` and `keys/` (`issuer.key`, `brain.key`) |
| `RCTYPING_HOST` | `0.0.0.0` | Server bind host |
| `RCTYPING_PORT` | `8000` | Server listen port |
| `RCTYPING_KEY_PASSPHRASE` | `None` | Optional passphrase for encrypting/decrypting `issuer.key` |
| `RCTYPING_REGISTRY_URL` | `http://localhost:8001` | Target public registry URL (`http://registry:8001` in Docker Compose) |
| `RCTYPING_PUBLISH_DEFAULT` | `true` | Auto-publish new certificates to the registry |
| `RCTYPING_CORPUS_DIR` | `corpus/data` | Path to generated corpus JSON files (`/app/corpus/data` in Docker) |
| `RCTYPING_MAX_CLOCK_SKEW_MS` | `4000` | Allowed client/server finish duration skew (ms) |
| `RCTYPING_MIN_HUMAN_IKI_MS` | `0.0` | Minimum mean inter-keystroke interval threshold (ms); `0.0` disables the upper WPM cap |
| `RCTYPING_MIN_IKI_STDDEV_MS` | `4.0` | Minimum IKI standard deviation threshold for >=20 intervals (ms) |

#### Registry Settings (`RCTYPING_REGISTRY_*`)

| Variable | Default | Description |
|---|---|---|
| `RCTYPING_REGISTRY_DATA_DIR` | `./data/registry` | Directory for `registry.db` and `keys/` (`registry.key`) |
| `RCTYPING_REGISTRY_HOST` | `0.0.0.0` | Registry bind host |
| `RCTYPING_REGISTRY_PORT` | `8001` | Registry listen port |
| `RCTYPING_REGISTRY_KEY_PASSPHRASE` | `None` | Optional passphrase for `registry.key` |
| `RCTYPING_REGISTRY_ADMIN_TOKEN` | `dev-admin-secret` | `X-Admin-Token` secret for trust-tier updates (`secret-admin-token` in Docker Compose) |

---

## License

Source code is licensed under the [MIT License](LICENSE). See [corpus/ATTRIBUTION.md](corpus/ATTRIBUTION.md) for per-category corpus licenses and attributions.
