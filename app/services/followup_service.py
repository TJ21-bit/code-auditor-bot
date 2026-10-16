import httpx
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from app.models.issue import IssueORM
from app.services.jira_service import add_comment
from app.services.sheets_service import update_followup_count, update_issue_status
from app.config import get_settings

logger = logging.getLogger(__name__)


async def run_followup_check(db: AsyncSession) -> dict:
    """
    Runs every hour via APScheduler.
    Finds all open/in-progress issues whose deadline has passed
    and sends follow-up notifications via email, Slack, and Jira comment.
    After 3 follow-ups, escalates the issue.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    result = await db.execute(
        select(IssueORM).where(
            IssueORM.status.in_(["open", "in_progress"]),
            IssueORM.deadline_at <= now,
        )
    )
    overdue_issues = result.scalars().all()

    notified = 0
    escalated = 0

    for issue in overdue_issues:
        hours_overdue = int((now - issue.deadline_at).total_seconds() / 3600)
        followup_num  = issue.followup_count + 1

        subject = f"[Code Audit] Follow-up #{followup_num}: {issue.id} — {issue.title}"
        body = _build_followup_message(issue, hours_overdue, followup_num)

        # 1. Email owner via Resend
        if issue.owner_email:
            try:
                await _send_followup_email(issue, hours_overdue, followup_num)
                logger.info(f"Follow-up email sent to {issue.owner_email} for {issue.id}")
            except Exception as e:
                logger.warning(f"Email failed for {issue.id}: {e}")

        # 2. Slack notification
        if get_settings().slack_webhook_url:
            try:
                await _send_slack(issue, hours_overdue, followup_num, get_settings())
            except Exception as e:
                logger.warning(f"Slack failed for {issue.id}: {e}")

        # 3. Jira comment
        if issue.jira_ticket_id and get_settings().jira_base_url:
            try:
                await add_comment(issue.jira_ticket_id, body)
            except Exception as e:
                logger.warning(f"Jira comment failed for {issue.id}: {e}")

        # 4. Update Google Sheet follow-up count
        if issue.sheet_row_index and get_settings().google_sheet_id:
            try:
                update_followup_count(issue.sheet_row_index, followup_num)
            except Exception as e:
                logger.warning(f"Sheet update failed for {issue.id}: {e}")

        # 5. Persist changes
        issue.followup_count   = followup_num
        issue.last_followup_at = now

        if followup_num >= 3:
            issue.status = "escalated"
            # Update sheet status too
            if issue.sheet_row_index and get_settings().google_sheet_id:
                try:
                    update_issue_status(issue.sheet_row_index, "escalated")
                except Exception:
                    pass
            escalated += 1
            logger.warning(f"Issue {issue.id} ESCALATED after {followup_num} follow-ups")

        notified += 1

    await db.commit()
    return {
        "checked":   len(overdue_issues),
        "notified":  notified,
        "escalated": escalated,
        "timestamp": now.isoformat(),
    }


def _build_followup_message(issue: IssueORM, hours_overdue: int, followup_num: int) -> str:
    return f"""
Hi {issue.owner_name or 'Team'},

This is follow-up #{followup_num} for an unresolved code audit issue assigned to you.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Issue ID   : {issue.id}
Title      : {issue.title}
Severity   : {issue.severity.upper()}
File       : {issue.file_path}
Line       : {issue.line_number or 'N/A'}
Repo       : {issue.repo}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Status     : {issue.status.upper()} — {hours_overdue}h overdue

Problem:
{issue.description or 'See Jira ticket for details.'}

Suggested Fix:
{issue.fix_suggestion or 'See Jira ticket for details.'}

{f'Jira Ticket: {issue.jira_ticket_url}' if issue.jira_ticket_url else ''}

Please resolve this issue or update its status in Jira.
{'⚠️  This issue will be ESCALATED to management after the next follow-up.' if followup_num >= 2 else ''}

