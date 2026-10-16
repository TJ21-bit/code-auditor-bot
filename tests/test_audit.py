import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from app.main import app
from app.db.database import init_db


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_trigger_audit_returns_job_id():
    mock_tree    = [{"path": "app/main.py", "type": "blob"}]
    mock_content = "def hello():\n    pass\n"
    mock_result  = {"score": 90, "summary": "Clean", "issues": []}

    with patch("app.api.audit.get_repo_tree", AsyncMock(return_value=mock_tree)), \
         patch("app.api.audit.get_file_content", AsyncMock(return_value=mock_content)), \
         patch("app.api.audit.audit_code", AsyncMock(return_value=mock_result)):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/audit/", json={
                "repo": "88gravity/test",
                "branch": "main",
                "park_to_jira": False,
                "park_to_sheet": False,
            })

    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert data["repo"] == "88gravity/test"


@pytest.mark.asyncio
async def test_audit_raises_issues():
    mock_tree    = [{"path": "auth/login.js", "type": "blob"}]
    mock_content = "db.query('SELECT * FROM users WHERE id=' + userId);"
    mock_result  = {
        "score": 20,
        "summary": "SQL injection detected",
        "issues": [{
            "title": "SQL Injection",
            "severity": "critical",
            "category": "Security",
            "line": "1",
            "description": "User input directly interpolated into SQL.",
            "fix": "Use parameterised queries.",
        }],
    }

    with patch("app.api.audit.get_repo_tree", AsyncMock(return_value=mock_tree)), \
         patch("app.api.audit.get_file_content", AsyncMock(return_value=mock_content)), \
         patch("app.api.audit.audit_code", AsyncMock(return_value=mock_result)), \
         patch("app.api.audit.create_ticket", AsyncMock(return_value=("DEV-1", "http://jira/DEV-1"))), \
         patch("app.api.audit.park_issue", return_value=2):

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.post("/audit/", json={
                "repo": "88gravity/test",
                "branch": "main",
                "park_to_jira": False,
                "park_to_sheet": False,
            })

    assert r.status_code == 200


@pytest.mark.asyncio
async def test_list_issues_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/issues/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_issue_stats():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/issues/stats")
    assert r.status_code == 200
    data = r.json()
    assert "total" in data
    assert "critical" in data


@pytest.mark.asyncio
async def test_get_nonexistent_issue():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/issues/ISS-9999")
    assert r.status_code == 404
