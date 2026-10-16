import json
import httpx
from typing import Dict, Any


SYSTEM_PROMPT = """You are a senior code security and quality auditor with 15 years experience.
Audit the provided code thoroughly. Focus on:
  - Security vulnerabilities (SQLi, XSS, CSRF, SSRF, path traversal, hardcoded secrets, etc.)
  - Performance bottlenecks (N+1 queries, missing indexes, blocking calls, memory leaks)
  - Code quality (dead code, code smells, duplication, poor naming)
  - Logic errors (off-by-one, null handling, race conditions)
  - Error handling (missing try/catch, swallowed exceptions, no logging)
  - Best practices (missing validation, no rate limiting, exposed stack traces)

Return ONLY valid JSON — no markdown fences, no explanation text."""

ISSUE_SCHEMA = """{
  "score": <integer 0-100, 100 = perfect code>,
  "summary": "<one-sentence overall assessment>",
  "issues": [
    {
      "title": "<short, specific title>",
      "severity": "<critical|warning|info>",
      "category": "<Security|Performance|Quality|Logic|Error Handling|Best Practice|Dependency>",
      "line": "<line number, range like 12-18, or null>",
      "description": "<clear explanation of the problem and its impact>",
      "fix": "<specific, actionable fix with code snippet if useful>"
    }
  ]
}"""


async def audit_code(file_path: str, language: str, code: str) -> Dict[str, Any]:
    """
    Send code to Claude API for security and quality audit.
    Uses httpx directly (fully async, no SDK caching issues).
    Returns parsed dict: { score, summary, issues[] }
    """
    from app.config import get_settings
    settings = get_settings()
    api_key = settings.anthropic_api_key

    if not api_key or api_key in ("sk-ant-...", "", "your_key_here"):
        return {
            "score": 50,
            "summary": "Anthropic API key not configured.",
            "issues": [],
        }

    truncated = code[:6000]
    truncation_note = "\n\n[... file truncated ...]" if len(code) > 6000 else ""

    prompt = f"""Audit this {language} file: `{file_path}`

Return JSON matching exactly this schema:
{ISSUE_SCHEMA}

Code to audit:
```{language}
{truncated}{truncation_note}
```"""

    payload = {
        "model": "claude-opus-4-5",
        "max_tokens": 2000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        import logging
        logging.getLogger(__name__).error(f"Anthropic API error {e.response.status_code}: {e.response.text}")
        return {"score": 50, "summary": f"API error: {e.response.status_code}", "issues": []}
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Anthropic request failed: {e}")
        return {"score": 50, "summary": f"Request failed: {e}", "issues": []}

    raw = data.get("content", [{}])[0].get("text", "").strip()

    # Strip accidental markdown fences
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                raw = part
                break

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import logging
        logging.getLogger(__name__).error(f"Failed to parse AI response: {raw[:200]}")
        return {
            "score": 50,
            "summary": "Audit completed but response could not be parsed.",
            "issues": [],
        }