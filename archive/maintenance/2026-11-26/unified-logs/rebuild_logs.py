"""Render one chronological, explicitly reconstructed run.log per retained graph.

Only readable logs are replaced. Structured events, manifests, graphs, input
texts, reports, and the database remain byte-for-byte unchanged.
"""
from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[4]
WORK = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def stamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def one_line(value):
    return ' '.join(str(value).splitlines())


def describe(event):
    name, data = event['event'], event.get('data', {})
    entity = event.get('entity_id') or ''
    if name == 'stage.started':
        return 'INFO', 'Stage started.'
    if name == 'stage.completed':
        duration = data.get('duration_seconds')
        return 'INFO', 'Stage finished.' + (f' Duration: {duration} seconds.' if duration is not None else '')
    if name == 'stage.failed':
        return 'ERROR', f"Stage interrupted: {data.get('error_type', 'error')}: {data.get('error', '')}"
    if name == 'extraction.chunk_review_summary':
        return 'INFO', (f"{data.get('chunk_id', entity)}: {data.get('accepted', 0)} accepted, "
                        f"{data.get('rejected', 0)} rejected, {data.get('unresolved', 0)} unresolved.")
    if name == 'seed.selected':
        seed = data['seed']
        return 'INFO', f"Selected {seed['id']}: {seed['concept']}."
    if name == 'seed.selection_completed':
        return 'INFO', f"Seed selection finished: {data['selected']} selected from {data['assessed']} assessed."
    if name == 'model.attempt_failed':
        return 'WARN', (f"Model attempt failed for {data.get('role', '')} {entity}: "
                        f"{data.get('error', data.get('reason', json.dumps(data, ensure_ascii=False)))}")
    if name == 'model.retry':
        return 'INFO', f"Retrying model request {entity}: {json.dumps(data, ensure_ascii=False)}"
    if name == 'item.unresolved':
        return 'WARN', f"Unresolved {data.get('step', '')} {data.get('id', entity)}: {data.get('reason', '')}"
    if name == 'checkpoint.migration_verified':
        return 'INFO', (f"Checkpoint recovery verified using {data.get('policy', data.get('mode'))}; "
                        f"{len(data.get('completed_seeds', []))} completed seeds preserved. "
                        f"Updated modules: {', '.join(data.get('changed_modules', []))}.")
    if name == 'checkpoint.restored':
        return 'INFO', f"Restored {data.get('checkpoint')} checkpoint; processing continues."
    if name == 'checkpoint.prior_work_preserved':
        return 'INFO', f"Verified preservation of {len(data.get('completed_seeds', []))} previously completed seeds."
    if name == 'run.failed':
        return 'ERROR', f"Execution stopped: {data.get('error_type', 'error')}: {data.get('error', '')}"
    if name == 'run.closed' and data.get('status') not in {'completed', 'completed_with_issues'}:
        return 'WARN', f"Execution segment closed with status {data.get('status')}."
    return None


