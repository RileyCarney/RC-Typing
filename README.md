# rc-typing

A local-first typing speed benchmark across categories of thought with **Ed25519 cryptographically signed certificates**, an **RFC 6962-style Merkle transparency log registry**, and an **AES-256-GCM locally encrypted markdown thought capture workspace**.

---

## Features

- **Typing Test Across Categories of Thought**: Benchmark Net WPM, Raw WPM, accuracy, and consistency across `code` (Python, PowerShell, C++, C#, JavaScript, TypeScript, SQL), `prose`, `reading`, `technical`, `formal`, and `conversational` passages.
- **Verifiable Cryptographic Certificates**: Each completed session issues an Ed25519-signed JSON certificate over RFC 8785-style canonical JSON, with server-side anti-cheat checks (clock skew, minimum inter-keystroke interval, and keystroke variance).
- **Public Transparency Registry (`rctyping-registry`)**: Optional RFC 6962 Merkle transparency log and issuer directory for publishing certificates, verifying inclusion proofs, and checking revocation status.
- **Typing Thoughts (Brain Explorer)**: Capture thoughts as `.md` files with live WPM/time tracking (`Enter` to push, `Shift+Enter` for newline), organize into folders via drag-and-drop, store encrypted locally with AES-256-GCM, and export as a `.zip` archive.
- **Offline & Standalone Verification**: Verify certificates in the web UI, via the `rctyping-app verify` CLI, or using the zero-app-dependency script at `verifier/verify_certificate.py`.

---

## Repository Structure

```text
RC-Typing/
├── app/                         # FastAPI web app, static UI, SQLite DB, keystore, CLI (rctyping-app)
├── registry/                    # Transparency log & issuer registry service, CLI (rctyping-registry)
├── packages/rctyping_common/    # Shared models, canonical JSON, Ed25519, Merkle proofs, corpus loader
├── corpus/                      # Passage definitions (build_corpus.py) and attribution docs
├── verifier/                    # Standalone certificate verifier (verify_certificate.py)
├── tests/                       # Top-level integration/verifier tests
├── docker-compose.yml           # Multi-container setup for app + registry
└── pyproject.toml               # uv workspace & pytest configuration
```

---

## Using the Application

### Prerequisites

- **Docker & Docker Compose**, or
- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)**

> **Important:** The generated corpus files (`corpus/data/`) are not checked into git. Generate them before running the app locally or building the `app` Docker image.

### Option 1: Run with Docker Compose

1. Generate the bundled typing corpus:
   ```bash
   python3 corpus/build_corpus.py
   ```
2. Build and start both `app` (port `8000`) and `registry` (port `8001`):
   ```bash
   docker compose up --build
   ```