— Code Auditor Bot | 88gravity
""".strip()


async def _send_followup_email(issue: IssueORM, hours_overdue: int, followup_num: int) -> None:
    """Send follow-up email via Resend."""
    s = get_settings()
    api_key   = getattr(s, 'resend_api_key', '') or ''
    from_addr = getattr(s, 'smtp_from', '') or 'onboarding@resend.dev'

    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping follow-up email")
        return

    sev_color = {'critical': '#dc2626', 'warning': '#d97706', 'info': '#2563eb'}.get(issue.severity, '#64748b')
    escalation_warning = ''
    if followup_num >= 2:
        escalation_warning = '<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:12px 16px;margin-top:16px;font-size:13px;color:#dc2626;font-weight:600">⚠️ This issue will be escalated to management after the next follow-up.</div>'

    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Inter',system-ui,sans-serif">
<div style="max-width:600px;margin:32px auto;background:#fff;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.09)">
  <div style="background:#0d1b2a;padding:20px 28px;display:flex;align-items:center;gap:12px">
    <div style="background:linear-gradient(135deg,#c89b3c,#dbb455);width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:800;color:#0d1b2a;font-size:12px">88</div>
    <div>
      <div style="color:#fff;font-weight:700;font-size:15px">Code Auditor — Follow-up #{followup_num}</div>
      <div style="color:rgba(255,255,255,.4);font-size:11px">88gravity · internal tool</div>
    </div>
  </div>
  <div style="padding:24px 28px">
    <h2 style="margin:0 0 6px;font-size:20px;font-weight:800;color:#0f172a">Hi {issue.owner_name or 'Developer'} 👋</h2>
    <p style="margin:0 0 20px;color:#475569;font-size:14px">This is follow-up <strong>#{followup_num}</strong> for an unresolved issue assigned to you. It is <strong>{hours_overdue} hours overdue</strong>.</p>
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:18px;margin-bottom:20px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">
        <span style="background:{sev_color};color:#fff;font-size:10px;font-weight:700;padding:3px 9px;border-radius:99px;text-transform:uppercase;letter-spacing:.5px">{issue.severity}</span>
        <span style="font-size:11px;color:#94a3b8;font-family:monospace">{issue.id}</span>
      </div>
      <div style="font-weight:700;font-size:16px;color:#0f172a;margin-bottom:8px">{issue.title}</div>
      <div style="font-size:12.5px;color:#64748b;font-family:monospace;margin-bottom:12px">{issue.file_path}{f' · Line {issue.line_number}' if issue.line_number else ''}</div>
      {'<div style="font-size:13px;color:#475569;line-height:1.6;margin-bottom:10px">'+issue.description+'</div>' if issue.description else ''}
      {'<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:7px;padding:10px 13px;font-size:12.5px;color:#1d4ed8">💡 '+issue.fix_suggestion+'</div>' if issue.fix_suggestion else ''}
    </div>
    {escalation_warning}
    <div style="text-align:center;margin-top:22px">
      <a href="http://127.0.0.1:8000" style="display:inline-block;background:#0d1b2a;color:#fff;padding:12px 28px;border-radius:9px;font-weight:700;font-size:14px;text-decoration:none">View Dashboard →</a>
    </div>
  </div>
  <div style="background:#f8fafc;padding:14px 28px;border-top:1px solid #e2e8f0;text-align:center">
    <p style="margin:0;font-size:11.5px;color:#94a3b8">88gravity Code Auditor · Follow-up {followup_num} of 3</p>
  </div>
</div>
</body>
</html>"""

    subject = f"[Code Auditor] Follow-up #{followup_num}: {issue.id} is {hours_overdue}h overdue"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"from": from_addr, "to": [issue.owner_email], "subject": subject, "html": html},
        )
        if not resp.is_success:
            logger.error(f"Resend follow-up failed: {resp.status_code} {resp.text}")


async def _send_slack(issue: IssueORM, hours_overdue: int, followup_num: int, settings=None) -> None:
    if settings is None: settings = get_settings()
    severity_emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(issue.severity, "⚪")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"⏰ Follow-up #{followup_num}: {issue.id}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Title:*\n{issue.title}"},
                {"type": "mrkdwn", "text": f"*Severity:*\n{severity_emoji} {issue.severity.upper()}"},
                {"type": "mrkdwn", "text": f"*File:*\n`{issue.file_path}`"},
                {"type": "mrkdwn", "text": f"*Owner:*\n{issue.owner_name}"},
                {"type": "mrkdwn", "text": f"*Overdue:*\n{hours_overdue}h"},
                {"type": "mrkdwn", "text": f"*Follow-up:*\n#{followup_num} of 3"},
            ],
        },
    ]
    if issue.jira_ticket_url:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Open Jira Ticket →"},
                "url": issue.jira_ticket_url,
                "style": "primary",
            }],
        })

    async with httpx.AsyncClient(timeout=5) as client:
        await client.post(
            settings.slack_webhook_url,
            json={"blocks": blocks, "text": f"Follow-up #{followup_num} for {issue.id}"},
        )