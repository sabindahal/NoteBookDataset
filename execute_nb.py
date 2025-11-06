import sys, time, pathlib, re
from typing import Dict, Any, List, Tuple, Optional
from utils import run, slug, ART

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE / "work"; WORK.mkdir(exist_ok=True)
RUNS = HERE / "artifacts" / "nb_runs"; RUNS.mkdir(parents=True, exist_ok=True)

BASE_DEPS = ["numpy","pandas","matplotlib","scikit-learn"]

def infer_installs(nb_path: str) -> List[str]:
    txt = pathlib.Path(nb_path).read_text(errors="ignore")
    pkgs = set()
    for pat, name in [
        (r"\bimport\s+torch\b", "torch"),
        (r"\bimport\s+tensorflow\b", "tensorflow"),
        (r"\bimport\s+xgboost\b", "xgboost"),
        (r"\bimport\s+lightgbm\b", "lightgbm"),
        (r"\bfrom\s+transformers\b|\bimport\s+transformers\b", "transformers"),
        (r"\bimport\s+seaborn\b", "seaborn"),
        (r"\bimport\s+statsmodels\b", "statsmodels"),
    ]:
        if re.search(pat, txt): pkgs.add(name)
    return sorted(pkgs)

def execute_notebook(nb_path: str, out_path: str, allow_installs: bool, per_notebook_seconds: int,
                     python_exe: Optional[str] = None) -> Dict[str, Any]:
    log_path = RUNS / (slug(nb_path) + ".log")
    started = time.time()
    status, err_type, err_msg = "unknown", "", ""
    try:
        py = python_exe or sys.executable
        cmd = [
            str(py), "-m", "papermill", nb_path, out_path,
            "--cwd", str(pathlib.Path(nb_path).parent.resolve()),
            "--request-save-on-cell-execute",
            "--log-output",
            "--kernel", "python3",
        ]
        rc, out, err = run(cmd, timeout=per_notebook_seconds)
        log_path.write_text((out or "") + "\n---ERR---\n" + (err or ""))
        status = "ok" if rc == 0 else ("timeout" if rc == 124 else "error")
        if rc != 0:
            err_type = "Timeout" if rc == 124 else "ExecutionError"
            err_msg = (err or out)[-1200:] if (err or out) else ""
    except Exception as e:
        status, err_type, err_msg = "error", e.__class__.__name__, str(e)[:1200]
    finally:
        dur = int(time.time() - started)
    return dict(runtime_seconds=dur, status=status, error_type=err_type, error_message=err_msg, log_path=str(log_path))
