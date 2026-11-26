"""Prepare and verify the November 26 archive operation without running inference.

Filesystem moves are recorded in move_plan.json and applied with checked, native
PowerShell Move-Item operations. Original execution records remain in the archive.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[3]
WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
AI = Path('outputs/runs/ai-test/run_20261125_130636_UTC-0500_bd046a0c')
ORIGINAL = Path('outputs/runs/llm-tuning/custom/run_20261125_034536_UTC-0500_9e4db7ab')
RECOVERY = Path('outputs/runs/llm-tuning/recoveries/recovery_20261125_153513_1d4712cf')
NEURONS = Path('outputs/runs/neurons-and-glia/custom/run_20261125_180507_UTC-0500_585a42c3')
LLM_FINAL = Path('outputs/runs/llm-tuning') / ORIGINAL.name
NEURONS_FINAL = Path('outputs/runs/neurons-and-glia') / NEURONS.name
STAGED = WORK / 'staging' / ORIGINAL.name
DB = ROOT / 'outputs/professor/students.sqlite3'
DB_BACKUP = ROOT / 'archive/databases/2026-11-26/students.sqlite3'
INPUTS = {'ai_test.txt', 'llm_tuning.txt', 'neurons_and_glia.txt'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def archive_run(path):
    return Path('archive/runs') / path.relative_to('outputs/runs')


def timestamp(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def events(path):
    with (path / 'events.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def validate_hashes(path):
    errors = []
    for name, entry in read(path / 'manifest.json').get('artifacts', {}).items():
        target = path / name
        if not target.is_file() or sha(target) != entry['sha256']:
            errors.append(name)
    if errors:
        raise ValueError(f'Artifact hash mismatch at {path}: {errors}')


def prepare_consolidation():
    from pipeline.graph_view import render_graph
    from pipeline.report import render_report

    original, recovery = ROOT / ORIGINAL, ROOT / RECOVERY
    first, last = read(original / 'manifest.json'), read(recovery / 'manifest.json')
    assert Path(last['source_run']).resolve() == original.resolve()
    assert (original / 'input.txt').read_bytes() == (recovery / 'input.txt').read_bytes()
    assert last['status'] == 'completed_with_issues'
    for source in (ROOT / AI, original, recovery, ROOT / NEURONS):
        validate_hashes(source)
    if STAGED.exists():
        raise FileExistsError(STAGED)
    shutil.copytree(recovery, STAGED)
    # The final recovery artifacts are authoritative. Retain original-only stage
    # artifacts/cache entries too; conflicting historical versions stay archived.
    for source in (original / 'artifacts').rglob('*'):
        destination = STAGED / source.relative_to(original)
        if source.is_file() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    started, finished = timestamp(first['started_at']), timestamp(last['finished_at'])
    segments, totals = [], Counter()
    sequence = 0
    event_counts = Counter()
    event_path = STAGED / 'events.jsonl'
    with event_path.open('w', encoding='utf-8', newline='\n') as output:
        for index, relative in enumerate((ORIGINAL, RECOVERY), 1):
            source = ROOT / relative
            manifest = read(source / 'manifest.json')
            rows = list(events(source))
            id_map = {row['event_id']: f'event_{sequence + i:06d}' for i, row in enumerate(rows, 1)}
            segment = dict(number=index, run_id=manifest['run_id'], status=manifest['status'],
                           started_at=manifest['started_at'], finished_at=manifest['finished_at'],
                           original_directory=str(relative), archived_directory=archive_run(relative).as_posix(),
                           events_sha256=sha(source / 'events.jsonl'),
                           manifest_sha256=sha(source / 'manifest.json'),
                           environment_sha256=sha(source / 'artifacts/environment.json'),
                           event_count=len(rows), performance=manifest.get('performance', {}))
            if manifest.get('error'):
                segment['error'] = manifest['error']
            segments.append(segment)
            totals['active_duration_seconds'] += rows[-1]['elapsed_seconds']
            totals['model_calls'] += manifest['performance']['model_calls']
            totals['cache_hits'] += manifest['performance'].get('cache_hits', 0)
            for row in rows:
                sequence += 1
                recorded = {k: row.get(k) for k in ('run_id', 'sequence', 'event_id', 'parent_id', 'elapsed_seconds')}
                row['source_event'] = dict(segment=index, **recorded)
                row['run_id'] = first['run_id']
                row['sequence'] = sequence
                row['event_id'] = id_map[recorded['event_id']]
                if recorded['parent_id']:
                    row['parent_id'] = id_map[recorded['parent_id']]
                row['elapsed_seconds'] = (timestamp(row['timestamp']) - started).total_seconds()
                output.write(json.dumps(row, ensure_ascii=False) + '\n')
                event_counts[row['event']] += 1
                if row['event'] == 'model.response':
                    response = row.get('data', {}).get('response', {})
                    totals['prompt_tokens'] += response.get('prompt_eval_count', 0) or 0
                    totals['output_tokens'] += response.get('eval_count', 0) or 0
                elif row['event'] == 'model.retry':
                    totals['retries'] += 1
                elif row['event'] == 'embedding.request':
                    totals['embedding_calls'] += 1

    lineage = dict(schema_version=1, operation='consolidated_execution_history',
                   created_at=datetime.now(timezone.utc).isoformat(), segments=segments,
                   explanation='Original execution followed by checkpoint recovery. Original failures, '
                               'timestamps, decisions, and final unresolved issues are preserved. '
                               'This is one logical run, not one uninterrupted process.',
                   wall_duration_seconds=(finished - started).total_seconds(),
                   active_duration_seconds=totals['active_duration_seconds'],
                   event_mapping='Canonical event IDs and parent IDs are unique. source_event retains '
                                 'each original identity. Event data and recorded timestamps are unchanged.')
    write(STAGED / 'artifacts/execution_segments.json', lineage)
    graph = read(STAGED / 'artifacts/graph.json')
    graph['run_id'] = first['run_id']
    write(STAGED / 'artifacts/graph.json', graph)
    (STAGED / 'knowledge_graph.html').write_text(render_graph(graph), encoding='utf-8')
    stats = read(STAGED / 'statistics.json')
    stats['run_id'] = first['run_id']
    stats['execution_segments'] = segments
    stats['models'].update(calls=totals['model_calls'], cache_hits=totals['cache_hits'],
                           retries=totals['retries'], embedding_calls=totals['embedding_calls'],
                           prompt_tokens=totals['prompt_tokens'], output_tokens=totals['output_tokens'])
    write(STAGED / 'statistics.json', stats)
    page, report = render_report(stats, read(STAGED / 'artifacts/paragraphs.json'),
                                read(STAGED / 'artifacts/chunks.json'),
                                read(STAGED / 'artifacts/debate.json'),
                                read(STAGED / 'artifacts/evaluation.json'))
    notice = ('This run combines the original execution and its checkpoint recovery. '
              'The interruption and all unresolved issues are retained. '
              'See artifacts/execution_segments.json for the two original execution records.')
    page = page.replace('<body>', '<body><p>' + notice + '</p>', 1)
    report = report.replace('\n\n', '\n\n' + notice + '\n\n', 1)
    (STAGED / 'index.html').write_text(page, encoding='utf-8')
    (STAGED / 'report.md').write_text(report, encoding='utf-8')
    log = 'Consolidated execution history; original records are preserved in archive/runs.\n\n'
    log += '=== Original execution: ' + first['run_id'] + ' ===\n'
    log += (original / 'run.log').read_text(encoding='utf-8')
    log += '\n=== Checkpoint recovery: ' + last['run_id'] + ' ===\n'
    log += 'The following recovery progress is reconstructed from recorded events.\n'
    for event in events(recovery):
        if event['event'] in {'stage.started', 'stage.completed', 'stage.failed', 'run.failed', 'run.closed',
                              'checkpoint.migration_verified', 'checkpoint.prior_work_preserved'}:
            log += f"{event['timestamp']} [{event['stage']}] {event['event']}\n"
    log += '\nFinal status: ' + last['status'] + '; evaluation: ' + last['evaluation_status'] + '\n'
    (STAGED / 'run.log').write_text(log, encoding='utf-8')

    merged = deepcopy(last)
    merged.update(run_id=first['run_id'], scope='consolidated_original_and_checkpoint_recovery',
                  source_run=str(ROOT / archive_run(ORIGINAL)),
                  started_at=first['started_at'], started_at_utc=started.astimezone(timezone.utc).isoformat(),
                  finished_at=finished.astimezone(started.tzinfo).isoformat(),
                  finished_at_utc=finished.astimezone(timezone.utc).isoformat(),
                  duration_seconds=lineage['wall_duration_seconds'],
                  active_duration_seconds=lineage['active_duration_seconds'],
                  pipeline_stages=['extraction', 'debate', 'checkpoint_restore', 'graph', 'evaluation'],
                  execution_segments=segments, consolidation=lineage,
                  performance=dict(model_calls=totals['model_calls'], cache_hits=totals['cache_hits'],
                                   execution_segments=2),
                  event_counts_before_finalization=dict(event_counts))
    merged.pop('no_earlier_stage_replay', None)
    merged['artifacts'] = {}
    for path in sorted(STAGED.rglob('*')):
        relative = path.relative_to(STAGED).as_posix()
        if path.is_file() and relative not in {'manifest.json', 'events.jsonl', 'run.log'} and not relative.startswith('explorer_sessions/'):
            merged['artifacts'][relative] = dict(sha256=sha(path), bytes=path.stat().st_size)
    write(STAGED / 'manifest.json', merged)
    validate_hashes(STAGED)
    assert {k:v for k,v in graph.items() if k != 'run_id'} == {
        k:v for k,v in read(recovery / 'artifacts/graph.json').items() if k != 'run_id'}
    return lineage


def prepare():
    if (WORK / 'move_plan.json').exists():
        raise FileExistsError('Preparation already exists; inspect it instead of overwriting it.')
    DB_BACKUP.parent.mkdir(parents=True, exist_ok=True)
    if DB_BACKUP.exists():
        raise FileExistsError(DB_BACKUP)
    with sqlite3.connect(DB.resolve().as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(DB_BACKUP) as backup:
        source.backup(backup)
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    for name in ('261273237.ipynb', 'README.md', 'data/README.md', 'data/input_sources.txt',
                 'docs/professor.md', 'tools/demo_student_contributions.py',
                 'tests/test_pipeline.py', 'tests/test_topic_independence.py'):
        dest = WORK / 'before' / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, dest)
    lineage = prepare_consolidation()
    moves = []
    def move(source, destination):
        source, destination = Path(source), Path(destination)
        assert (ROOT/source).resolve().is_relative_to(ROOT)
        assert (ROOT/destination).resolve().is_relative_to(ROOT)
        assert not (ROOT/destination).exists(), destination
        moves.append(dict(source=source.as_posix(), destination=destination.as_posix()))

    # Move selected graph into the layout supported by the library scanner.
    move(NEURONS, NEURONS_FINAL)
    move(STAGED.relative_to(ROOT), LLM_FINAL)
    for path in sorted((ROOT/'outputs/runs').glob('**/manifest.json')):
        relative = path.parent.relative_to(ROOT)
        if relative in {AI, NEURONS} or 'recovery_source' in relative.parts:
            continue
        move(relative, archive_run(relative))
    for path in sorted((ROOT/'data/archive').iterdir()):
        move(path.relative_to(ROOT), Path('archive/inputs') / path.name)
    for name in ('AI Chapter.txt', 'Neurology Chapter.txt', 'validation'):
        move(Path('data')/name, Path('archive/inputs')/name)
    for path in sorted((ROOT/'outputs/archive').iterdir()):
        move(path.relative_to(ROOT), Path('archive/outputs')/path.name)
    for path in sorted((ROOT/'outputs').iterdir()):
        if path.name not in {'runs','professor','setup','archive'}:
            move(path.relative_to(ROOT), Path('archive/outputs')/path.name)
    if (ROOT/'debug.log').exists():
        move('debug.log','archive/logs/debug.log')
    write(WORK/'move_plan.json', dict(root=str(ROOT), moves=moves))
    write(WORK/'selection.json', dict(inputs=sorted(INPUTS), active_runs=[str(AI),str(LLM_FINAL),str(NEURONS_FINAL)],
                                     original_selected_runs=[str(AI),str(RECOVERY),str(NEURONS)],
                                     database_backup=str(DB_BACKUP.relative_to(ROOT)), lineage=lineage))
    print(json.dumps(dict(prepared=True, moves=len(moves), database_backup=str(DB_BACKUP),
                          consolidated_events=sum(s['event_count'] for s in lineage['segments']))))


def rebuild_database():
    from pipeline.explorer import load_snapshot
    from pipeline.professor import run_identity, topic_identity
    paths = [ROOT/AI, ROOT/LLM_FINAL, ROOT/NEURONS_FINAL]
    snapshots = [load_snapshot(p) for p in paths]
    # All existing sessions belong to older archived runs, verified explicitly.
    original_kept = {str((ROOT/p).resolve()) for p in (AI,RECOVERY,NEURONS)}
    with sqlite3.connect(DB_BACKUP) as old:
        preserved_old_ids = {r[0] for r in old.execute('SELECT id,directory FROM runs') if r[1] in original_kept}
        assert not any(r[0] in preserved_old_ids for r in old.execute('SELECT run_id FROM sessions'))
        assert not any(r[0] in preserved_old_ids for r in old.execute('SELECT run_id FROM fact_approvals'))
    staged_db = WORK/'students.staged.sqlite3'
    if staged_db.exists():
        raise FileExistsError(staged_db)
    with sqlite3.connect(DB_BACKUP) as backup, sqlite3.connect(staged_db) as staged:
        backup.backup(staged)
        staged.execute('PRAGMA foreign_keys=ON')
        with staged:
            for table in ('contributions','contribution_jobs','overrides','pending_answers','answers',
                          'sessions','requests','assessment_errors','fact_approvals','runs'):
                staged.execute('DELETE FROM '+table)
            for snapshot in snapshots:
                key, title = topic_identity(snapshot)
                payload = dict(graph=snapshot.original_graph or snapshot.graph,
                               manifest=snapshot.manifest, quiz_aliases=snapshot.quiz_aliases)
                staged.execute('INSERT INTO runs VALUES (?,?,?,?,?)',
                               (run_identity(snapshot),key,title,str(snapshot.directory),json.dumps(payload)))
        assert staged.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert staged.execute('PRAGMA foreign_key_check').fetchall() == []
        assert staged.execute('SELECT count(*) FROM runs').fetchone()[0] == 3
    # SQLite backup replaces pages consistently; preserve the live database path.
    with sqlite3.connect(staged_db) as staged, sqlite3.connect(DB) as live:
        staged.backup(live)
    print('Database updated: three graphs; student identities retained; old histories archived.')


def verify():
    from pipeline.professor import discover_latest, run_identity
    from pipeline.explorer import load_snapshot
    assert {p.name for p in (ROOT/'data').glob('*.txt')} == INPUTS | {'input_sources.txt'}
    runs = sorted((ROOT/'outputs/runs').glob('**/manifest.json'))
    assert {p.parent for p in runs} == {ROOT/AI, ROOT/LLM_FINAL, ROOT/NEURONS_FINAL}
    found, warnings = discover_latest(ROOT/'outputs/runs', latest_only=False)
    assert len(found)==3 and not warnings, warnings
    for path in (ROOT/AI,ROOT/LLM_FINAL,ROOT/NEURONS_FINAL):
        validate_hashes(path)
        load_snapshot(path)
    merged = ROOT/LLM_FINAL
    rows = list(events(merged))
    ids = {e['event_id'] for e in rows}
    assert len(ids)==len(rows)
    assert all(e['sequence']==i for i,e in enumerate(rows,1))
    assert all(e['parent_id'] is None or e['parent_id'] in ids for e in rows)
    assert all(timestamp(a['timestamp']) <= timestamp(b['timestamp']) for a,b in zip(rows,rows[1:]))
    for segment, relative in enumerate((ORIGINAL,RECOVERY),1):
        originals=list(events(ROOT/archive_run(relative)))
        actual=[e for e in rows if e['source_event']['segment']==segment]
        assert len(actual)==len(originals)
        for before,after in zip(originals,actual):
            assert before['data']==after['data'] and before['event']==after['event']
            assert before['timestamp']==after['timestamp']
            assert before['event_id']==after['source_event']['event_id']
    old_graph=read(ROOT/archive_run(RECOVERY)/'artifacts/graph.json')
    new_graph=read(merged/'artifacts/graph.json')
    assert {k:v for k,v in old_graph.items() if k!='run_id'} == {k:v for k,v in new_graph.items() if k!='run_id'}
    with sqlite3.connect(DB) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert {r[0] for r in db.execute('SELECT id FROM runs')}=={run_identity(s) for s in found}
        counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ('runs','students','sessions','answers')}
    plan=read(WORK/'move_plan.json')
    assert all((ROOT/m['destination']).exists() and not (ROOT/m['source']).exists() for m in plan['moves'])
    report=dict(verified=True, active_inputs=sorted(INPUTS), runs=[dict(path=str(s.directory.relative_to(ROOT)),
                 status=s.manifest['status'], nodes=len(s.graph['nodes']),edges=len(s.graph['edges'])) for s in found],
                database=counts, merged_events=len(rows), original_event_data_preserved=True,
                retained_graph_content_unchanged=True, artifact_hashes_valid=True, moves=len(plan['moves']))
    write(WORK/'verification.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','database','verify'])
    action=parser.parse_args().action
    {'prepare':prepare,'database':rebuild_database,'verify':verify}[action]()
