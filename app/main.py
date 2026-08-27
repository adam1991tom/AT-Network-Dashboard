from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import CONFIG
from app.database import DB_PATH, initialise


VERSION = "2.0.0-dev1"
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="AT Network Dashboard",
    version=VERSION,
)

app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static",
)

templates = Environment(
    loader=FileSystemLoader(BASE_DIR / "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


@app.on_event("startup")
def startup() -> None:
    initialise()


@app.get("/api/health")
def api_health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "environment": CONFIG.environment,
        "database": str(DB_PATH),
    }


@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    template = templates.get_template("dashboard.html")
    return HTMLResponse(
        template.render(
            request=request,
            version=VERSION,
            page="dashboard",
            title="Dashboard",
        )
    )


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request) -> HTMLResponse:
    template = templates.get_template("settings.html")
    return HTMLResponse(
        template.render(
            request=request,
            version=VERSION,
            page="settings",
            title="Settings",
        )
    )
