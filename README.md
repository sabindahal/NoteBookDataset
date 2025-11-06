
export GITHUB_TOKEN=ghp_xxx...

### 1) Install deps in a fresh venv
python -m venv .notebook && source .notebook/bin/activate
pip install -r requirements.txt

### 2) Search GitHub for candidate repos
python build_dataset.py search   --query 'topic:machine-learning  stars:>20 pushed:>=2023-01-01'   --max-repos 50 --max-nbs-per-repo 5

### 3) Triage notebooks (filter out obvious missing-data notebooks). This will take longest time
python build_dataset.py triage

### 4) Execute notebooks with a runtime budget (8 min per nb by default)
python build_dataset.py run   --per-notebook-seconds 480   --max-total-seconds 7200

### 5) After execution notebook_dataset.csv this is the reports of all the repo that could run, either with error or not. 

### 6) The newly ran notebooks are in artifacts/nb_runs
