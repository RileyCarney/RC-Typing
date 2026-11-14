"""FastAPI main application entrypoint."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from rctyping_app.api.routes import router as api_router
from rctyping_app.config import settings
from rctyping_app.core.keystore import KeyStore
from rctyping_app.db.session import init_db
from rctyping_app.services.publish_worker import PublishWorker
from rctyping_common.corpus import CorpusRepository

app_keystore: KeyStore | None = None
app_corpus: CorpusRepository | None = None
app_worker: PublishWorker | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_keystore, app_corpus, app_worker
    # 1. Initialize DB
    init_db()

    # 2. Initialize Keystore
    keys_dir = settings.data_dir / "keys"
    app_keystore = KeyStore(keys_dir=keys_dir, passphrase=settings.key_passphrase)

    # 3. Load Corpus
    corpus_path = settings.corpus_dir
    if not corpus_path.exists():
        # Fallback to local corpus path
        corpus_path = Path(__file__).resolve().parent.parent.parent.parent / "corpus" / "data"
    app_corpus = CorpusRepository.load_from_dir(corpus_path)

    # 4. Start background publish worker
    app_worker = PublishWorker(keystore=app_keystore)
    app_worker.start()

    yield

    # Teardown
    if app_worker:
        app_worker.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="rc-typing",
        description="Typing application measuring speed across categories of thought with verifiable certificates",
        version="0.1.0",
        lifespan=lifespan,
    )

    # API router
    app.include_router(api_router, prefix="/api")

    # Well-known public key
    @app.get("/.well-known/rctyping-pubkey.pem")
    def get_public_key():
        if app_keystore is None:
            return Response("KeyStore not initialized", status_code=503)
        return Response(content=app_keystore.get_public_key_pem(), media_type="application/x-pem-file")

    # Static UI files
    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(static_dir / "favicon.svg", media_type="image/svg+xml")

    return app


app = create_app()
