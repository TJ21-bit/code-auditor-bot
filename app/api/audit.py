import uuid
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.database import get_db
from app.models.audit_request import AuditRequest
from app.models.issue import IssueORM, IssueOut
from app.services.github_service import (
    get_repo_tree, get_repo_tree_all, get_file_content, detect_language, get_repo_info
)
from app.services.ai_service import audit_code
from app.services.owner_service import assign_owner
from app.config import get_settings

router = APIRouter(prefix="/audit", tags=["Audit"])
logger = logging.getLogger(__name__)


def _settings():
    return get_settings()


# ── POST /audit/ ─────────────────────────────────────────────────
@router.post("/", response_model=dict)
async def trigger_audit(
    request: AuditRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    job_id = str(uuid.uuid4())[:8].upper()
    logger.info(f"[{job_id}] Audit triggered: repo={request.repo} branch={request.branch} paths={request.paths}")
    background_tasks.add_task(_run_audit, job_id, request)
    return {
        "job_id":     job_id,
        "repo":       request.repo,
        "branch":     request.branch,
        "message":    f"Audit started for {request.repo}",
        "status_url": f"/audit/status/{job_id}",
    }


# ── GET /audit/status/{job_id} ────────────────────────────────────
@router.get("/status/{job_id}", response_model=dict)
async def audit_status(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(IssueORM).where(IssueORM.commit_sha == job_id)
    )
    issues = result.scalars().all()
    return {
        "job_id":       job_id,
        "issues_found": len(issues),
        "issues":       [IssueOut.model_validate(i).model_dump(mode="json") for i in issues],
    }


# ── GET /audit/repos/{owner}/{repo}/tree ─────────────────────────
@router.get("/repos/{owner}/{repo}/tree", response_model=dict)
async def get_repo_file_tree(owner: str, repo: str, branch: str = "master"):
    full_repo = f"{owner}/{repo}"
    info = await get_repo_info(full_repo)
    default_branch = info.get("default_branch", "master")

    try:
        all_files = await get_repo_tree_all(full_repo, branch)
        used_branch = branch
    except Exception:
        all_files = await get_repo_tree_all(full_repo, default_branch)
        used_branch = default_branch

    AUDITABLE = {
        ".js",".ts",".jsx",".tsx",".py",".php",".java",".go",
        ".rb",".cs",".cpp",".c",".swift",".kt",".rs",".vue",
        ".sql",".sh",".bash",".yaml",".yml",".env",".json",".config",
    }
    import os
    tree = [{**f, "auditable": os.path.splitext(f["path"])[1].lower() in AUDITABLE}
            for f in all_files]
    auditable_count = sum(1 for f in tree if f["auditable"])

    return {
        "repo":            full_repo,
        "branch":          used_branch,
        "description":     info.get("description"),
        "default_branch":  default_branch,
        "auditable_files": auditable_count,
        "total_files":     len(tree),
        "tree":            tree,
    }


# ── GET /audit/debug/token ───────────────────────────────────────
@router.get("/debug/token", response_model=dict)
async def debug_token():
    import httpx
    s = _settings()
    token = s.anthropic_api_key or ""
    gh_token = s.github_token or ""
    masked_ant = token[:12]+"..."+token[-4:] if len(token) > 16 else ("EMPTY" if not token else token)
    masked_gh  = gh_token[:8]+"..."+gh_token[-4:] if len(gh_token) > 12 else ("EMPTY" if not gh_token else gh_token)

    # Test Anthropic
    ant_status = "not tested"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": token, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]}
            )
            ant_status = f"OK ({r.status_code})" if r.is_success else f"FAIL {r.status_code}: {r.json().get('error',{}).get('message','')}"
    except Exception as e:
        ant_status = f"ERROR: {e}"

    # Test GitHub
    gh_status = "not tested"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            headers = {"Accept": "application/vnd.github+json"}
            if gh_token:
                headers["Authorization"] = f"Bearer {gh_token}"
            r = await client.get("https://api.github.com/user", headers=headers)
            gh_status = f"OK — logged in as {r.json().get('login','?')}" if r.is_success else f"FAIL {r.status_code}"
    except Exception as e:
        gh_status = f"ERROR: {e}"

    return {
        "anthropic_key": masked_ant,
        "anthropic_api": ant_status,
        "github_key":    masked_gh,
        "github_api":    gh_status,
    }


