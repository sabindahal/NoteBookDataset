import os, sys, subprocess, shutil, pathlib, hashlib, time
from typing import Optional, List

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE / "work"; WORK.mkdir(exist_ok=True)
ENVS = WORK / "envs"; ENVS.mkdir(parents=True, exist_ok=True)

def _run(cmd, cwd=None, timeout=None):
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill(); out, err = p.communicate()
        return 124, out, err
    return p.returncode, out, err

def _slug(s: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-+" else "-" for ch in s)[:200]

def _hash_text(txt: str) -> str:
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16]

def _reqs_fingerprint(repo_dir: pathlib.Path) -> str:
    parts = []
    for fn in ("requirements.txt", "pyproject.toml", "setup.cfg", "environment.yml", ".python-version", "runtime.txt"):
        p = repo_dir / fn
        if p.exists():
            try:
                parts.append(fn + ":" + p.read_text(errors="ignore"))
            except Exception:
                pass
    return _hash_text("\n---\n".join(parts)) if parts else "no-reqs"

def _venv_python(env_dir: pathlib.Path) -> pathlib.Path:
    if os.name == "nt":
        return env_dir / "Scripts" / "python.exe"
    return env_dir / "bin" / "python"

def ensure_repo_env(repo_url: str, repo_dir: pathlib.Path,
                    extra_pkgs: Optional[List[str]] = None,
                    base_pkgs: Optional[List[str]] = None) -> pathlib.Path:
    extra_pkgs = extra_pkgs or []
    base_pkgs = base_pkgs or ["pip", "wheel", "setuptools","numpy", "pandas", "matplotlib", "scikit-learn","papermill", "nbclient", "ipykernel", "jupyter"]

    fp = _reqs_fingerprint(repo_dir)
    key = _slug(repo_url.split("github.com/")[-1]) + "-" + fp
    env_dir = ENVS / key
    py = _venv_python(env_dir)

    if not py.exists():
        if env_dir.exists(): shutil.rmtree(env_dir, ignore_errors=True)
        rc, out, err = _run([sys.executable, "-m", "venv", str(env_dir)])
        if rc != 0: raise RuntimeError(f"venv create failed: {err or out}")
        rc, out, err = _run([str(py), "-m", "pip", "install", "--upgrade"] + base_pkgs, timeout=1200)
        if rc != 0: raise RuntimeError(f"pip base install failed: {err or out}")

        req = repo_dir / "requirements.txt"
        if req.exists():
            rc, out, err = _run([str(py), "-m", "pip", "install", "-r", str(req)], timeout=1800)
            if rc != 0:
                print(f"[WARN] requirements.txt install had issues for {repo_url}: {err or out}")

        if extra_pkgs:
            rc, out, err = _run([str(py), "-m", "pip", "install"] + extra_pkgs, timeout=900)
            if rc != 0:
                print(f"[WARN] extra packages failed for {repo_url}: {err or out}")

        kern_name = f"nb-{key}"
        _run([str(py), "-m", "ipykernel", "install", "--user", "--name", kern_name], timeout=300)

    (env_dir / ".last_used").write_text(str(int(time.time())))
    return py

def prune_envs(older_than_days: int = 14):
    cutoff = time.time() - older_than_days * 86400
    for d in ENVS.glob("*"):
        if not d.is_dir(): continue
        stamp = d / ".last_used"
        try:
            t = int(stamp.read_text())
        except Exception:
            t = d.stat().st_mtime
        if t < cutoff:
            shutil.rmtree(d, ignore_errors=True)

