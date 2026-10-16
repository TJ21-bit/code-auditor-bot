import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
from app.services.followup_service import run_followup_check
from app.models.issue import IssueORM


def _make_issue(id, hours_overdue=5, followup_count=0):
    i = IssueORM()
    i.id            = id
    i.title         = f"Test issue {id}"
    i.severity      = "critical"
    i.status        = "open"
    i.owner_name    = "Rahul S."
    i.owner_email   = "rahul@88gravity.com"
    i.file_path     = "auth/login.py"
    i.repo          = "88gravity/test"
    i.description   = "Test description"
    i.fix_suggestion = "Fix it"
    i.followup_count = followup_count
    i.deadline_at   = datetime.utcnow() - timedelta(hours=hours_overdue)
    i.jira_ticket_id = f"DEV-{id}"
    i.jira_ticket_url = f"https://jira/DEV-{id}"
    i.sheet_row_index = 2
    i.parked_to_jira  = True
    i.parked_to_sheet = True
    return i


@pytest.mark.asyncio
async def test_followup_sends_notifications():
    issues = [_make_issue("ISS-0001", hours_overdue=10)]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = issues
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit  = AsyncMock()

    with patch("app.services.followup_service.add_comment", AsyncMock()), \
         patch("app.services.followup_service.update_followup_count"), \
         patch("app.services.followup_service._send_email"), \
         patch("app.services.followup_service._send_slack", AsyncMock()), \
         patch("app.services.followup_service.settings") as mock_settings:

        mock_settings.smtp_user         = "test@test.com"
        mock_settings.slack_webhook_url = "https://hooks.slack.com/test"
        mock_settings.jira_base_url     = "https://jira.test.com"
        mock_settings.google_sheet_id   = "sheet123"

        summary = await run_followup_check(mock_db)

    assert summary["checked"]  == 1
    assert summary["notified"] == 1
    assert issues[0].followup_count == 1


@pytest.mark.asyncio
async def test_followup_escalates_after_3():
    issues = [_make_issue("ISS-0002", hours_overdue=50, followup_count=2)]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = issues
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit  = AsyncMock()

    with patch("app.services.followup_service.add_comment", AsyncMock()), \
         patch("app.services.followup_service.update_followup_count"), \
         patch("app.services.followup_service.update_issue_status"), \
         patch("app.services.followup_service._send_email"), \
         patch("app.services.followup_service._send_slack", AsyncMock()), \
         patch("app.services.followup_service.settings") as mock_settings:

        mock_settings.smtp_user         = "test@test.com"
        mock_settings.slack_webhook_url = ""
        mock_settings.jira_base_url     = "https://jira.test.com"
        mock_settings.google_sheet_id   = "sheet123"

        summary = await run_followup_check(mock_db)

    assert summary["escalated"] == 1
    assert issues[0].status == "escalated"


@pytest.mark.asyncio
async def test_followup_skips_resolved():
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []  # query filters resolved out
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit  = AsyncMock()

    summary = await run_followup_check(mock_db)
    assert summary["checked"]  == 0
    assert summary["notified"] == 0