# ── GET /audit/debug/db ──────────────────────────────────────────
@router.get("/debug/db", response_model=dict)
async def debug_db(db: AsyncSession = Depends(get_db)):
    """Check what's actually in the database."""
    result = await db.execute(select(IssueORM).order_by(IssueORM.created_at.desc()).limit(20))
    issues = result.scalars().all()
    return {
        "total_issues": len(issues),
        "latest": [
            {
                "id":         i.id,
                "title":      i.title,
                "repo":       i.repo,
                "job_id":     i.commit_sha,
                "severity":   i.severity,
                "status":     i.status,
                "created_at": str(i.created_at),
            }
            for i in issues
        ]
    }


# ── Helpers ──────────────────────────────────────────────────────
async def _next_issue_number(db: AsyncSession) -> int:
    result = await db.execute(select(func.count()).select_from(IssueORM))
    count = result.scalar() or 0
    return count + 1


# ── Background: GitHub audit ─────────────────────────────────────
async def _run_audit(job_id: str, request: AuditRequest):
    from app.db.database import AsyncSessionLocal

    logger.info(f"[{job_id}] Background audit starting: {request.repo}")

    async with AsyncSessionLocal() as db:
        try:
            s = _settings()

            if request.paths:
                files = [{"path": p, "type": "blob"} for p in request.paths]
            else:
                files = await get_repo_tree(request.repo, request.branch)

            logger.info(f"[{job_id}] {len(files)} files to audit")

            if not files:
                logger.warning(f"[{job_id}] No auditable files found — check GitHub token and repo name")
                return

            issue_counter = await _next_issue_number(db)

            for file_item in files:
                path = file_item["path"]
                lang = detect_language(path)
                logger.info(f"[{job_id}] Auditing: {path}")

                code = await get_file_content(request.repo, path, request.branch)
                if not code or not code.strip():
                    logger.debug(f"[{job_id}] Empty file: {path}")
                    continue

                result = await audit_code(path, lang, code)
                raw_issues = result.get("issues", [])
                logger.info(f"[{job_id}] {path}: {len(raw_issues)} issues found (score={result.get('score')})")

                if not raw_issues:
                    continue

                for raw in raw_issues:
                    issue_id = f"ISS-{str(issue_counter).zfill(4)}"
                    issue_counter += 1

                    # Owner assignment
                    if request.assigned_to:
                        from app.models.developer import DeveloperORM
                        dev = await db.get(DeveloperORM, request.assigned_to)
                        if dev:
                            owner_name, owner_email = dev.name, dev.email
                        else:
                            owner_name, owner_email = request.assigned_to, request.assigned_to
                    else:
                        owner_name, owner_email = await assign_owner(
                            request.repo, path, request.branch, request.owner_overrides
                        )

                    deadline = (
                        datetime.now(timezone.utc).replace(tzinfo=None)
                        + timedelta(hours=s.followup_interval_hours)
                    )

                    orm = IssueORM(
                        id             = issue_id,
                        title          = raw.get("title", "Untitled"),
                        description    = raw.get("description", ""),
                        fix_suggestion = raw.get("fix", ""),
                        severity       = raw.get("severity", "info"),
                        category       = raw.get("category", "General"),
                        status         = "open",
                        repo           = request.repo,
                        file_path      = path,
                        line_number    = str(raw.get("line", "")),
                        language       = lang,
                        commit_sha     = job_id,
                        project_name   = request.project_name or request.repo.split("/")[-1],
                        owner_name     = owner_name,
                        owner_email    = owner_email,
                        created_at     = datetime.utcnow(),
                        deadline_at    = deadline,
                        followup_count = 0,
                    )
                    db.add(orm)
                    logger.info(f"[{job_id}] Saved {issue_id}: {orm.title[:50]}")

                    # Park to Jira
                    if request.park_to_jira and s.jira_base_url:
                        try:
                            from app.services.jira_service import create_ticket
                            issue_dict = {
                                "id": issue_id, "title": orm.title, "severity": orm.severity,
                                "description": orm.description, "fix_suggestion": orm.fix_suggestion,
                                "file_path": path, "repo": request.repo,
                            }
                            ticket_id, ticket_url = await create_ticket(issue_dict)
                            orm.jira_ticket_id  = ticket_id
                            orm.jira_ticket_url = ticket_url
                            orm.parked_to_jira  = True
                        except Exception as e:
                            logger.warning(f"[{job_id}] Jira failed: {e}")

            await db.commit()
            total = issue_counter - 1
            logger.info(f"[{job_id}] ✅ Audit complete — {total} total issues saved to DB")

            # Park all issues to Google Sheets in one batch after commit
            if s.google_sheet_id:  # park whenever sheet is configured
                try:
                    await _park_all_to_sheets(db, job_id)
                except Exception as e:
                    logger.warning(f"[{job_id}] Sheets batch parking failed: {e}")

            # Create HubSpot tasks for each issue
            try:
                await _create_hubspot_tasks(db, job_id)
            except Exception as e:
                logger.warning(f"[{job_id}] HubSpot tasks failed: {e}")

            # Send email notifications to each assigned developer
            try:
                await _notify_developers(db, job_id)
            except Exception as e:
                logger.warning(f"[{job_id}] Email notification failed: {e}")

        except Exception as e:
            logger.error(f"[{job_id}] ❌ Audit failed: {e}", exc_info=True)
            await db.rollback()


