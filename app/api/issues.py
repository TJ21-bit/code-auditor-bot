from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.issue import IssueORM, IssueOut, IssueUpdate
from app.services.jira_service import close_ticket
from app.services.sheets_service import update_issue_status

router = APIRouter(prefix="/issues", tags=["Issues"])


@router.get("/", response_model=list[IssueOut])
async def list_issues(
    status:      Optional[str] = Query(None, description="open | in_progress | resolved | escalated"),
    severity:    Optional[str] = Query(None, description="critical | warning | info"),
    owner_email: Optional[str] = Query(None),
    repo:        Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """List all issues with optional filters."""
    q = select(IssueORM).order_by(IssueORM.created_at.desc())
    if status:      q = q.where(IssueORM.status == status)
    if severity:    q = q.where(IssueORM.severity == severity)
    if owner_email: q = q.where(IssueORM.owner_email == owner_email)
    if repo:        q = q.where(IssueORM.repo == repo)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/stats", response_model=dict)
async def issue_stats(db: AsyncSession = Depends(get_db)):
    """Return summary counts for the dashboard."""
    result = await db.execute(select(IssueORM))
    issues = result.scalars().all()
    return {
        "total":      len(issues),
        "critical":   sum(1 for i in issues if i.severity == "critical"),
        "warning":    sum(1 for i in issues if i.severity == "warning"),
        "info":       sum(1 for i in issues if i.severity == "info"),
        "open":       sum(1 for i in issues if i.status == "open"),
        "in_progress": sum(1 for i in issues if i.status == "in_progress"),
        "resolved":   sum(1 for i in issues if i.status == "resolved"),
        "escalated":  sum(1 for i in issues if i.status == "escalated"),
        "parked_jira":  sum(1 for i in issues if i.parked_to_jira),
        "parked_sheet": sum(1 for i in issues if i.parked_to_sheet),
    }


@router.get("/{issue_id}", response_model=IssueOut)
async def get_issue(issue_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IssueORM).where(IssueORM.id == issue_id))
    issue  = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    return issue


@router.patch("/{issue_id}", response_model=IssueOut)
async def update_issue(
    issue_id: str,
    update:   IssueUpdate,
    db:       AsyncSession = Depends(get_db),
):
    """
    Update an issue — change status, reassign owner.
    Marking as resolved automatically closes the Jira ticket and updates the sheet.
    """
    result = await db.execute(select(IssueORM).where(IssueORM.id == issue_id))
    issue  = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    if update.resolution_note is not None:
        issue.resolution_note = update.resolution_note

    if update.status:
        issue.status = update.status
        if update.status == "resolved":
            issue.resolved_at = datetime.utcnow()

            # Close Jira ticket
            if issue.jira_ticket_id and issue.parked_to_jira:
                try:
                    await close_ticket(issue.jira_ticket_id)
                except Exception:
                    pass

            # Update Google Sheet
            if issue.sheet_row_index and issue.parked_to_sheet:
                try:
                    update_issue_status(
                        issue.sheet_row_index,
                        "resolved",
                        issue.resolved_at.isoformat(),
                    )
                except Exception:
                    pass

    if update.owner_name:  issue.owner_name  = update.owner_name
    if update.owner_email: issue.owner_email = update.owner_email

    await db.commit()
    return issue


@router.delete("/{issue_id}", response_model=dict)
async def delete_issue(issue_id: str, db: AsyncSession = Depends(get_db)):
    """Hard-delete an issue from the local DB (does not affect Jira/Sheets)."""
    result = await db.execute(select(IssueORM).where(IssueORM.id == issue_id))
    issue  = result.scalar_one_or_none()
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    await db.delete(issue)
    await db.commit()
    return {"deleted": issue_id}


@router.delete("/audit/{job_id}")
async def delete_audit(job_id: str, db: AsyncSession = Depends(get_db)):
    """Delete all issues belonging to an audit job."""
    from sqlalchemy import delete as sql_delete
    result = await db.execute(
        select(IssueORM).where(IssueORM.commit_sha == job_id)
    )
    issues = result.scalars().all()
    count = len(issues)
    if not count:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Audit not found")
    await db.execute(
        sql_delete(IssueORM).where(IssueORM.commit_sha == job_id)
    )
    await db.commit()
    return {"deleted": count, "job_id": job_id}


@router.post("/park-all-to-sheets")
async def park_all_to_sheets(db: AsyncSession = Depends(get_db)):
    """Park all unparked issues to Google Sheets — one tab per project."""
    from app.services.sheets_service import park_issue
    import logging
    logger = logging.getLogger(__name__)

    result = await db.execute(
        select(IssueORM)
        .where(IssueORM.parked_to_sheet == False)
        .order_by(IssueORM.commit_sha)
    )
    issues = result.scalars().all()
    parked = 0
    failed = 0

    for issue in issues:
        try:
            tab_name = (
                issue.project_name
                or (issue.repo.split("/")[-1] if issue.repo and issue.repo != "zip-upload" else None)
                or f"Audit {issue.commit_sha}"
            )
            row = park_issue({
                "id": issue.id, "title": issue.title, "severity": issue.severity,
                "category": issue.category or "General", "status": issue.status,
                "file_path": issue.file_path or "", "line_number": issue.line_number or "",
                "repo": issue.repo or "", "language": issue.language or "",
                "owner_name": issue.owner_name or "", "owner_email": issue.owner_email or "",
                "jira_ticket_id": issue.jira_ticket_id or "", "jira_ticket_url": issue.jira_ticket_url or "",
                "description": issue.description or "", "fix_suggestion": issue.fix_suggestion or "",
                "created_at": str(issue.created_at or ""), "deadline_at": str(issue.deadline_at or ""),
                "followup_count": issue.followup_count or 0,
            }, tab_name=tab_name)
            issue.parked_to_sheet = True
            issue.sheet_row_index = row
            parked += 1
        except Exception as e:
            logger.warning(f"Failed to park {issue.id}: {e}")
            failed += 1

    await db.commit()
    return {"parked": parked, "failed": failed, "message": f"Parked {parked} issues to Google Sheets"}


@router.get("/test-followup")
async def test_followup(db: AsyncSession = Depends(get_db)):
    """Manually trigger follow-up check — for testing without waiting 48h."""
    from app.services.followup_service import run_followup_check
    result = await run_followup_check(db)
    return result


@router.get("/trigger-followup/{issue_id}")
async def trigger_single_followup(issue_id: str, db: AsyncSession = Depends(get_db)):
    """Force send a follow-up email for one specific issue — for testing."""
    from app.services.followup_service import _send_followup_email
    issue = await db.get(IssueORM, issue_id)
    if not issue:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Issue not found")
    await _send_followup_email(issue, hours_overdue=72, followup_num=1)
    return {"sent": True, "to": issue.owner_email, "issue": issue_id}