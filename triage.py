import os, json, pathlib, re, warnings
from typing import Dict, Any, Tuple, List

warnings.filterwarnings("ignore", category=UserWarning, module="nbformat")

import nbformat
from nbformat.reader import NotJSONError
try:
    from jsonschema.exceptions import ValidationError
except Exception:  # fallback if jsonschema import path differs
    class ValidationError(Exception): ...
from utils import detect_libs, find_relative_paths

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE / "work"; WORK.mkdir(exist_ok=True)
ART = HERE / "artifacts"; ART.mkdir(exist_ok=True)

HEAVY_LIBS = {"torch", "tensorflow", "transformers"}
CUDA_PAT = re.compile(r"\b(cuda|torch\.cuda|device\s*=\s*['\"]cuda)", re.I)


def _safe_read_nb_from_text(raw: str) -> Tuple[Any, str]:
    try:
        nb = nbformat.reads(raw, as_version=4)
        return nb, None
    except (ValidationError, NotJSONError, json.JSONDecodeError, KeyError) as e:
        return None, f"{type(e).__name__}: {e}"


def _concat_code_from_cells(nb) -> str:
    parts: List[str] = []
    for c in getattr(nb, "cells", []):
        if isinstance(c, dict):
            if c.get("cell_type") == "code":
                src = c.get("source", "")
                parts.append(src if isinstance(src, str) else "".join(src))
        else:
            if getattr(c, "cell_type", "") == "code":
                src = getattr(c, "source", "")
                parts.append(src if isinstance(src, str) else "".join(src))
    return "\n".join(parts)


def triage_notebook(nb_path: str, repo_root: str) -> Dict[str, Any]:
    """
    Robust triage: never raises. Returns a dict with consistent keys.
    """
    p = pathlib.Path(nb_path)
    repo_root = pathlib.Path(repo_root).resolve()

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
        error_type="",
        error_message="",
        sample="",
    )

    if (not p.exists()) or (not p.is_file()):
        result["status"] = "skip_missing"
        return result

    size = p.stat().st_size
    result["size_kb"] = max(0, int(size / 1024))
    if size == 0:
        result["status"] = "skip_empty"
        return result

    raw = p.read_text(encoding="utf-8", errors="ignore")
    head = raw.lstrip()[:200]
    result["sample"] = head

    if head.startswith("version https://git-lfs.github.com/spec/v1"):
        result["status"] = "skip_lfs_pointer"
        return result

    if head.lower().startswith("<html") or head.lower().startswith("<!doctype html"):
        result["status"] = "skip_html_notebook"
        return result

    nb, load_err = _safe_read_nb_from_text(raw)
    if nb is None:
        result.update(
            status="invalid",
            error_type="InvalidNotebook",
            error_message=(load_err or "Invalid ipynb (missing metadata)")[:500],
        )
        return result

    try:
        libs = detect_libs(nb)
    except Exception as e:
        libs = []
        result["error_type"] = result["error_type"] or type(e).__name__
        result["error_message"] = (result["error_message"] or str(e))[:500]

    try:
        rels = find_relative_paths(nb)
    except Exception as e:
        rels = []
        result["error_type"] = result["error_type"] or type(e).__name__
        result["error_message"] = (result["error_message"] or str(e))[:500]

    missing = []
    for rp in rels:
        try:
            cand = (repo_root / rp).resolve()

            if not str(cand).startswith(str(repo_root)) or not cand.exists():
                missing.append(rp)
        except Exception:
            missing.append(rp)

    src_all = _concat_code_from_cells(nb)
    suspect_cuda = bool(CUDA_PAT.search(src_all))

    has_heavy_libs = bool(set(libs) & HEAVY_LIBS)

    try:
        n_code_cells = sum(
            1 for c in getattr(nb, "cells", [])
            if (isinstance(c, dict) and c.get("cell_type") == "code") or
               (hasattr(c, "cell_type") and getattr(c, "cell_type") == "code")
        )
    except Exception:
        n_code_cells = 0

    keep_candidate = (
        (result["size_kb"] <= 500) and
        (n_code_cells <= 60) and
        (not suspect_cuda) and
        (not has_heavy_libs)
    )

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