# ── Post-audit: park to sheets ──────────────────────────────────
async def _park_all_to_sheets(db, job_id: str):
    """Park all issues from this job to Google Sheets — one tab per project."""
    from app.services.sheets_service import park_issue
    from sqlalchemy import select

    result = await db.execute(
        select(IssueORM)
        .where(IssueORM.commit_sha == job_id)
        .where(IssueORM.parked_to_sheet == False)
    )
    issues = result.scalars().all()
    if not issues:
        logger.info(f"[{job_id}] No unparked issues to sheet")
        return

    # Use project_name as tab — fallback to repo name or job_id
    first = issues[0]
    tab_name = (
        first.project_name
        or (first.repo.split('/')[-1] if first.repo and first.repo != 'zip-upload' else None)
        or f"Audit {job_id}"
    )

    logger.info(f"[{job_id}] Parking {len(issues)} issues → sheet tab '{tab_name}'")

    for issue in issues:
        try:
            row = park_issue({
                "id": issue.id, "title": issue.title, "severity": issue.severity,
                "category": issue.category or "General", "status": issue.status,
                "file_path": issue.file_path or "", "line_number": issue.line_number or "",
                "repo": issue.repo or "", "language": issue.language or "",
                "owner_name": issue.owner_name or "", "owner_email": issue.owner_email or "",
                "jira_ticket_id": "", "jira_ticket_url": "",
                "description": issue.description or "", "fix_suggestion": issue.fix_suggestion or "",
                "created_at": str(issue.created_at or ""), "deadline_at": str(issue.deadline_at or ""),
                "followup_count": issue.followup_count or 0,
            }, tab_name=tab_name)
            issue.parked_to_sheet = True
            issue.sheet_row_index = row
            logger.info(f"[{job_id}] Parked {issue.id} → '{tab_name}' row {row}")
        except Exception as e:
            logger.warning(f"[{job_id}] Failed to park {issue.id}: {e}")

    await db.commit()
    logger.info(f"[{job_id}] ✅ Sheets parking complete — tab '{tab_name}'")


# ── Post-audit: HubSpot tasks ───────────────────────────────────
async def _create_hubspot_tasks(db, job_id: str):
    """Create HubSpot tasks for each critical/warning issue in this job."""
    from app.services.hubspot_service import create_task
    from app.config import get_settings
    from sqlalchemy import select

    s = get_settings()
    if not getattr(s, 'hubspot_api_key', ''):
        return  # Skip if not configured

    result = await db.execute(
        select(IssueORM)
        .where(IssueORM.commit_sha == job_id)
        .where(IssueORM.severity.in_(['critical', 'warning']))
    )
    issues = result.scalars().all()
    logger.info(f"[{job_id}] Creating HubSpot tasks for {len(issues)} issues")

    for issue in issues:
        try:
            task_id = await create_task({
                "id": issue.id, "title": issue.title,
                "severity": issue.severity, "category": issue.category,
                "file_path": issue.file_path, "line_number": issue.line_number,
                "repo": issue.repo, "description": issue.description,
                "fix_suggestion": issue.fix_suggestion,
                "owner_name": issue.owner_name, "owner_email": issue.owner_email,
                "deadline_at": issue.deadline_at,
            })
            if task_id:
                issue.jira_ticket_id = f"HS-{task_id}"  # reuse field for HubSpot task ID
                logger.info(f"[{job_id}] HubSpot task {task_id} for {issue.id}")
        except Exception as e:
            logger.warning(f"[{job_id}] HubSpot task failed for {issue.id}: {e}")

    await db.commit()


