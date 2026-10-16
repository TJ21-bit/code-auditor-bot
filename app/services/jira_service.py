import httpx
import base64
from typing import Tuple, Optional
from app.config import get_settings

settings = get_settings()

SEVERITY_TO_PRIORITY = {
    "critical": "Highest",
    "warning":  "Medium",
    "info":     "Low",
}


def _auth_header() -> dict:
    creds = f"{settings.jira_email}:{settings.jira_api_token}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _make_doc(text: str) -> dict:
    """Wrap plain text in Jira Atlassian Document Format (ADF)."""
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


async def create_ticket(issue: dict) -> Tuple[str, str]:
    """
    Create a Jira issue from an issue dict.
    Returns (ticket_id, ticket_url).
    """
    priority = SEVERITY_TO_PRIORITY.get(issue.get("severity", "info"), "Low")

    description_parts = [
        f"Description:\n{issue.get('description', 'N/A')}",
        f"\nFile: {issue.get('file_path', 'N/A')}",
        f"Line: {issue.get('line_number', 'N/A')}",
        f"Repo: {issue.get('repo', 'N/A')}",
        f"\nSuggested Fix:\n{issue.get('fix_suggestion', 'See description')}",
    ]
    description_text = "\n".join(description_parts)

    payload = {
        "fields": {
            "project":     {"key": settings.jira_project_key},
            "summary":     f"[{issue.get('severity', 'info').upper()}] {issue.get('title', 'Code Issue')}",
            "description": _make_doc(description_text),
            "issuetype":   {"name": "Bug"},
            "priority":    {"name": priority},
            "labels":      [
                "code-audit",
                issue.get("category", "general").lower().replace(" ", "-"),
                issue.get("language", "unknown"),
            ],
        }
    }

    # Only add assignee if we have an email
    if issue.get("owner_email"):
        payload["fields"]["assignee"] = {"emailAddress": issue["owner_email"]}

    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"{settings.jira_base_url}/rest/api/3/issue",
            headers=_auth_header(),
            json=payload,
        )
        res.raise_for_status()
        data = res.json()

    ticket_id  = data["key"]
    ticket_url = f"{settings.jira_base_url}/browse/{ticket_id}"
    return ticket_id, ticket_url


async def add_comment(ticket_id: str, comment: str) -> None:
    """Add a follow-up comment to an existing Jira ticket."""
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{settings.jira_base_url}/rest/api/3/issue/{ticket_id}/comment",
            headers=_auth_header(),
            json={"body": _make_doc(comment)},
        )


async def close_ticket(ticket_id: str) -> None:
    """Transition a Jira ticket to Done/Closed."""
    async with httpx.AsyncClient(timeout=10) as client:
        # Fetch available transitions
        t_res = await client.get(
            f"{settings.jira_base_url}/rest/api/3/issue/{ticket_id}/transitions",
            headers=_auth_header(),
        )
        transitions = t_res.json().get("transitions", [])
        done_id = next(
            (t["id"] for t in transitions
             if t["name"].lower() in ("done", "closed", "resolved", "complete")),
            None,
        )
        if done_id:
            await client.post(
                f"{settings.jira_base_url}/rest/api/3/issue/{ticket_id}/transitions",
                headers=_auth_header(),
                json={"transition": {"id": done_id}},
            )


async def get_ticket_status(ticket_id: str) -> Optional[str]:
    """Return the current status name of a Jira ticket."""
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(
            f"{settings.jira_base_url}/rest/api/3/issue/{ticket_id}?fields=status",
            headers=_auth_header(),
        )
        if not res.is_success:
            return None
    return res.json().get("fields", {}).get("status", {}).get("name")
