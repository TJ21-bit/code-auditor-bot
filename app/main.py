import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.db.database import init_db
from app.api import audit, issues, webhooks
from app.api import developers
from app.api import hubspot
from app.scheduler.jobs import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Code Auditor Bot...")
    await init_db()
    start_scheduler()
    logger.info("Ready.")
    yield
    stop_scheduler()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="Code Auditor Bot",
    description="AI-powered code audit → Jira + Google Sheets → 48h follow-up",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(audit.router)
app.include_router(issues.router)
app.include_router(webhooks.router)
app.include_router(developers.router)
app.include_router(hubspot.router)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")
templates = Jinja2Templates(directory="frontend/templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request, "active": "dashboard"})

@app.get("/browse", response_class=HTMLResponse)
async def browse(request: Request):
    return templates.TemplateResponse("browse.html", {"request": request, "active": "browse"})

@app.get("/followups", response_class=HTMLResponse)
async def followups(request: Request):
    return templates.TemplateResponse("followups.html", {"request": request, "active": "followups"})

@app.get("/developers", response_class=HTMLResponse)
async def developers_page(request: Request):
    return templates.TemplateResponse("developers.html", {"request": request, "active": "developers"})

@app.get("/new-audit", response_class=HTMLResponse)
async def new_audit(request: Request):
    return templates.TemplateResponse("new_audit.html", {"request": request, "active": "new_audit"})

@app.get("/issue/{issue_id}", response_class=HTMLResponse)
async def issue_detail(request: Request, issue_id: str):
    return templates.TemplateResponse("issue_detail.html", {"request": request, "issue_id": issue_id, "active": "dashboard"})

@app.get("/health")
async def health():
    return {"status": "ok", "service": "code-auditor-bot"}