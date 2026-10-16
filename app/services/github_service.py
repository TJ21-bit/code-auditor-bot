import httpx
import base64
from typing import List, Optional

AUDITABLE_EXTENSIONS = {
    ".js", ".ts", ".jsx", ".tsx", ".py", ".php", ".java", ".go",
    ".rb", ".cs", ".cpp", ".c", ".swift", ".kt", ".rs", ".vue",
    ".sql", ".sh", ".bash", ".yaml", ".yml", ".env", ".htaccess",
    ".json", ".config",
}


def _headers() -> dict:
    """Build headers fresh each call so token changes are picked up."""
    from app.config import get_settings
    token = get_settings().github_token
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token and token not in ("ghp_...", "", "your_token_here"):
        h["Authorization"] = f"Bearer {token}"
    return h


async def get_repo_info(repo: str) -> dict:
    """Fetch basic repo metadata."""
    url = f"https://api.github.com/repos/{repo}"
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(url, headers=_headers())
        if not res.is_success:
            return {}
    return res.json()


async def get_repo_tree_all(repo: str, branch: str = "master") -> List[dict]:
    """Return ALL files for the file browser (auditable + non-auditable)."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{branch}?recursive=1"
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(url, headers=_headers())

        # If branch not found, try the repo's default branch
        if res.status_code == 404:
            info = await get_repo_info(repo)
            default = info.get("default_branch", "main")
            if default != branch:
                url2 = f"https://api.github.com/repos/{repo}/git/trees/{default}?recursive=1"
                res = await client.get(url2, headers=_headers())

        if res.status_code == 409:
            return []  # Empty repo

        res.raise_for_status()

    data = res.json()
    return [
        {"path": item["path"], "type": item["type"], "size": item.get("size", 0)}
        for item in data.get("tree", [])
        if item["type"] == "blob"
    ]


async def get_repo_tree(repo: str, branch: str = "master") -> List[dict]:
    """Return only auditable files (used by the audit engine)."""
    all_files = await get_repo_tree_all(repo, branch)
    return [f for f in all_files if _is_auditable(f["path"])]


async def get_file_content(repo: str, path: str, ref: str = "master") -> Optional[str]:
    """Fetch and decode a single file's content from GitHub."""
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    async with httpx.AsyncClient(timeout=20) as client:
        res = await client.get(url, headers=_headers())
        if res.status_code == 404:
            return None
        res.raise_for_status()
    data = res.json()
    content_b64 = data.get("content", "")
    return base64.b64decode(content_b64.replace("\n", "")).decode("utf-8", errors="replace")


async def get_file_last_committer(repo: str, path: str, branch: str = "master") -> Optional[str]:
    """Return the email of the last person to commit to this file."""
    url = f"https://api.github.com/repos/{repo}/commits?path={path}&sha={branch}&per_page=1"
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(url, headers=_headers())
        if not res.is_success:
            return None
    commits = res.json()
    if commits:
        return commits[0].get("commit", {}).get("author", {}).get("email")
    return None


async def list_branches(repo: str) -> List[str]:
    """Return list of branch names for a repo."""
    url = f"https://api.github.com/repos/{repo}/branches?per_page=100"
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(url, headers=_headers())
        if not res.is_success:
            return []
    return [b["name"] for b in res.json()]


def _is_auditable(path: str) -> bool:
    return any(path.endswith(ext) for ext in AUDITABLE_EXTENSIONS)


def detect_language(path: str) -> str:
    ext_map = {
        ".js": "javascript", ".ts": "typescript", ".jsx": "javascript",
        ".tsx": "typescript", ".py": "python", ".php": "php",
        ".java": "java", ".go": "go", ".rb": "ruby", ".cs": "csharp",
        ".cpp": "cpp", ".c": "c", ".swift": "swift", ".kt": "kotlin",
        ".rs": "rust", ".vue": "vue", ".sql": "sql", ".sh": "bash",
        ".bash": "bash", ".yaml": "yaml", ".yml": "yaml",
    }
    for ext, lang in ext_map.items():
        if path.endswith(ext):
            return lang
    return "code"