def build(directory, manifest):
    with (directory / 'events.jsonl').open(encoding='utf-8') as stream:
        events = [json.loads(line) for line in stream if line.strip()]
    assert events
    assert all(stamp(a['timestamp']) <= stamp(b['timestamp']) for a, b in zip(events, events[1:]))
    terminal = [event for event in events if event['event'] in {'run.completed', 'run.closed'}
                and event.get('data', {}).get('status') == manifest['status']]
    assert terminal, 'A recorded final result is required; no completion is synthesized.'
    final_event = terminal[-1]
    counts = Counter(event['event'] for event in events)
    segments = manifest.get('execution_segments', [])
    local_zone = stamp(manifest['started_at']).tzinfo
    lines = [
        'Reconstructed chronological run log, generated from recorded events.',
        'This is a readable timeline; full model requests and responses remain in events.jsonl.',
        f"Run: {manifest['run_id']}",
        f"Input: {manifest['config']['input']}",
        f"Recorded start: {manifest['started_at']}",
        f"Recorded finish: {manifest['finished_at']}",
        'Timezone: America/Toronto (timestamps include the original UTC offset).',
        f"Final status: {manifest['status']}",
        f"Evaluation: {manifest.get('evaluation_status', 'not recorded')}",
    ]
    if segments:
        lines.append('One logical run spanning the original execution and checkpoint recovery; the interruption is recorded below.')
    else:
        lines.append('One recorded execution; model retries are included below.')
    lines.append('')
    row_sources = []

    def emit(event, level, message):
        recorded_time = event.get('timestamp_local') or stamp(event['timestamp']).astimezone(local_zone).isoformat()
        lines.append(f"{recorded_time} | {level} | {event['stage']} | {one_line(message)}")
        row_sources.append(dict(event_id=event['event_id'], timestamp=event['timestamp'], level=level))

    start_event = next(event for event in events if event['event'] == 'run.started')
    emit(start_event, 'START', 'Logical run started.')
    for event in events:
        item = describe(event)
        if item is not None:
            emit(event, *item)
    emit(final_event, 'RESULT', f"Logical run finished: {manifest['status']}; evaluation: {manifest.get('evaluation_status', 'not recorded')}.")
    lines.extend([
        '',
        f"Recorded model attempts that failed: {counts['model.attempt_failed']}",
        f"Recorded model retries: {counts['model.retry']}",
        f"Final unresolved items: {len(manifest.get('unresolved_items', []))}",
        f"Incomplete extraction chunks: {', '.join(manifest.get('incomplete_extraction_chunks', [])) or 'none'}",
        'Final unresolved details and status are retained in manifest.json and artifacts/unresolved_items.json.',
        'Source event timestamps and messages were not rewritten. Stage durations retain their recorded values.',
    ])
    assert sum(' | START | ' in line for line in lines) == 1
    assert sum(' | RESULT | ' in line for line in lines) == 1
    assert all(stamp(a['timestamp']) <= stamp(b['timestamp']) for a, b in zip(row_sources, row_sources[1:]))
    if segments:
        assert any('Execution stopped:' in line for line in lines)
        assert any('checkpoint; processing continues.' in line for line in lines)
    return '\n'.join(lines) + '\n', dict(source_event_count=len(events), timeline_rows=len(row_sources),
                                         rows=row_sources, counts=dict(counts))


def main():
    audit_path = WORK / 'verification.json'
    if audit_path.exists():
        raise FileExistsError('Log reconstruction already completed; do not overwrite its backup.')
    manifests = sorted((ROOT / 'outputs/runs').glob('*/*/manifest.json'))
    assert len(manifests) == 3
    prepared, immutable = [], {}
    for path in manifests:
        directory, manifest = path.parent, read(path)
        # Check every saved file, not just the graph. Only run.log may change.
        for existing in directory.rglob('*'):
            if existing.is_file() and existing.name != 'run.log':
                immutable[existing.relative_to(ROOT).as_posix()] = digest(existing)
        assert 'run.log' not in manifest.get('artifacts', {}), 'Do not invalidate a hashed log artifact.'
        text, verification = build(directory, manifest)
        backup = WORK / 'before' / directory.relative_to(ROOT) / 'run.log'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise FileExistsError(backup)
        shutil.copy2(directory / 'run.log', backup)
        prepared.append((directory, text, backup, verification))
    for path in [ROOT / 'outputs/professor/students.sqlite3', *(ROOT / 'data').glob('*.txt')]:
        immutable[path.relative_to(ROOT).as_posix()] = digest(path)
    write_report = []
    for directory, text, backup, verification in prepared:
        temporary = directory / 'run.log.reconstructing'
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        temporary.replace(directory / 'run.log')
        write_report.append(dict(run=str(directory.relative_to(ROOT)), log='run.log',
                                 backup=str(backup.relative_to(ROOT)), previous_sha256=digest(backup),
                                 current_sha256=digest(directory / 'run.log'), **verification))
    changed = [name for name, expected in immutable.items() if digest(ROOT / name) != expected]
    assert not changed, changed
    audit = dict(verified=True, active_changes='Only the three run.log files',
                 protected_files_verified=len(immutable), original_events_preserved=True,
                 reconstructed=True, runs=write_report)
    audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(verified=True, protected_files_verified=len(immutable),
                         logs=[dict(path=str(directory.relative_to(ROOT) / 'run.log'),
                                    timeline_rows=verification['timeline_rows'])
                               for directory, _, _, verification in prepared]), indent=2))


if __name__ == '__main__':
    main()
