import nbformat, pathlib, re
from nbformat.reader import NotJSONError
from typing import Dict, Any
from utils import detect_libs, find_relative_paths

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE / "work"; WORK.mkdir(exist_ok=True)
ART = HERE / "artifacts"; ART.mkdir(exist_ok=True)

HEAVY_LIBS = {"torch","tensorflow","transformers"}
CUDA_PAT = re.compile(r"\b(cuda|torch\.cuda|device\s*=\s*['\"]cuda)", re.I)

def triage_notebook(nb_path: str, repo_root: str) -> Dict[str, Any]:
    p = pathlib.Path(nb_path)
    repo_root = pathlib.Path(repo_root).resolve()

    # Default result schema (consistent columns even on skips/errors)
    result: Dict[str, Any] = dict(
        status="unknown",
        size_kb=0,
        n_cells=0,
        libs_detected="",
        has_relative_data_paths=False,
        missing_paths="",
        suspect_cuda=False,
        has_heavy_libs=False,
        keep_candidate=False,
        path=str(p),
        repo_root=str(repo_root),
    )

    # --- basic file checks ---
    if (not p.exists()) or (not p.is_file()):
        result["status"] = "skip_missing"
        return result

    size = p.stat().st_size
    result["size_kb"] = int(size / 1024)
    if size == 0:
        result["status"] = "skip_empty"
        return result

    # --- read safely (detect LFS/HTML/garbage) ---
    raw = p.read_text(encoding="utf-8", errors="ignore")
    head = raw.lstrip()[:200]

    if head.startswith("version https://git-lfs.github.com/spec/v1"):
        result["status"] = "skip_lfs_pointer"
        return result

    if head.startswith("<html") or head.startswith("<!DOCTYPE html"):
        result["status"] = "skip_html_notebook"
        return result

    # --- parse notebook JSON ---
    try:
        nb = nbformat.reads(raw, as_version=4)
    except NotJSONError as e:
        result["status"] = "bad_json"
        result["error"] = str(e)
        result["sample"] = head
        return result

    # --- original triage logic (only if parsed ok) ---
    libs = detect_libs(nb)
    rels = find_relative_paths(nb)

    # Check missing relative/absolute paths within repo
    missing = []
    for rp in rels:
        cand = (repo_root / rp).resolve()
        # must stay inside repo and exist
        if not str(cand).startswith(str(repo_root)) or not cand.exists():
            missing.append(rp)

    # Concatenate code to scan CUDA hints
    src_all_parts = []
    for c in nb.cells:
        if getattr(c, "cell_type", "") == "code":
            src_all_parts.append("".join(c.get("source", [])))
    src_all = "\n".join(src_all_parts)
    suspect_cuda = bool(CUDA_PAT.search(src_all))

    has_heavy_libs = bool(set(libs) & HEAVY_LIBS)
    n_code_cells = sum(1 for c in nb.cells if getattr(c, "cell_type", "") == "code")

    # Small/simple heuristics
    keep_candidate = (
        (result["size_kb"] <= 500) and
        (n_code_cells <= 60) and
        (not suspect_cuda) and
        (not has_heavy_libs)
    )

    # Populate result
    result.update(
        status="ok",
        n_cells=n_code_cells,
        libs_detected=";".join(libs),
        has_relative_data_paths=bool(rels),
        missing_paths=";".join(sorted(set(missing))) if missing else "",
        suspect_cuda=suspect_cuda,
        has_heavy_libs=has_heavy_libs,
        keep_candidate=keep_candidate,
    )
    return result
