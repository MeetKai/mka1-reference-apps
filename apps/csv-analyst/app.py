"""Local CSV analysis app; no uploads or reports are retained by this web server."""

import logging
from pathlib import Path
from threading import BoundedSemaphore
from typing import Annotated
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from workflow import MAX_CSV_BYTES, WorkflowError, analyze, validate_csv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="MKA1 CSV analyst", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
capacity = BoundedSemaphore(1)


@app.middleware("http")
async def local_requests_only(request: Request, call_next):
    if request.method == "POST":
        origin = request.headers.get("origin")
        if (
            origin and urlparse(origin).netloc != request.headers.get("host")
        ) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed."}, status_code=403
            )
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "Invalid upload length."}, status_code=400)
        if length > MAX_CSV_BYTES + 20_000:
            return JSONResponse({"detail": "Upload a CSV smaller than 1 MB."}, status_code=413)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/sample")
def sample():
    return FileResponse(ROOT / "sample.csv", media_type="text/csv", filename="sample.csv")


@app.post("/api/analyze")
def analyze_csv(
    file: Annotated[UploadFile, File()],
    question: Annotated[str, Form(min_length=10, max_length=2000)],
):
    try:
        raw = file.file.read(MAX_CSV_BYTES + 1)
    finally:
        file.file.close()
    try:
        validate_csv(raw)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if len(question.strip()) < 10:
        raise HTTPException(422, "Enter a question with at least 10 non-whitespace characters.")
    if not capacity.acquire(blocking=False):
        raise HTTPException(429, "An analysis is already running. Wait for it to finish.")
    try:
        return analyze(raw, question.strip())
    except WorkflowError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        logging.getLogger(__name__).warning("Analysis failed: %s", type(exc).__name__)
        raise HTTPException(
            502,
            "Analysis failed. Check your API key, model's shell support, and sandbox capacity. No report was accepted.",
        ) from exc
    finally:
        capacity.release()
