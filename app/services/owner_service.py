from typing import Optional, Dict, Tuple
from app.services.github_service import get_file_last_committer

_rr_index = 0


async def _get_team() -> Dict[str, str]:
    """Load team from DB — no hardcoded developers."""
    from app.db.database import AsyncSessionLocal
    from app.models.developer import DeveloperORM
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(DeveloperORM).where(DeveloperORM.active == True)
        )
        devs = result.scalars().all()
        return {d.email: d.name for d in devs}


async def assign_owner(
    repo: str,
    file_path: str,
    branch: str = "main",
    overrides: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    global _rr_index

    team = await _get_team()

    # No developers added yet — return unassigned
    if not team:
        return "Unassigned", ""

    # 1. Explicit override
    if overrides and file_path in overrides:
        email = overrides[file_path]
        return team.get(email, email.split("@")[0].title()), email

    # 2. GitHub blame (last committer)
    try:
        blame_email = await get_file_last_committer(repo, file_path, branch)
        if blame_email and blame_email in team:
            return team[blame_email], blame_email
    except Exception:
        pass

    # 3. Round-robin across active developers
    emails = list(team.keys())
    email = emails[_rr_index % len(emails)]
    _rr_index += 1
    return team[email], email