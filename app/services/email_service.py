import httpx
import logging
from typing import List

logger = logging.getLogger(__name__)


def _settings():
    from app.config import get_settings
    return get_settings()


async def send_developer_issues_email(name: str, email: str, issues: list) -> bool:
    """Send formatted HTML email via Resend API."""
    s = _settings()

    api_key  = getattr(s, 'resend_api_key', '') or ''
    from_addr = getattr(s, 'smtp_from', '') or 'onboarding@resend.dev'

    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping email")
        return False

    critical = [i for i in issues if i.severity == 'critical']
    warnings  = [i for i in issues if i.severity == 'warning']
    info      = [i for i in issues if i.severity == 'info']

    def badge(sev):
        colors = {'critical': '#dc2626', 'warning': '#d97706', 'info': '#2563eb'}
        return colors.get(sev, '#64748b')

    def issue_row(i):
        file = (i.file_path or '').split('/')[-1]
        bg   = {'critical': '#fef2f2', 'warning': '#fffbeb', 'info': '#eff6ff'}.get(i.severity, '#f8fafc')
        return f"""
        <tr style="background:{bg}">
          <td style="padding:11px 16px;border-bottom:1px solid #e2e8f0">
            <span style="display:inline-block;background:{badge(i.severity)};color:#fff;font-size:10px;
                         font-weight:700;padding:3px 8px;border-radius:99px;text-transform:uppercase;
                         letter-spacing:.5px">{i.severity}</span>
          </td>
          <td style="padding:11px 16px;border-bottom:1px solid #e2e8f0;font-weight:600;
                     color:#0f172a;font-size:13px">{i.title}</td>
          <td style="padding:11px 16px;border-bottom:1px solid #e2e8f0;font-family:monospace;
                     font-size:12px;color:#64748b">{file}</td>
          <td style="padding:11px 16px;border-bottom:1px solid #e2e8f0;font-size:12px;
                     color:#64748b;text-transform:capitalize">{i.status}</td>
        </tr>"""

    rows_html = ''.join(issue_row(i) for i in issues)

    sev_summary = ' '.join([
        f'<strong style="color:#dc2626">{len(critical)} critical</strong>' if critical else '',
        f'<strong style="color:#d97706">{len(warnings)} warning{"s" if len(warnings)!=1 else ""}</strong>' if warnings else '',
        f'<strong style="color:#2563eb">{len(info)} info</strong>' if info else '',
    ]).strip()

    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:'Inter',system-ui,sans-serif">
<div style="max-width:620px;margin:32px auto;background:#fff;border-radius:14px;
            overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.09)">

  <!-- Header -->
  <div style="background:#0d1b2a;padding:22px 28px;display:flex;align-items:center;gap:12px">
    <div style="background:linear-gradient(135deg,#c89b3c,#dbb455);width:36px;height:36px;
                border-radius:8px;display:flex;align-items:center;justify-content:center;
                font-weight:800;color:#0d1b2a;font-size:13px;flex-shrink:0">88</div>
    <div>
      <div style="color:#fff;font-weight:700;font-size:16px;letter-spacing:-.2px">Code Auditor</div>
      <div style="color:rgba(255,255,255,.4);font-size:11px;margin-top:1px">88gravity · internal tool</div>
    </div>
  </div>

  <!-- Body -->
  <div style="padding:28px 28px 0">
    <h2 style="margin:0 0 8px;font-size:22px;font-weight:800;color:#0f172a;letter-spacing:-.5px">
      Hi {name} 👋
    </h2>
    <p style="margin:0 0 22px;color:#475569;font-size:14px;line-height:1.6">
      You have <strong>{len(issues)} open code issue{"s" if len(issues)!=1 else ""}</strong>
      assigned to you: {sev_summary}.<br/>
      Please review and resolve them within <strong>48 hours</strong>.
    </p>

    <!-- Table -->
    <table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;
                  border-radius:10px;overflow:hidden;margin-bottom:24px">
      <thead>
        <tr style="background:#f8fafc">
          <th style="padding:9px 16px;text-align:left;font-size:10.5px;font-weight:700;
                     text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;
                     border-bottom:1px solid #e2e8f0">Severity</th>
          <th style="padding:9px 16px;text-align:left;font-size:10.5px;font-weight:700;
                     text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;
                     border-bottom:1px solid #e2e8f0">Issue</th>
          <th style="padding:9px 16px;text-align:left;font-size:10.5px;font-weight:700;
                     text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;
                     border-bottom:1px solid #e2e8f0">File</th>
          <th style="padding:9px 16px;text-align:left;font-size:10.5px;font-weight:700;
                     text-transform:uppercase;letter-spacing:.5px;color:#94a3b8;
                     border-bottom:1px solid #e2e8f0">Status</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>

    <!-- CTA -->
    <div style="text-align:center;margin-bottom:28px">
      <a href="http://127.0.0.1:8000"
         style="display:inline-block;background:#0d1b2a;color:#fff;padding:13px 32px;
                border-radius:10px;font-weight:700;font-size:14px;text-decoration:none;
                letter-spacing:-.2px">
        View Dashboard →
      </a>
    </div>
  </div>

  <!-- Footer -->
  <div style="background:#f8fafc;padding:16px 28px;border-top:1px solid #e2e8f0;
              text-align:center">
    <p style="margin:0;font-size:12px;color:#94a3b8">
      88gravity Code Auditor · All issues must be resolved within 48 hours of assignment.<br/>
      Do not share this email externally.
    </p>
  </div>
</div>
</body>
</html>"""

    subject = f"[Code Auditor] {len(issues)} issue{'s' if len(issues)!=1 else ''} assigned to you — 88gravity"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from":    from_addr,
                    "to":      [email],
                    "subject": subject,
                    "html":    html,
                },
            )
            if resp.is_success:
                logger.info(f"Email sent to {email} via Resend ({len(issues)} issues)")
                return True
            else:
                logger.error(f"Resend failed for {email}: {resp.status_code} {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Email request failed for {email}: {e}")
        return False