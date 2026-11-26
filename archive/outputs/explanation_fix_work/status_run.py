import json
import sys
from collections import Counter
from pathlib import Path

root = Path(sys.argv[1])
run = root if (root / 'manifest.json').exists() else sorted(root.glob('custom/*'))[-1]
manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
print('RUN', run.name, 'STATUS', manifest['status'])
progress = run / 'artifacts/debate_progress.json'
if progress.exists():
    rows = json.loads(progress.read_text(encoding='utf-8'))['candidates']
    print('CANDIDATES', len(rows), dict(Counter(r['review_status'] for r in rows)))
    if rows:
        seed = rows[-1]['seed_id']
        print('LATEST', seed, [(r['id'], r['review_status'], r.get('rejection_stage')) for r in rows if r['seed_id'] == seed])
events = (run / 'events.jsonl').read_text(encoding='utf-8').splitlines()
event = json.loads(events[-1])
print('EVENT', event['timestamp'], event['event'], event['data'].get('role'))
