"""Audit preserved source files, completed decisions, and continuation provenance."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from resume_debate_checkpoint import check_preserved

directory = Path(sys.argv[1]).resolve()
base = Path(__file__).parent
source = ROOT / 'outputs/runs/llm-tuning/custom/run_20261125_034536_UTC-0500_9e4db7ab'
read = lambda path: json.loads(path.read_text(encoding='utf-8'))
original = read(source / 'artifacts/checkpoints/debate.json')
result = read(directory / 'artifacts/debate_progress.json')
check_preserved(original['data'], result, original['artifacts'], directory)
new_candidates = result['candidates'][len(original['data']['candidates']):]
assert all(not row['accepted'] for row in new_candidates if row['review_status'] == 'unresolved')
assert all(row.get('gates', {}).get('connected_to_seed') is True
           for row in new_candidates if row['accepted']), 'A new accepted relationship lacks final connectivity approval'
expected = {k.replace('\\', '/'): v for k, v in read(base / 'source_hashes.json').items()}
actual = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in source.rglob('*') if p.is_file()}
assert expected == actual, 'Original run files changed'
events = [json.loads(line) for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines()]
requests = [event for event in events if event['event'] == 'model.request']
restores = [event for event in events if event['event'] == 'checkpoint.restored']
assert len(restores) == 1, 'Unexpected checkpoint restoration count'
assert not any(event['event'] == 'model.cache_hit' for event in events), 'Old model responses reused'
assert all(event['data'].get('source') == 'ollama' for event in events if event['event'] == 'model.response')
assert requests and requests[0]['entity_id'].startswith('seed_010'), 'Recovery did not start at seed_010'
assert {event['stage'] for event in requests} <= {'debate', 'evaluation'}, 'Earlier inference stage ran'
for event in requests:
    assert not any((event.get('entity_id') or '').startswith(seed)
                   for seed in original['data']['completed_seeds']), 'A completed seed made a model request'
manifest = read(directory / 'manifest.json')
checkpoint = read(directory / 'artifacts/checkpoints/debate.json')
summary = dict(recovery=str(directory), status=manifest['status'], original_files_unchanged=len(actual),
               preserved_candidates=len(original['data']['candidates']),
               preserved_transcripts=len(original['data']['transcripts']),
               completed_seeds=checkpoint['data']['completed_seeds'],
               total_candidates=len(result['candidates']), model_requests=len(requests),
               new_accepted=sum(row['accepted'] for row in new_candidates),
               new_unresolved=sum(row['review_status'] == 'unresolved' for row in new_candidates),
               new_accepted_connectivity_verified=True,
               cache_hits=0, earlier_stage_requests=0, first_request=requests[0]['entity_id'],
               health_window=manifest['config']['health_window'],
               health_min_samples=manifest['config']['health_min_samples'],
               health_max_failure_rate=manifest['config']['health_max_failure_rate'])
(base / 'recovery_integrity.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
