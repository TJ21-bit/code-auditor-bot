import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _settings():
    from app.config import get_settings
    return get_settings()


async def create_task(issue: dict) -> Optional[str]:
    """Create a HubSpot task for a code issue. Returns task ID or None."""
    s = _settings()
    api_key = getattr(s, 'hubspot_api_key', '') or ''
    if not api_key:
        logger.warning("HUBSPOT_API_KEY not set — skipping task creation")
        return None

    sev_priority = {'critical': 'HIGH', 'warning': 'MEDIUM', 'info': 'LOW'}
    priority = sev_priority.get(issue.get('severity', 'info'), 'MEDIUM')

    title = f"[{issue.get('severity','').upper()}] {issue.get('title','Code Issue')}"
    body = f"""Code Audit Issue — {issue.get('repo','')}

File: {issue.get('file_path','')} {f"(Line {issue.get('line_number','')})" if issue.get('line_number') else ''}
Severity: {issue.get('severity','').upper()}
Category: {issue.get('category','')}

Description:
{issue.get('description','')}

Fix Suggestion:
{issue.get('fix_suggestion','')}

Issue ID: {issue.get('id','')}
Assigned to: {issue.get('owner_name','')} ({issue.get('owner_email','')})"""

    # hs_timestamp is required by HubSpot — use deadline or 48h from now
    from datetime import datetime, timedelta
    try:
        dl = issue.get('deadline_at')
        if dl:
            if isinstance(dl, str):
                dl = datetime.fromisoformat(dl.replace('Z',''))
            ts = int(dl.timestamp() * 1000)
        else:
            ts = int((datetime.utcnow() + timedelta(hours=48)).timestamp() * 1000)
    except Exception:
        ts = int((datetime.utcnow() + timedelta(hours=48)).timestamp() * 1000)

    payload = {
        "properties": {
            "hs_task_subject":  title,
            "hs_task_body":     body,
            "hs_task_status":   "NOT_STARTED",
            "hs_task_priority": priority,
            "hs_task_type":     "TODO",
            "hs_timestamp":     ts,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.hubapi.com/crm/v3/objects/tasks",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if resp.is_success:
                task_id = resp.json().get("id")
                logger.info(f"HubSpot task created: {task_id} for {issue.get('id')}")
                return task_id
            else:
                logger.error(f"HubSpot task failed: {resp.status_code} {resp.text}")
                return None
    except Exception as e:
        logger.error(f"HubSpot request failed: {e}")
        return None


async def create_followup_task(issue: dict, followup_num: int) -> Optional[str]:
    """Create a HubSpot follow-up task for overdue issue."""
    issue_copy = dict(issue)
    issue_copy['title'] = f"FOLLOW-UP #{followup_num}: {issue.get('title','')}"
    issue_copy['description'] = (
        f"This issue is overdue (follow-up #{followup_num}).\n\n"
        + (issue.get('description') or '')
    )
    return await create_task(issue_copy)


async def get_task(task_id: str) -> Optional[dict]:
    """Get a HubSpot task by ID."""
    s = _settings()
    api_key = getattr(s, 'hubspot_api_key', '') or ''
    if not api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://api.hubapi.com/crm/v3/objects/tasks/{task_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                params={"properties": "hs_task_subject,hs_task_status,hs_task_priority"},
            )
            if resp.is_success:
                return resp.json()
    except Exception as e:
        logger.error(f"HubSpot get task failed: {e}")
    return None


async def complete_task(task_id: str) -> bool:
    """Mark a HubSpot task as completed."""
    s = _settings()
    api_key = getattr(s, 'hubspot_api_key', '') or ''
    if not api_key:
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                f"https://api.hubapi.com/crm/v3/objects/tasks/{task_id}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"properties": {"hs_task_status": "COMPLETED"}},
            )
            return resp.is_success
    except Exception as e:
        logger.error(f"HubSpot complete task failed: {e}")
        return False