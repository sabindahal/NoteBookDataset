import os, csv, sys, json, shutil, pathlib, argparse
from typing import Dict, Any, List
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module="nbformat")

from gh_search import search_repos, list_ipynb_in_repo
from triage import triage_notebook
from execute_nb import execute_notebook, infer_installs
from utils import ART, slug
from envs import ensure_repo_env, prune_envs

HERE = pathlib.Path(__file__).resolve().parent
WORK = HERE / "work"; WORK.mkdir(exist_ok=True)
DATASET_CSV = HERE / "notebook_dataset.csv"
RUNS = HERE / "artifacts" / "nb_runs"; RUNS.mkdir(parents=True, exist_ok=True)


def clone_repo(full_name: str, dest: pathlib.Path):
    import git
    return git.Repo.clone_from(f"https://github.com/{full_name}.git", dest, depth=1)


def ensure_repo_checked_out(full_name: str, dest: pathlib.Path):
    if dest.exists():
        if (dest / ".git").exists() and any(dest.iterdir()):
            print(f"✅ Using existing repo: {dest}")
            return
        else:
            print(f"🌀 Found folder without .git; refreshing: {dest}")
            shutil.rmtree(dest)
    print(f"⬇️ Cloning https://github.com/{full_name}.git into {dest}")
    clone_repo(full_name, dest)


def _append_candidates(new_items: List[Dict[str, Any]]):
    out_json = HERE / "artifacts" / "candidates.json"
    existing = []
    if out_json.exists():
        try:
            existing = json.loads(out_json.read_text())
        except Exception:
            existing = []
    merged = existing + new_items
    out_json.write_text(json.dumps(merged, indent=2))
    print(f"Appended {len(new_items)} candidates; total {len(merged)} now at {out_json}")


def do_search(args):
    repos = search_repos(args.query, max_repos=args.max_repos)
    candidates = []
    for r in repos:
        nbs = list_ipynb_in_repo(r["full_name"], max_files=args.max_nbs_per_repo)
        for nb in nbs:
            candidates.append({
                "repo_full_name": r["full_name"],
                "repo_html_url": r["html_url"],
                "repo_stars": r.get("stargazers_count", 0),
                "repo_pushed_at": r.get("pushed_at", ""),
                "notebook_path": nb["path"],
                "notebook_url": f'{r["html_url"]}/blob/{r.get("default_branch", "master")}/{nb["path"]}',
                "size_kb": int(nb.get("size", 0) / 1024),
            })
    _append_candidates(candidates)


def do_triage(args):
    cand_path = HERE / "artifacts" / "candidates.json"
    if not cand_path.exists():
        print("No candidates.json. Run `search` first.", file=sys.stderr); sys.exit(1)
    cands = json.loads(cand_path.read_text())

    # Prepare writer
    fieldnames = [
        "repo_url","repo_stars","repo_pushed_at","notebook_path","notebook_url",
        "size_kb","n_cells","libs_detected","has_relative_data_paths","missing_paths",
        "suspect_cuda","has_heavy_libs","keep_candidate","runtime_seconds",
        "status","error_type","error_message"
    ]
    out_rows: List[Dict[str, Any]] = []

    for c in cands:
        repo_full = c["repo_full_name"]
        repo_url = c["repo_html_url"]
        repo_dir = WORK / slug(repo_full)

        try:
            ensure_repo_checked_out(repo_full, repo_dir)
        except Exception as e:
            out_rows.append({
                "repo_url": repo_url,
                "repo_stars": c.get("repo_stars",""),
                "repo_pushed_at": c.get("repo_pushed_at",""),
                "notebook_path": c.get("notebook_path",""),
                "notebook_url": c.get("notebook_url",""),
                "size_kb": 0,
                "n_cells": 0,
                "libs_detected": "",
                "has_relative_data_paths": False,
                "missing_paths": "",
                "suspect_cuda": False,
                "has_heavy_libs": False,
                "keep_candidate": False,
                "runtime_seconds": "",
                "status": "error",
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
            })
            print(f"⚠️ Repo clone/checkout failed, skipping {repo_url}: {e}")
            continue

        nb_rel = c["notebook_path"]
        nb_abs = (repo_dir / nb_rel).resolve()
        if not nb_abs.exists():
            out_rows.append({
                "repo_url": repo_url,
                "repo_stars": c.get("repo_stars",""),
                "repo_pushed_at": c.get("repo_pushed_at",""),
                "notebook_path": nb_rel,
                "notebook_url": c.get("notebook_url",""),
                "size_kb": c.get("size_kb", 0),
                "n_cells": 0,
                "libs_detected": "",
                "has_relative_data_paths": False,
                "missing_paths": "",
                "suspect_cuda": False,
                "has_heavy_libs": False,
                "keep_candidate": False,
                "runtime_seconds": "",
                "status": "skip_missing",
                "error_type": "",
                "error_message": "",
            })
            continue

        tri = triage_notebook(str(nb_abs), str(repo_dir))
        row = dict(
            repo_url=repo_url,
            repo_stars=c.get("repo_stars",""),
            repo_pushed_at=c.get("repo_pushed_at",""),
            notebook_path=nb_rel,
            notebook_url=c.get("notebook_url",""),
            size_kb=tri.get("size_kb", c.get("size_kb", 0)),
            n_cells=tri.get("n_cells", 0),
            libs_detected=tri.get("libs_detected",""),
            has_relative_data_paths=tri.get("has_relative_data_paths", False),
            missing_paths=tri.get("missing_paths",""),
            suspect_cuda=tri.get("suspect_cuda", False),
            has_heavy_libs=tri.get("has_heavy_libs", False),
            keep_candidate=tri.get("keep_candidate", False),
            runtime_seconds="",
            status=tri.get("status","ok") if tri.get("status") in {"ok","invalid","bad_json","skip_missing","skip_empty","skip_lfs_pointer","skip_html_notebook"} else "triaged",
            error_type=tri.get("error_type",""),
            error_message=tri.get("error_message",""),
        )
        out_rows.append(row)

    with open(DATASET_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})
    print(f"Wrote {DATASET_CSV} with {len(out_rows)} triaged entries.")


