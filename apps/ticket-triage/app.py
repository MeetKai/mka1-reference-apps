"""Local-only reference app. Add real application authentication before remote hosting."""

import logging
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from workflow import WorkflowError, classify

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="MKA1 ticket triage", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
capacity = BoundedSemaphore(2)


@app.middleware("http")
async def local_requests_only(request: Request, call_next):
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse(
                {"detail": "Cross-origin requests are not allowed."}, status_code=403
            )
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "Cross-site requests are not allowed."}, status_code=403)
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


@app.get("/api/samples")
def samples():
    import json

    return json.loads((ROOT / "samples.json").read_text())


class TicketRequest(BaseModel):
    ticket: str = Field(min_length=10, max_length=12_000)


@app.post("/api/triage")
def triage(body: TicketRequest):
    if not body.ticket.strip() or len(body.ticket.strip()) < 10:
        raise HTTPException(422, "Enter a ticket with at least 10 non-whitespace characters.")
    if not capacity.acquire(blocking=False):
        raise HTTPException(429, "Two requests are already running. Wait for one to finish.")
    try:
        return classify(body.ticket.strip())
    except WorkflowError as exc:
        raise HTTPException(502, str(exc)) from exc
    except Exception as exc:
        logging.getLogger(__name__).warning("Triage failed: %s", type(exc).__name__)
        raise HTTPException(
            502,
            "The API request failed. Check your key, model access, and gateway URL. No decision was saved.",
        ) from exc
    finally:
        capacity.release()
