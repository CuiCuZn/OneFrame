"""FastAPI application entry point."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import config, db
from .api import assets, channels, generate, jobs, library, models, prompts, system
from .core import library as library_core
from .core import worker
from .errors import AppError
from .providers import catalog as protocol_catalog
from .seed import seed_if_empty, seed_pollinations, seed_prompts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("oneframe")

STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    db.init_db()
    with db.connect() as conn:
        seed_if_empty(conn)
        seed_pollinations(conn)
        seed_prompts(conn)
        variants = library_core.ensure_variants(conn)
        upgraded = library_core.ensure_taxonomy(conn)
    if variants:
        log.info("reference library variants: %s items, %s depth maps", variants["items"], variants["depth"])
    if upgraded:
        log.info("reference library reclassified: %s items, %s facets", upgraded["items"], upgraded["facets"])
    await worker.runner.start()
    log.info("OneFrame ready at http://%s:%s", config.HOST, config.PORT)
    yield
    await worker.runner.stop()


app = FastAPI(title="OneFrame", version=config.APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code, **({"extra": exc.detail} if exc.detail else {})},
    )


for module in (channels, models, generate, jobs, assets, library, prompts, system):
    app.include_router(module.router)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "version": config.APP_VERSION,
        "uptime": int(time.time() - STARTED_AT),
        "protocols": [item["id"] for item in protocol_catalog()],
    }


@app.get("/api/ping")
def ping():
    return {"pong": True}


# ── static SPA (built frontend) ───────────────────────────────────────────
if config.FRONTEND_DIST.exists():
    from fastapi.staticfiles import StaticFiles

    assets_dir = config.FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        candidate = (config.FRONTEND_DIST / full_path).resolve()
        if (
            full_path
            and candidate.is_file()
            and config.FRONTEND_DIST in candidate.parents
        ):
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=3600"})
        return FileResponse(
            config.FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-store"}
        )