# ── Post-audit: email developers ────────────────────────────────
async def _notify_developers(db, job_id: str):
    """After audit completes, email each developer their assigned issues."""
    from app.services.email_service import send_developer_issues_email
    from sqlalchemy import select

    # Get all issues from this job
    result = await db.execute(
        select(IssueORM).where(IssueORM.commit_sha == job_id)
    )
    issues = result.scalars().all()
    if not issues:
        return

    # Group by owner email
    by_owner = {}
    for i in issues:
        if i.owner_email:
            if i.owner_email not in by_owner:
                by_owner[i.owner_email] = {'name': i.owner_name or i.owner_email, 'issues': []}
            by_owner[i.owner_email]['issues'].append(i)

    # Send one email per developer
    for email, data in by_owner.items():
        sent = await send_developer_issues_email(data['name'], email, data['issues'])
        if sent:
            logger.info(f"[{job_id}] Notified {email} ({len(data['issues'])} issues)")
        else:
            logger.warning(f"[{job_id}] Failed to notify {email}")


# ── Background: Zip audit ─────────────────────────────────────────
import zipfile, tempfile, os
from fastapi import UploadFile, File, Form


@router.post("/upload-zip", response_model=dict)
async def audit_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    park_to_jira:  bool = Form(False),
    park_to_sheet: bool = Form(False),
    assigned_to:   str  = Form(None),
    project_name:  str  = Form(None),
):
    if not file.filename.endswith(".zip"):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Only .zip files are supported")
    job_id   = str(uuid.uuid4())[:8].upper()
    zip_bytes = await file.read()
    background_tasks.add_task(_run_zip_audit, job_id, zip_bytes, park_to_jira, park_to_sheet, assigned_to, project_name)
    return {
        "job_id":     job_id,
        "message":    f"Zip audit started — {file.filename}",
        "status_url": f"/audit/status/{job_id}",
    }


async def _run_zip_audit(job_id: str, zip_bytes: bytes, park_to_jira: bool, park_to_sheet: bool, assigned_to: str = None, project_name: str = None):
    from app.db.database import AsyncSessionLocal
    from app.services.github_service import _is_auditable

    logger.info(f"[{job_id}] Zip audit starting")

    async with AsyncSessionLocal() as db:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, "upload.zip")
                with open(zip_path, "wb") as f:
                    f.write(zip_bytes)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmpdir)

                auditable_files = []
                for root, _, files in os.walk(tmpdir):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        rel   = os.path.relpath(fpath, tmpdir).replace("\\", "/")
                        if not rel.startswith("upload.zip") and _is_auditable(rel):
                            auditable_files.append((rel, fpath))

                logger.info(f"[{job_id}] {len(auditable_files)} auditable files in zip")
                s = _settings()
                issue_counter = await _next_issue_number(db)

                for rel_path, abs_path in auditable_files:
                    try:
                        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                            code = f.read()
                        if not code.strip():
                            continue
                        lang   = detect_language(rel_path)
                        result = await audit_code(rel_path, lang, code)
                        raw_issues = result.get("issues", [])
                        logger.info(f"[{job_id}] {rel_path}: {len(raw_issues)} issues")

                        for raw in raw_issues:
                            issue_id = f"ISS-{str(issue_counter).zfill(4)}"
                            issue_counter += 1
                            deadline = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=s.followup_interval_hours)

                            if assigned_to:
                                from app.models.developer import DeveloperORM
                                dev = await db.get(DeveloperORM, assigned_to)
                                owner_name  = dev.name  if dev else assigned_to
                                owner_email = dev.email if dev else assigned_to
                            else:
                                owner_name, owner_email = await assign_owner("zip-upload", rel_path, "")

                            orm = IssueORM(
                                id=issue_id, title=raw.get("title","Untitled"),
                                description=raw.get("description",""), fix_suggestion=raw.get("fix",""),
                                severity=raw.get("severity","info"), category=raw.get("category","General"),
                                status="open", repo="zip-upload", file_path=rel_path,
                                line_number=str(raw.get("line","")), language=lang,
                                commit_sha=job_id, project_name=project_name or "Zip Upload",
                                owner_name=owner_name, owner_email=owner_email,
                                created_at=datetime.utcnow(), deadline_at=deadline, followup_count=0,
                            )
                            db.add(orm)
                    except Exception as e:
                        logger.error(f"[{job_id}] Error on {rel_path}: {e}")

                await db.commit()
                logger.info(f"[{job_id}] ✅ Zip audit complete")

        except Exception as e:
            logger.error(f"[{job_id}] ❌ Zip audit failed: {e}", exc_info=True)
            await db.rollback()