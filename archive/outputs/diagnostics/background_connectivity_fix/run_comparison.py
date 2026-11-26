"""Repeat the saved baseline commands with fresh run directories."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


directory = Path(__file__).resolve().parent
root = directory.parents[2]
baseline = json.loads((directory / 'baseline-runs.json').read_text(encoding='utf-8'))
results = []
for row in baseline:
    command = row['command']
    destination = root / command[command.index('--output-root') + 1]
    before = set(destination.rglob('manifest.json'))
    with (directory / ('fixed-' + destination.name + '.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    record = dict(input=row['input'], command=command, exit_code=result.returncode,
                  manifests=[str(path.relative_to(root)) for path in sorted(set(destination.rglob('manifest.json')) - before)],
                  notebook_sha256=hashlib.sha256((root / '261273237.ipynb').read_bytes()).hexdigest())
    results.append(record)
    (directory / 'fixed-runs.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps(record), flush=True)
