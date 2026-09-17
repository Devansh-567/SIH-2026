"""
Single-container entrypoint for deployment.

The local-dev setup runs Vite on :3000 and uvicorn on :8000, with Vite
proxying /api -> :8000. In a deployed container there is no Vite dev
server, so this module reproduces the same URL shape with one process:

    /api/*   -> the FastAPI app from rfplatform.api.main (unchanged)
    /*       -> the built React bundle (frontend/dist), copied to STATIC_DIR

Because the frontend already targets "/api" (see frontend/src/lib/api.ts)
and both halves are served from one origin, no CORS configuration and no
build-time API URL are needed.

Run with: uvicorn rfplatform.api.server:app --host 0.0.0.0 --port 7860
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from rfplatform.api.main import app as api_app

STATIC_DIR = Path(os.environ.get("RFPLATFORM_STATIC_DIR", "/app/static"))

app = FastAPI(
    title="RF Signal Analysis Platform",
    description="Frontend + API served from a single origin.",
)

# Mounted first so /api/... never falls through to the static handler.
app.mount("/api", api_app)


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Platform-level health check, separate from the API's own /api/health."""
    return JSONResponse({"status": "ok", "static": STATIC_DIR.is_dir()})


# Mounted last: Starlette matches routes in registration order, so the
# catch-all only sees requests that nothing above claimed.
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
else:  # pragma: no cover - only hit if the image was built without the frontend
    @app.get("/")
    def _missing_frontend() -> JSONResponse:
        return JSONResponse(
            {"detail": f"Frontend bundle not found at {STATIC_DIR}. API is at /api."},
            status_code=503,
        )
