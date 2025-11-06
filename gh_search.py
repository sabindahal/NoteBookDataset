import os, requests, pathlib
from typing import List, Dict, Any
from urllib.parse import quote_plus

HERE = pathlib.Path(__file__).resolve().parent
ART = HERE / "artifacts"
ART.mkdir(exist_ok=True)

GH = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

def _headers():
    h = {"Accept": "application/vnd.github+json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h

def search_repos(query: str, max_repos: int = 50) -> List[Dict[str, Any]]:
    out = []
    page, per_page = 1, 30
    while len(out) < max_repos:
        q = quote_plus(query)
        url = f"{GH}/search/repositories?q={q}&sort=stars&order=desc&per_page={per_page}&page={page}"
        r = requests.get(url, headers=_headers(), timeout=60); r.raise_for_status()
        items = r.json().get("items", [])
        if not items: break
        out.extend(items)
        if len(items) < per_page: break
        page += 1
    return out[:max_repos]

def list_ipynb_in_repo(full_name: str, max_files: int = 5) -> List[Dict[str, Any]]:
    r = requests.get(f"{GH}/repos/{full_name}", headers=_headers(), timeout=60); r.raise_for_status()
    repo = r.json(); branch = repo["default_branch"]
    r = requests.get(f"{GH}/repos/{full_name}/git/trees/{branch}?recursive=1", headers=_headers(), timeout=60); r.raise_for_status()
    tree = r.json().get("tree", [])
    nbs = [t for t in tree if t.get("path","").endswith(".ipynb") and t.get("type")=="blob"]
    nbs = [t for t in nbs if t.get("size", 0) <= 2_500_000]  # ~2.5MB cap
    return nbs[:max_files]
