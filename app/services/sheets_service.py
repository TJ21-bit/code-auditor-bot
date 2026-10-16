import json
import time
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADERS = [
    "Issue ID", "Title", "Severity", "Category", "Status",
    "File", "Line", "Repo", "Language",
    "Owner Name", "Owner Email",
    "Jira Ticket ID", "Jira Ticket URL",
    "Description", "Fix Suggestion",
    "Created At", "Deadline", "Resolved At", "Follow-up Count",
]


def _get_client():
    from app.config import get_settings
    s = get_settings()
    if s.google_credentials_json:
        info = json.loads(s.google_credentials_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_file(
            s.google_service_account_json, scopes=SCOPES
        )
    return gspread.authorize(creds), s


def _get_or_create_worksheet(tab_name: str):
    """Get existing worksheet or create a new one with headers."""
    gc, s = _get_client()
    sh = gc.open_by_key(s.google_sheet_id)

    # Clean tab name — sheets has 100 char limit, no special chars
    safe_name = tab_name[:80].replace('/', '-').replace('\\', '-').replace(':', '-').replace('*', '').replace('?', '').replace('[', '').replace(']', '')

    try:
        ws = sh.worksheet(safe_name)
        # Check headers exist
        first = ws.row_values(1)
        if not first or first[0] != "Issue ID":
            ws.insert_row(HEADERS, index=1)
            ws.format("A1:S1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.08, "green": 0.11, "blue": 0.17}})
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=safe_name, rows=2000, cols=len(HEADERS))
        ws.append_row(HEADERS)
        ws.format("A1:S1", {
            "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "backgroundColor": {"red": 0.08, "green": 0.11, "blue": 0.17}
        })

    return ws


def _get_worksheet():
    """Legacy: get default Code Issues tab."""
    return _get_or_create_worksheet("Code Issues")


def park_issue(issue: dict, tab_name: str = None) -> int:
    """
    Append issue to a sheet tab.
    If tab_name is provided, uses that tab (creates if needed).
    Falls back to 'Code Issues' tab.
    """
    time.sleep(0.5)  # avoid rate limit

    if tab_name:
        ws = _get_or_create_worksheet(tab_name)
    else:
        ws = _get_worksheet()

    row = [
        issue.get("id", ""),
        issue.get("title", ""),
        issue.get("severity", ""),
        issue.get("category", ""),
        issue.get("status", "open"),
        issue.get("file_path", ""),
        str(issue.get("line_number", "")),
        issue.get("repo", ""),
        issue.get("language", ""),
        issue.get("owner_name", ""),
        issue.get("owner_email", ""),
        issue.get("jira_ticket_id", ""),
        issue.get("jira_ticket_url", ""),
        issue.get("description", ""),
        issue.get("fix_suggestion", ""),
        str(issue.get("created_at", datetime.utcnow().isoformat())),
        str(issue.get("deadline_at", "")),
        "",  # Resolved At
        str(issue.get("followup_count", 0)),
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return len(ws.col_values(1))


def update_issue_status(row_index: int, status: str, resolved_at: str = "", tab_name: str = None) -> None:
    if tab_name:
        ws = _get_or_create_worksheet(tab_name)
    else:
        ws = _get_worksheet()
    status_col   = HEADERS.index("Status") + 1
    resolved_col = HEADERS.index("Resolved At") + 1
    ws.update_cell(row_index, status_col, status)
    if resolved_at:
        ws.update_cell(row_index, resolved_col, resolved_at)


def update_followup_count(row_index: int, count: int, tab_name: str = None) -> None:
    if tab_name:
        ws = _get_or_create_worksheet(tab_name)
    else:
        ws = _get_worksheet()
    col = HEADERS.index("Follow-up Count") + 1
    ws.update_cell(row_index, col, count)


def get_all_issues(tab_name: str = None) -> list:
    if tab_name:
        ws = _get_or_create_worksheet(tab_name)
    else:
        ws = _get_worksheet()
    return ws.get_all_records()