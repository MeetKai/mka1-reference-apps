"""Local CSV analysis with bounded background jobs and temporary in-memory results."""

import logging
import time
from pathlib import Path
from threading import BoundedSemaphore, Lock, Timer
from typing import Annotated
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from httpx import TimeoutException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from workflow import MAX_CSV_BYTES, WorkflowError, analyze, validate_csv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="MKA1 CSV analyst", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
capacity = BoundedSemaphore(1)
jobs = {}
jobs_lock = Lock()
RESULT_TTL_SECONDS = 600
MAX_SAVED_JOBS = 5


def prune_jobs():
    """Call with jobs_lock held; running jobs are never evicted."""
    now = time.monotonic()
    expired = [
        key
        for key, job in jobs.items()
        if job.get("finished_at") is not None and now - job["finished_at"] >= RESULT_TTL_SECONDS
    ]
    for key in expired:
        del jobs[key]


def expire_job(job_id):
    with jobs_lock:
        jobs.pop(job_id, None)


def run_analysis(job_id, raw, question):
    outcome = {"status": "failed", "error": "The analysis was interrupted. Try again."}
    try:
        result = analyze(raw, question)
        outcome = {"status": "completed", "result": result}
    except TimeoutException:
        outcome = {
            "status": "failed",
            "error": "MKA1 timed out before the report was ready. Try a smaller CSV or a narrower question.",
        }
    except WorkflowError as exc:
        outcome = {"status": "failed", "error": str(exc)}
    except Exception as exc:
        logging.getLogger(__name__).warning("Analysis failed: %s", type(exc).__name__)
        outcome = {
            "status": "failed",
            "error": "Analysis failed. Check your API key, model's shell support, and sandbox capacity. No report was accepted.",
        }
    finally:
        # Record completion before releasing capacity for the next analysis.
        with jobs_lock:
            jobs[job_id] = {**outcome, "finished_at": time.monotonic()}
        capacity.release()
        expiry = Timer(RESULT_TTL_SECONDS, expire_job, args=(job_id,))
        expiry.daemon = True
        expiry.start()


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
    background_tasks: BackgroundTasks,
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
    job_id = uuid4().hex
    with jobs_lock:
        prune_jobs()
        completed = sorted(
            (job["finished_at"], key)
            for key, job in jobs.items()
            if job.get("finished_at") is not None
        )
        while len(jobs) >= MAX_SAVED_JOBS and completed:
            _, oldest = completed.pop(0)
            del jobs[oldest]
        jobs[job_id] = {"status": "running"}
    background_tasks.add_task(run_analysis, job_id, raw, question.strip())
    return JSONResponse({"job_id": job_id, "status": "running"}, status_code=202)


@app.get("/api/jobs/{job_id}")
def analysis_status(job_id: str):
    with jobs_lock:
        prune_jobs()
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(
                404, "This analysis has expired or the server restarted. Run it again."
            )
        return {key: value for key, value in job.items() if key != "finished_at"}
