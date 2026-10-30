"""FastAPI application entry point."""
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .contract import STATUS_CODES, ContractError, error_envelope
from .routers import auth, sync, images, load, albums, artists, spotify_actions, jobs, meta, import_csv, exports

logger = logging.getLogger("retention")

RETENTION_INTERVAL_SECONDS = 300  # 5 minutes


def _frontend_dist_dir() -> Path | None:
    candidates = []
    env = os.getenv("FRONTEND_DIST")
    if env:
        candidates.append(Path(env))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend" / "dist")
    here = Path(__file__).resolve().parent
    candidates.append(here.parent / "frontend" / "dist")
    candidates.append(here.parent.parent / "frontend" / "dist")
    for c in candidates:
        if c.is_dir() and (c / "index.html").is_file():
            return c
    return None


async def _run_migrations():
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.info("DATABASE_URL not set; skipping migrations.")
        return
    if db_url.startswith("sqlite"):
        try:
            from .database import engine
            from .models import Base
            await asyncio.to_thread(Base.metadata.create_all, bind=engine)
            logger.info("SQLite schema created/verified.")
        except Exception as e:
            logger.warning("SQLite schema creation failed: %s", e)
        return
    # Postgres path (existing)
    try:
        import psycopg2
        from .services.db_service import run_migrations, wait_for_db

        migrations_dir = os.getenv("MIGRATIONS_DIR", "/app/migrations")
        if not Path(migrations_dir).is_dir():
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass and (Path(meipass) / "migrations").is_dir():
                migrations_dir = str(Path(meipass) / "migrations")
            elif (Path(__file__).resolve().parent.parent / "migrations").is_dir():
                migrations_dir = str(Path(__file__).resolve().parent.parent / "migrations")

        await asyncio.to_thread(wait_for_db, db_url)
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        try:
            await asyncio.to_thread(run_migrations, conn, migrations_dir)
            logger.info("Migrations applied from %s", migrations_dir)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Migration run failed: %s", e)


async def _retention_loop():
    """Delete shortlived playlists whose expiry has passed (best effort)."""
    from .services import retention_service
    await asyncio.sleep(20)  # let startup migrations/DB settle
    while True:
        try:
            await asyncio.to_thread(retention_service.sweep_expired)
        except Exception as e:  # never let the worker kill the app
            logger.warning("retention sweep failed: %s", e)
        await asyncio.sleep(RETENTION_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await _run_migrations()
    task = asyncio.create_task(_retention_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Spotify Library API", version="1.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

@app.exception_handler(StarletteHTTPException)
async def _http_exc(_: Request, exc: StarletteHTTPException):
    # Registered on the Starlette base class, not fastapi.HTTPException: the
    # router raises Starlette's for unmatched routes and wrong methods, and a
    # handler bound to the subclass misses those. Contract §1 requires the
    # nested envelope for ALL errors, including 404/405 on unknown paths.
    code = STATUS_CODES.get(exc.status_code, "error")
    return JSONResponse(status_code=exc.status_code,
                        content=error_envelope(code, str(exc.detail)),
                        headers={"Access-Control-Allow-Origin": "*"})

@app.exception_handler(ContractError)
async def _contract_exc(_: Request, exc: ContractError):
    # Explicit code+status from the endpoint (e.g. 422 not_connected), which the
    # status-derived HTTPException handler cannot express.
    return JSONResponse(status_code=exc.status_code,
                        content=error_envelope(exc.code, exc.message),
                        headers={"Access-Control-Allow-Origin": "*"})

@app.exception_handler(RequestValidationError)
async def _validation_exc(_: Request, exc: RequestValidationError):
    details = "; ".join(
        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
    )
    return JSONResponse(status_code=422,
                        content=error_envelope("validation_error", details),
                        headers={"Access-Control-Allow-Origin": "*"})

@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    return JSONResponse(status_code=500,
                        content=error_envelope("internal_error", str(exc)),
                        headers={"Access-Control-Allow-Origin": "*"})

for r in [auth, sync, images, load, albums, artists, spotify_actions, jobs, meta, import_csv, exports]:
    app.include_router(r.router)

@app.get("/api/v1/health", tags=["health"])
def health():
    return {"status": "ok"}

_dist = _frontend_dist_dir()
if _dist:
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")
else:
    @app.get("/", tags=["health"])
    def root():
        return {"status": "ok", "docs": "/docs"}
