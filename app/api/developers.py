from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.developer import DeveloperORM, DeveloperCreate, DeveloperOut, DeveloperUpdate
from app.models.issue import IssueORM
from app.services.email_service import send_developer_issues_email

router = APIRouter(prefix="/developers", tags=["Developers"])


@router.get("/", response_model=List[DeveloperOut])
async def list_developers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DeveloperORM).order_by(DeveloperORM.name))
    return result.scalars().all()


@router.post("/", response_model=DeveloperOut)
async def create_developer(dev: DeveloperCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.get(DeveloperORM, dev.email)
    if existing:
        raise HTTPException(status_code=400, detail="Developer with this email already exists")
    orm = DeveloperORM(
        email=dev.email.lower().strip(),
        name=dev.name.strip(),
        role=dev.role or "Developer",
        created_at=datetime.utcnow(),
    )
    db.add(orm)
    await db.commit()
    return orm


@router.patch("/{email}", response_model=DeveloperOut)
async def update_developer(email: str, update: DeveloperUpdate, db: AsyncSession = Depends(get_db)):
    dev = await db.get(DeveloperORM, email.lower())
    if not dev:
        raise HTTPException(status_code=404, detail="Developer not found")
    if update.name   is not None: dev.name   = update.name
    if update.role   is not None: dev.role   = update.role
    if update.active is not None: dev.active = update.active
    await db.commit()
    return dev


@router.delete("/{email}")
async def delete_developer(email: str, db: AsyncSession = Depends(get_db)):
    dev = await db.get(DeveloperORM, email.lower())
    if not dev:
        raise HTTPException(status_code=404, detail="Developer not found")
    await db.delete(dev)
    await db.commit()
    return {"deleted": email}


@router.post("/{email}/notify")
async def notify_developer(email: str, db: AsyncSession = Depends(get_db)):
    """Send email to one developer with their open issues."""
    dev = await db.get(DeveloperORM, email.lower())
    if not dev:
        raise HTTPException(status_code=404, detail="Developer not found")

    result = await db.execute(
        select(IssueORM)
        .where(IssueORM.owner_email == email.lower())
        .where(IssueORM.status != "resolved")
        .order_by(IssueORM.severity)
    )
    issues = result.scalars().all()

    if not issues:
        return {"message": "No open issues for this developer", "sent": False}

    sent = await send_developer_issues_email(dev.name, dev.email, issues)
    if sent:
        dev.last_notified_at = datetime.utcnow()
        await db.commit()

    return {"message": f"Email sent to {dev.email}" if sent else "Email failed — check SMTP settings", "sent": sent}


@router.post("/notify-all")
async def notify_all_developers(db: AsyncSession = Depends(get_db)):
    """Send emails to ALL active developers who have open issues."""
    devs_result = await db.execute(
        select(DeveloperORM).where(DeveloperORM.active == True)
    )
    devs = devs_result.scalars().all()

    results = []
    for dev in devs:
        issues_result = await db.execute(
            select(IssueORM)
            .where(IssueORM.owner_email == dev.email)
            .where(IssueORM.status != "resolved")
        )
        issues = issues_result.scalars().all()
        if not issues:
            continue
        sent = await send_developer_issues_email(dev.name, dev.email, issues)
        if sent:
            dev.last_notified_at = datetime.utcnow()
        results.append({"email": dev.email, "issues": len(issues), "sent": sent})

    await db.commit()
    return {"notified": results}


@router.get("/{email}/issues")
async def get_developer_issues(email: str, db: AsyncSession = Depends(get_db)):
    """Get all open issues assigned to a developer."""
    result = await db.execute(
        select(IssueORM)
        .where(IssueORM.owner_email == email.lower())
        .where(IssueORM.status != "resolved")
        .order_by(IssueORM.severity)
    )
    issues = result.scalars().all()
    return [
        {
            "id": i.id, "title": i.title, "severity": i.severity,
            "file_path": i.file_path, "status": i.status,
            "deadline_at": i.deadline_at, "repo": i.repo,
        }
        for i in issues
    ]


@router.get("/test-email")
async def test_email(email: str, name: str = "Developer"):
    """Send a test email to verify Resend is working."""
    from app.services.email_service import send_developer_issues_email
    from app.models.issue import IssueORM
    from datetime import datetime, timedelta

    # Create fake issues for the test
    class FakeIssue:
        def __init__(self, title, severity, file_path, status):
            self.title = title
            self.severity = severity
            self.file_path = file_path
            self.status = status
            self.category = "Security"
            self.owner_name = name
            self.owner_email = email

    fake_issues = [
        FakeIssue("Hardcoded API key found in source code", "critical", "src/config.py", "open"),
        FakeIssue("Missing input validation on login endpoint", "warning", "api/auth.py", "open"),
        FakeIssue("Unused import statements", "info", "utils/helpers.js", "open"),
    ]

    sent = await send_developer_issues_email(name, email, fake_issues)
    return {
        "sent": sent,
        "to": email,
        "message": f"Test email {'sent successfully' if sent else 'FAILED — check RESEND_API_KEY in .env'}"
    }