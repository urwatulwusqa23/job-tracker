import time

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.logging import configure_logging, logger, new_request_id, request_id_ctx
from app.routers import ai, applications, auth, cv, google_oauth, pages, stats

configure_logging(settings.LOG_LEVEL)

if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT, traces_sample_rate=0.1)

app = FastAPI(title=settings.APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = new_request_id()
    request_id_ctx.set(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.exception(f"{request.method} {request.url.path} failed after {duration_ms}ms")
        raise
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    logger.info(f"{request.method} {request.url.path} {response.status_code} {duration_ms}ms")
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Liveness + DB connectivity check for uptime monitors / Render health checks."""
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check DB ping failed")
        db_ok = False
    status_code = 200 if db_ok else 503
    return JSONResponse(status_code=status_code, content={"status": "ok" if db_ok else "degraded", "db": db_ok})


app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(auth.me_router)
app.include_router(google_oauth.router)
app.include_router(stats.router)
app.include_router(applications.router)
app.include_router(cv.router)
app.include_router(ai.router)

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except RuntimeError:
    pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=False)
