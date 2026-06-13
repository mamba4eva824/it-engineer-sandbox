"""FastAPI application for the SaaS License Dashboard."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from dashboard.collectors import licenses, okta

REPO_ROOT = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent / "static"

load_dotenv(REPO_ROOT / ".env")

app = FastAPI(title="SaaS License Dashboard", version="1.0.0")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/licenses")
def api_licenses():
    return licenses.collect_all_licenses()


@app.get("/api/pipeline/onboarding")
def api_pipeline_onboarding():
    return okta.collect_onboarding_pipeline()


@app.get("/api/pipeline/offboarding")
def api_pipeline_offboarding():
    return okta.collect_offboarding_pipeline()


@app.get("/api/health")
def api_health():
    return licenses.collect_health()
