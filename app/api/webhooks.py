import hashlib
import hmac
import uuid
import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.audit_request import AuditRequest
from app.api.audit import _run_audit
from app.config import get_settings

router   = APIRouter(prefix="/webhook", tags=["Webhooks"])
settings = get_settings()
logger   = logging.getLogger(__name__)


@router.post("/github")
async def github_push_webhook(
    request:          Request,
    background_tasks: BackgroundTasks,
    db:               AsyncSession = Depends(get_db),
):
    """
    Receives GitHub push events and automatically audits changed files.

    Setup:
      GitHub Repo → Settings → Webhooks → Add webhook
        Payload URL : https://your-domain.com/webhook/github
        Content type: application/json
        Secret      : value of GITHUB_WEBHOOK_SECRET in .env
        Events      : Just the push event
    """
    body      = await request.body()
    event     = request.headers.get("X-GitHub-Event", "")
    signature = request.headers.get("X-Hub-Signature-256", "")

    # Verify HMAC signature if secret is configured
    if settings.github_webhook_secret:
        expected = "sha256=" + hmac.new(
            settings.github_webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("GitHub webhook: invalid signature")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if event == "ping":
        return {"status": "pong"}

    if event != "push":
        return {"status": "ignored", "event": event}

    payload = await request.json()
    repo    = payload.get("repository", {}).get("full_name", "")
    branch  = payload.get("ref", "").replace("refs/heads/", "")

    # Collect all added + modified files from this push
    changed_files = list({
        f
        for commit in payload.get("commits", [])
        for f in (commit.get("added", []) + commit.get("modified", []))
    })

    if not changed_files:
        return {"status": "no_files_changed"}

    job_id = str(uuid.uuid4())[:8].upper()
    audit_req = AuditRequest(
        repo          = repo,
        branch        = branch,
        paths         = changed_files,
        park_to_jira  = True,
        park_to_sheet = True,
    )
    background_tasks.add_task(_run_audit, job_id, audit_req)

    logger.info(f"Webhook triggered audit [{job_id}] for {len(changed_files)} files in {repo}")
    return {
        "status":     "audit_triggered",
        "job_id":     job_id,
        "repo":       repo,
        "branch":     branch,
        "files_count": len(changed_files),
        "files":      changed_files,
        "status_url": f"/audit/status/{job_id}",
    }
