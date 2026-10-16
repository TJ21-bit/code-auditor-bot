import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.issue import IssueORM
from app.services.hubspot_service import create_task, complete_task, get_task

router = APIRouter(prefix="/hubspot", tags=["HubSpot"])
logger = logging.getLogger(__name__)


@router.get("/status")
async def hubspot_status():
    """Check if HubSpot is configured."""
    from app.config import get_settings
    s = get_settings()
    configured = bool(getattr(s, 'hubspot_api_key', ''))
    return {"configured": configured, "message": "HubSpot connected" if configured else "Add HUBSPOT_API_KEY to .env"}


@router.post("/sync-tasks")
async def sync_tasks(db: AsyncSession = Depends(get_db)):
    """Create HubSpot tasks for all open critical/warning issues without a task."""
    result = await db.execute(
        select(IssueORM)
        .where(IssueORM.status != "resolved")
        .where(IssueORM.severity.in_(["critical", "warning"]))
        .where(IssueORM.jira_ticket_id == None)
    )
    issues = result.scalars().all()
    created = 0
    failed  = 0

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
                issue.jira_ticket_id = f"HS-{task_id}"
                created += 1
        except Exception as e:
            logger.warning(f"HubSpot task failed for {issue.id}: {e}")
            failed += 1

    await db.commit()
    return {"created": created, "failed": failed}


@router.post("/complete/{issue_id}")
async def complete_issue_task(issue_id: str, db: AsyncSession = Depends(get_db)):
    """Mark HubSpot task as complete when issue is resolved."""
    issue = await db.get(IssueORM, issue_id)
    if not issue:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Issue not found")

    if issue.jira_ticket_id and issue.jira_ticket_id.startswith("HS-"):
        task_id = issue.jira_ticket_id.replace("HS-", "")
        success = await complete_task(task_id)
        return {"completed": success, "task_id": task_id}

    return {"completed": False, "message": "No HubSpot task found for this issue"}


@router.get("/test")
async def test_hubspot():
    """Test HubSpot connection by creating a test task."""
    task_id = await create_task({
        "id": "TEST-001",
        "title": "Test task from 88gravity Code Auditor",
        "severity": "info",
        "category": "Test",
        "file_path": "test.py",
        "line_number": "1",
        "repo": "88gravity/code-auditor",
        "description": "This is a test task to verify HubSpot integration is working.",
        "fix_suggestion": "No fix needed — this is a test",
        "owner_name": "Tijeet Singh",
        "owner_email": "tijeetsinghmakkar@gmail.com",
    })
    if task_id:
        return {"success": True, "task_id": task_id, "message": "Test task created in HubSpot!"}
    return {"success": False, "message": "Failed — check HUBSPOT_API_KEY in .env"}