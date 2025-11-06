### 1) export GITHUB_TOKEN=ghp_xxx...

### 2) Install deps in a fresh venv
python -m venv .notebook && source .notebook/bin/activate
pip install -r requirements.txt

### 3) Search GitHub for candidate repos
python build_dataset.py search   --query 'topic:machine-learning  stars:>20 pushed:>=2023-01-01'   --max-repos 50 --max-nbs-per-repo 5

### 4) Triage notebooks (filter out obvious missing-data notebooks). This will take longest time
python build_dataset.py triage

### 5) Execute notebooks with a runtime budget (8 min per nb by default)
python build_dataset.py run   --per-notebook-seconds 480   --max-total-seconds 7200

### 6) After execution notebook_dataset.csv 
this is the reports of all the repo that could run, either with error or not. 

### 7) The newly ran notebooks are in artifacts/nb_runs


### For the final deploy:
When we are satisfied with debugging phase, change the commands on the index.py and run python index.py