import subprocess
import sys
import os

cmds = [
    "python build_dataset.py search --query 'topic:machine-learning  stars:>2 pushed:>=2023-01-01' --max-repos 500 --max-nbs-per-repo 5",
    "python build_dataset.py triage",
    "python build_dataset.py run --per-notebook-seconds 480 --max-total-seconds 1200000"
]

for c in cmds:
    print(f"\n===== Running: {c} =====\n")
    ret = subprocess.run(c, shell=True)
    if ret.returncode != 0:
        print(f"\n❌ Command failed: {c}\n")
        sys.exit(ret.returncode)

print("\n All steps completed successfully!\n")