def do_run(args):
    if not DATASET_CSV.exists():
        print("No notebook_dataset.csv. Run `triage` first.", file=sys.stderr); sys.exit(1)
    import pandas as pd
    df = pd.read_csv(DATASET_CSV)

    df = df[(df["keep_candidate"] == True)]
    df = df[(~df["has_relative_data_paths"]) | (df["missing_paths"].astype(str)=="")]

    total_budget = int(args.max_total_seconds)
    per_nb = int(args.per_notebook_seconds)
    spent = 0

    out_rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        if spent + per_nb > total_budget:
            break

        repo_full_from_url = row["repo_url"].split("github.com/")[-1].strip("/")
        repo_dir = WORK / slug(repo_full_from_url)

        try:
            ensure_repo_checked_out(repo_full_from_url, repo_dir)
        except Exception as e:
            row["runtime_seconds"] = 0
            row["status"] = "error"
            row["error_type"] = type(e).__name__
            row["error_message"] = str(e)[:500]
            out_rows.append(row.to_dict())
            print(f"⚠️ Repo checkout failed in run: {row['repo_url']} :: {e}")
            continue

        nb_abs = (repo_dir / row["notebook_path"]).resolve()
        if not nb_abs.exists():
            row["runtime_seconds"] = 0
            row["status"] = "skip_missing"
            row["error_type"] = ""
            row["error_message"] = ""
            out_rows.append(row.to_dict())
            continue

        try:
            extra = infer_installs(str(nb_abs))
        except Exception:
            extra = []

        try:
            py_in_env = ensure_repo_env(row["repo_url"], repo_dir, extra_pkgs=extra)
            out_nb = RUNS / (slug(row["repo_url"]) + "_" + slug(row["notebook_path"]) + ".ipynb")
            res = execute_notebook(
                str(nb_abs), str(out_nb),
                allow_installs=False,
                per_notebook_seconds=per_nb,
                python_exe=str(py_in_env)
            )
            spent += min(per_nb, int(res.get("runtime_seconds", 0)))
            row["runtime_seconds"] = res.get("runtime_seconds", 0)
            row["status"] = res.get("status", "error")
            row["error_type"] = res.get("error_type", "")
            row["error_message"] = res.get("error_message", "")
        except Exception as e:
            row["runtime_seconds"] = 0
            row["status"] = "error"
            row["error_type"] = type(e).__name__
            row["error_message"] = str(e)[:500]

        out_rows.append(row.to_dict())

    import pandas as pd
    if out_rows:
        pd.DataFrame(out_rows).to_csv(DATASET_CSV, index=False)
        print(f"Updated {DATASET_CSV} with execution results for {len(out_rows)} notebooks.")
    else:
        print("No notebooks executed under current filters/budget.")


def do_envclean(args):
    prune_envs(older_than_days=int(args.days))
    print("Env prune complete.")


def main():
    ap = argparse.ArgumentParser(description="Build a dataset of runnable ML notebooks from GitHub (per-repo venv).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="Search GitHub for candidate repos + notebooks (appends)")
    s.add_argument("--query", required=True, help="GitHub repository search query")
    s.add_argument("--max-repos", type=int, default=50)
    s.add_argument("--max-nbs-per-repo", type=int, default=3)
    s.set_defaults(func=do_search)

    t = sub.add_parser("triage", help="Clone and triage candidates for data deps & simplicity")
    t.set_defaults(func=do_triage)

    r = sub.add_parser("run", help="Execute triaged notebooks under a time budget (per-repo venv)")
    r.add_argument("--per-notebook-seconds", type=int, default=480)
    r.add_argument("--max-total-seconds", type=int, default=3600)
    r.set_defaults(func=do_run)

    c = sub.add_parser("envclean", help="Remove cached per-repo envs older than N days (default 14)")
    c.add_argument("--days", type=int, default=14)
    c.set_defaults(func=do_envclean)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
