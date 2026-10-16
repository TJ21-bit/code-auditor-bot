import asyncio

async def park_all():
    from app.db.database import AsyncSessionLocal
    from app.models.issue import IssueORM
    from app.services.sheets_service import park_issue
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(IssueORM).where(IssueORM.parked_to_sheet == False))
        issues = result.scalars().all()
        print(f"Parking {len(issues)} issues to Google Sheets...")

        for i, issue in enumerate(issues):
            try:
                row = park_issue({
                    "id": issue.id,
                    "title": issue.title,
                    "severity": issue.severity,
                    "category": issue.category or "General",
                    "status": issue.status,
                    "file_path": issue.file_path or "",
                    "line_number": issue.line_number or "",
                    "repo": issue.repo or "",
                    "language": issue.language or "",
                    "owner_name": issue.owner_name or "",
                    "owner_email": issue.owner_email or "",
                    "jira_ticket_id": issue.jira_ticket_id or "",
                    "jira_ticket_url": issue.jira_ticket_url or "",
                    "description": issue.description or "",
                    "fix_suggestion": issue.fix_suggestion or "",
                    "created_at": str(issue.created_at or ""),
                    "deadline_at": str(issue.deadline_at or ""),
                    "followup_count": issue.followup_count or 0,
                })
                issue.parked_to_sheet = True
                issue.sheet_row_index = row
                print(f"  [{i+1}/{len(issues)}] ✓ {issue.id} → row {row}")
            except Exception as e:
                print(f"  [{i+1}/{len(issues)}] ✗ {issue.id}: {e}")

        await db.commit()
        print(f"\nDone! All issues parked to Google Sheets.")

asyncio.run(park_all())
