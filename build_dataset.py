import os, csv, sys, json, shutil, pathlib, argparse
from typing import Dict, Any
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

def _append_candidates(new_items):
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
                "notebook_url": f'{r["html_url"]}/blob/{r["default_branch"]}/{nb["path"]}',
                "size_kb": int(nb.get("size", 0) / 1024),
            })
    _append_candidates(candidates)

def do_triage(args):
    cand_path = HERE / "artifacts" / "candidates.json"
    if not cand_path.exists():
        print("No candidates.json. Run `search` first.", file=sys.stderr); sys.exit(1)
    cands = json.loads(cand_path.read_text())

    rows = []
    for c in cands:
        repo_dir = WORK / slug(c["repo_full_name"])
        if repo_dir.exists(): shutil.rmtree(repo_dir)
        clone_repo(c["repo_full_name"], repo_dir)
        nb_abs = (repo_dir / c["notebook_path"]).resolve()
        if not nb_abs.exists(): continue

        tri = triage_notebook(str(nb_abs), str(repo_dir))
        row = dict(
            repo_url=c["repo_html_url"],
            repo_stars=c["repo_stars"],
            repo_pushed_at=c["repo_pushed_at"],
            notebook_path=c["notebook_path"],
            notebook_url=c["notebook_url"],
            size_kb=c["size_kb"],
            n_cells=tri["n_cells"],
            libs_detected=tri["libs_detected"],
            has_relative_data_paths=tri["has_relative_data_paths"],
            missing_paths=tri["missing_paths"],
            suspect_cuda=tri["suspect_cuda"],
            has_heavy_libs=tri["has_heavy_libs"],
            keep_candidate=tri["keep_candidate"],
            runtime_seconds="",
            status="triaged",
            error_type="",
            error_message="",
        )
        rows.append(row)

    with open(DATASET_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        for r in rows: w.writerow(r)
    print(f"Wrote {DATASET_CSV} with {len(rows)} triaged entries.")

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

    out_rows = []
    for i, row in df.iterrows():
        if spent + per_nb > total_budget: break

        repo_dir = WORK / slug(row["repo_url"].split("github.com/")[-1])
        if repo_dir.exists(): shutil.rmtree(repo_dir)
        clone_repo(row["repo_url"].split("github.com/")[-1], repo_dir)

        nb_abs = (repo_dir / row["notebook_path"]).resolve()
        if not nb_abs.exists(): continue

        try:
            extra = infer_installs(str(nb_abs))
        except Exception:
            extra = []
        py_in_env = ensure_repo_env(row["repo_url"], repo_dir, extra_pkgs=extra)

        out_nb = RUNS / (slug(row["repo_url"]) + "_" + slug(row["notebook_path"]) + ".ipynb")
        res = execute_notebook(str(nb_abs), str(out_nb),
                               allow_installs=False,
                               per_notebook_seconds=per_nb,
                               python_exe=str(py_in_env))

        spent += min(per_nb, int(res["runtime_seconds"]))
        row["runtime_seconds"] = res["runtime_seconds"]
        row["status"] = res["status"]
        row["error_type"] = res["error_type"]
        row["error_message"] = res["error_message"]
        out_rows.append(row.to_dict())

    pd.DataFrame(out_rows).to_csv(DATASET_CSV, index=False)
    print(f"Updated {DATASET_CSV} with execution results for {len(out_rows)} notebooks.")

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
