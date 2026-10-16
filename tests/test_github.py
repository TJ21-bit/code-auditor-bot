import pytest
from unittest.mock import patch, AsyncMock
from app.services.github_service import (
    get_repo_tree, get_file_content, detect_language, _is_auditable
)


def test_is_auditable():
    assert _is_auditable("app/main.py")     is True
    assert _is_auditable("src/auth.js")     is True
    assert _is_auditable("logo.png")        is False
    assert _is_auditable("README.md")       is False
    assert _is_auditable("db/schema.sql")   is True
    assert _is_auditable("app.ts")          is True


def test_detect_language():
    assert detect_language("app/main.py")   == "python"
    assert detect_language("src/auth.js")   == "javascript"
    assert detect_language("api/users.ts")  == "typescript"
    assert detect_language("login.php")     == "php"
    assert detect_language("schema.sql")    == "sql"
    assert detect_language("unknown.xyz")   == "code"


@pytest.mark.asyncio
async def test_get_repo_tree_filters_non_auditable():
    raw_tree = [
        {"path": "src/app.js",    "type": "blob"},
        {"path": "assets/logo.png", "type": "blob"},
        {"path": "src/",          "type": "tree"},
        {"path": "lib/utils.py",  "type": "blob"},
    ]
    mock_response = AsyncMock()
    mock_response.json.return_value = {"tree": raw_tree}
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        result = await get_repo_tree("owner/repo", "main")

    paths = [r["path"] for r in result]
    assert "src/app.js"    in paths
    assert "lib/utils.py"  in paths
    assert "assets/logo.png" not in paths
    assert "src/"          not in paths


@pytest.mark.asyncio
async def test_get_file_content_decodes_base64():
    import base64
    code = "def hello():\n    return 'world'\n"
    encoded = base64.b64encode(code.encode()).decode()

    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"content": encoded}
    mock_response.raise_for_status = lambda: None

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        result = await get_file_content("owner/repo", "app/main.py")

    assert result == code


@pytest.mark.asyncio
async def test_get_file_content_returns_none_on_404():
    mock_response = AsyncMock()
    mock_response.status_code = 404

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_response)
        result = await get_file_content("owner/repo", "missing.py")

    assert result is None
