import os, re, json, subprocess, pathlib,venv
from typing import List, Dict, Any, Tuple

HERE = pathlib.Path(__file__).resolve().parent
ART = HERE / "artifacts"
ART.mkdir(exist_ok=True)

def run(cmd: List[str], cwd=None, env=None, timeout=None) -> Tuple[int, str, str]:
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return 124, out, err
    return p.returncode, out, err

def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", s)[:200]

def detect_libs(nb_json: Dict[str, Any]) -> List[str]:
    libs = set()
    pats = {
        "sklearn": r"\bfrom\s+sklearn\b|\bimport\s+sklearn\b",
        "tensorflow": r"\bimport\s+tensorflow\b|\bfrom\s+tensorflow\b",
        "torch": r"\bimport\s+torch\b|\bfrom\s+torch\b",
        "xgboost": r"\bimport\s+xgboost\b",
        "lightgbm": r"\bimport\s+lightgbm\b",
        "transformers": r"\bfrom\s+transformers\b|\bimport\s+transformers\b",
        "catboost": r"\bimport\s+catboost\b",
        "statsmodels": r"\bimport\s+statsmodels\b",
        "pandas": r"\bimport\s+pandas\b|\bfrom\s+pandas\b",
        "matplotlib": r"\bimport\s+matplotlib\b|\bfrom\s+matplotlib\b",
        "seaborn": r"\bimport\s+seaborn\b",
    }
    for cell in nb_json.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        for name, pat in pats.items():
            if re.search(pat, src):
                libs.add(name)
    return sorted(libs)

REL_PATH_PAT = re.compile(r"""
    (?:read_csv|to_csv|read_excel|read_parquet|read_json|read_table|open|np\.load|np\.save|
       torch\.load|joblib\.load|pickle\.load|Image\.open|imread|savetxt|loadtxt|
       pd\.read_.*|with\s+open)
    \s*\(\s*['"]([^'"]+)['"]
""", re.X)

def find_relative_paths(nb_json):
    hits = []
    for cell in nb_json.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        for m in REL_PATH_PAT.finditer(src):
            p = m.group(1)
            if p.startswith(("http://", "https://", "s3://")):
                continue
            hits.append(p)
    return hits

def clone_repo(repo_full_name: str, dest: pathlib.Path):
    url = f"https://github.com/{repo_full_name}.git"
    rc, out, err = run(["git", "clone", "--depth", "1", url, str(dest)])
    if rc != 0:
        raise RuntimeError(f"git clone failed: {err or out}")

def ensure_repo_env(repo_url: str, repo_dir: pathlib.Path, extra_pkgs=None, base_deps=None) -> pathlib.Path:
    extra_pkgs = extra_pkgs or []
    base_deps = base_deps or ["numpy", "pandas", "matplotlib", "scikit-learn"]

    venv_dir = repo_dir / ".venv"
    if not venv_dir.exists():
        venv.EnvBuilder(with_pip=True).create(str(venv_dir))

    if os.name == "nt":
        py = venv_dir / "Scripts" / "python.exe"
        pip = venv_dir / "Scripts" / "pip.exe"
    else:
        py = venv_dir / "bin" / "python"
        pip = venv_dir / "bin" / "pip"

    run([str(pip), "install", "--upgrade", "pip", "setuptools", "wheel"])

    if base_deps:
        run([str(pip), "install", *base_deps])

    req = repo_dir / "requirements.txt"
    if req.exists():
        run([str(pip), "install", "-r", str(req)])

    if extra_pkgs:
        run([str(pip), "install", *extra_pkgs])

    return py