3. Open [http://localhost:8000](http://localhost:8000) in your browser. Persistent keys and SQLite databases are stored in the `app-data` and `registry-data` Docker volumes mounted at `/data`.

### Option 2: Run Locally with `uv`

1. Install workspace dependencies:
   ```bash
   uv sync
   ```
2. Generate the typing corpus:
   ```bash
   uv run python corpus/build_corpus.py
   ```
3. Start the transparency registry (Terminal 1):
   ```bash
   uv run rctyping-registry serve
   ```
4. Start the typing web application (Terminal 2):
   ```bash
   uv run rctyping-app serve
   ```
5. Open [http://localhost:8000](http://localhost:8000).

### Web UI Workflow

- **Typing Test**: Select a category (and language for `code`), click the passage viewport or start typing to begin, and press `Tab + Enter` (or click **New Passage**) to load another passage. Completing a passage opens the certificate modal where you can download the `.json` certificate or send it straight to the verifier.
- **Typing Thoughts**: Type markdown thoughts with live WPM, elapsed time, and character count. Press `Enter` to save to the selected folder (or `Shift+Enter` for a newline), drag thoughts between folders in the Brain Explorer, and click **Export Brain (.zip)** to download your notes.
- **Verify Certificate**: Paste or upload a certificate `.json` file to verify its Ed25519 signature and check its Merkle inclusion proof against the configured registry.
- **Stats & History**: View aggregated typing metrics broken down by category of thought.
- **Settings**: Toggle automatic publishing to the public registry, set a default certificate display name, and configure the registry URL.

### CLI & Standalone Verification

Inspect your app's issuer public key:
```bash
uv run rctyping-app pubkey
```

Verify a certificate using the app CLI:
```bash
uv run rctyping-app verify path/to/certificate.json --registry http://localhost:8001
# Optional: pin an expected issuer public key
uv run rctyping-app verify path/to/certificate.json --pubkey issuer_pub.pem
```

Verify a certificate with the standalone script (requires only Python stdlib + `cryptography`):
```bash
python3 verifier/verify_certificate.py path/to/certificate.json --registry http://localhost:8001
```

---

## Developing the Application

### Development Setup

Install all workspace packages including `dev` dependencies (`pytest`, `pytest-asyncio`, `httpx`):
```bash
uv sync --extra dev
uv run python corpus/build_corpus.py
```

Run either service with hot-reload enabled:
```bash
uv run rctyping-registry serve --reload
uv run rctyping-app serve --reload
```

Interactive OpenAPI documentation is available while running:
- App API: [http://localhost:8000/docs](http://localhost:8000/docs)
- Registry API: [http://localhost:8001/docs](http://localhost:8001/docs)

### Running Tests

`pyproject.toml` configures `pytest` across all workspace test directories (`tests`, `packages/rctyping_common/tests`, `app/tests`, `registry/tests`):
```bash
uv run --extra dev pytest
```

### Configuration

Both services use `pydantic-settings` and read from environment variables or a `.env` file.

#### App Settings (`RCTYPING_*`)

| Variable | Default | Description |
|---|---|---|
| `RCTYPING_DATA_DIR` | `./data` | Directory for SQLite database and Ed25519 keys |
| `RCTYPING_HOST` | `0.0.0.0` | Bind host for `rctyping-app serve` |
| `RCTYPING_PORT` | `8000` | Bind port for `rctyping-app serve` |
| `RCTYPING_KEY_PASSPHRASE` | `None` | Optional passphrase for local key protection |
| `RCTYPING_REGISTRY_URL` | `http://localhost:8001` | Target public registry URL |
| `RCTYPING_PUBLISH_DEFAULT` | `true` | Auto-publish new certificates to the registry |
| `RCTYPING_CORPUS_DIR` | `corpus/data` | Path to generated corpus JSON files |
| `RCTYPING_MAX_CLOCK_SKEW_MS` | `4000` | Allowed client/server finish timestamp skew (ms) |
| `RCTYPING_MIN_HUMAN_IKI_MS` | `35.0` | Minimum mean inter-keystroke interval anti-cheat threshold (ms) |
| `RCTYPING_MIN_IKI_STDDEV_MS` | `4.0` | Minimum keystroke interval standard deviation threshold (ms) |

#### Registry Settings (`RCTYPING_REGISTRY_*`)

| Variable | Default | Description |
|---|---|---|
| `RCTYPING_REGISTRY_DATA_DIR` | `./data/registry` | Directory for registry SQLite database and signing keys |
| `RCTYPING_REGISTRY_HOST` | `0.0.0.0` | Bind host for `rctyping-registry serve` |
| `RCTYPING_REGISTRY_PORT` | `8001` | Bind port for `rctyping-registry serve` |
| `RCTYPING_REGISTRY_KEY_PASSPHRASE` | `None` | Optional passphrase for registry key protection |
| `RCTYPING_REGISTRY_ADMIN_TOKEN` | `dev-admin-secret` | Admin token for issuer trust-tier management |
| `RCTYPING_REGISTRY_BASE_URL` | `http://localhost:8001` | Public base URL advertised by the registry |

### Updating the Corpus

Passages are defined in `corpus/build_corpus.py` (see `corpus/ATTRIBUTION.md` for source attributions and licenses). After modifying `PASSAGES`, regenerate `corpus/data/`:
```bash
uv run python corpus/build_corpus.py
```

---

## License

[MIT](LICENSE)
