"""Profile saved pipeline traces without importing the pipeline or calling models.

Example: python tools/profile_run.py outputs/runs/custom/RUN --output profile.json
Summed request time is not wall time when requests overlap. Cached responses do not
contribute their historical token counts or backend durations to inference totals.
These diagnostics measure cost and recorded checks, not independent accuracy.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


def percentile(values, fraction):
    """Nearest-rank percentile; null means no observations."""
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def read_events(path, warnings):
    with path.open('rb') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                # A hard crash can leave one unfinished final write. Never hide
                # malformed complete records or corruption in the middle.
                if not line.endswith(b'\n') and not stream.read():
                    warnings.append(f'Ignored incomplete final event at line {number}')
                    return
                raise ValueError(f'{path}:{number}: invalid event JSON') from exc


def read_optional(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def profile_run(directory):
    directory = Path(directory)
    manifest = read_optional(directory / 'manifest.json', {})
    warnings = []
    roles = defaultdict(Counter)
    requests = {}
    events = Counter()
    fingerprints = Counter()
    latencies = defaultdict(list)
    output_counts = defaultdict(list)
    page_sizes = defaultdict(list)
    stage_requests = Counter()
    stage_wait = Counter()
    last_elapsed = 0.0
    candidate_roles = {
        'concept_alias_resolver': ('existing_concepts', 'canonical_name'),
        'relation_resolver': ('available', 'key'),
    }
    for event in read_events(directory / 'events.jsonl', warnings):
        kind, data = event['event'], event.get('data', {})
        events[kind] += 1
        last_elapsed = max(last_elapsed, event.get('elapsed_seconds', 0))
        if kind == 'model.request':
            role = data['role']
            row = roles[role]
            row['requests'] += 1
            row['retry_requests'] += int(data.get('attempt', 1) > 1)
            stage = event.get('stage', 'unknown')
            stage_requests[stage] += 1
            requests[event['event_id']] = dict(role=role, stage=stage,
                started=event.get('elapsed_seconds'), response=False, failed=False, cached=False)
            key = {k: data.get(k) for k in ('model', 'role', 'prompt', 'schema', 'options', 'think')}
            digest = hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            row['identical_repeat_requests'] += int(fingerprints[digest] > 0)
            fingerprints[digest] += 1
            if role in candidate_roles:
                marker = '\nDATA:\n'
                if marker in data.get('prompt', ''):
                    try:
                        payload, _ = json.JSONDecoder().raw_decode(data['prompt'].split(marker, 1)[1])
                        if 'text_references' in payload and 'data' in payload:
                            payload = payload['data']
                        candidates = payload.get(candidate_roles[role][0])
                        if isinstance(candidates, list):
                            page_sizes[role].append(len(candidates))
                    except ValueError:
                        pass  # Older prompt formats need not be parseable.
            continue
        request = requests.get(event.get('parent_id'))
        if kind in {'cache.hit', 'model.response', 'model.attempt_failed', 'validation.failed'} and request:
            role, stage = request['role'], request['stage']
            row = roles[role]
            if kind == 'cache.hit':
                request['cached'] = True
            elif kind == 'validation.failed':
                row['validation_failures'] += 1
            elif kind == 'model.attempt_failed':
                request['failed'] = True
                row['failed_attempts'] += 1
                row['output_limit_failures'] += int(data.get('error_type') == 'OutputLimitError')
                if not request['response']:
                    row['failures_before_response'] += 1
                    start, end = request['started'], event.get('elapsed_seconds')
                    if start is not None and end is not None and not request['cached']:
                        wait = max(0, end - start)
                        row['failed_request_wait_seconds'] += wait
                        stage_wait[stage] += wait
            else:
                request['response'] = True
                row['responses'] += 1
                request['cached'] |= data.get('source') == 'cache'
                if request['cached']:
                    continue
                row['live_responses'] += 1
                raw = data['response']
                wait = data.get('duration_seconds')
                if wait is None and request['started'] is not None and event.get('elapsed_seconds') is not None:
                    wait = event['elapsed_seconds'] - request['started']
                if wait is not None:
                    wait = max(0, wait)
                    latencies[role].append(wait)
                    row['response_wait_seconds'] += wait
                    stage_wait[stage] += wait
                row['prompt_tokens'] += raw.get('prompt_eval_count') or 0
                row['output_tokens'] += raw.get('eval_count') or 0
                if raw.get('eval_count') is not None:
                    output_counts[role].append(raw['eval_count'])
                for field in ('load_duration', 'prompt_eval_duration', 'eval_duration'):
                    row[field + '_seconds'] += (raw.get(field) or 0) / 1e9
                row['truncated_responses'] += int(raw.get('done_reason') == 'length')
                if role in candidate_roles:
                    try:
                        answer = json.loads(raw['message']['content'])
                        field = candidate_roles[role][1]
                        if isinstance(answer, dict) and field in answer:
                            row['null_candidate_responses' if answer[field] is None else 'proposed_match_responses'] += 1
                    except (ValueError, KeyError):
                        pass
    for request in requests.values():
        row = roles[request['role']]
        row['cache_hits'] += int(request['cached'])
        row['pending_requests'] += int(not request['response'] and not request['failed'])
    rows = []
    for role, counter in roles.items():
        row = dict(counter)
        for field in ('cache_hits', 'responses', 'live_responses', 'pending_requests',
                      'failed_attempts', 'validation_failures', 'output_limit_failures',
                      'response_wait_seconds', 'failed_request_wait_seconds', 'prompt_tokens', 'output_tokens'):
            row.setdefault(field, 0)
        row.update(role=role, uncached_requests=row['requests'] - row['cache_hits'],
            measured_wait_seconds=row['response_wait_seconds'] + row['failed_request_wait_seconds'],
            latency_p50_seconds=percentile(latencies[role], .5),
            latency_p95_seconds=percentile(latencies[role], .95),
            output_tokens_p50=percentile(output_counts[role], .5),
            output_tokens_p95=percentile(output_counts[role], .95),
            candidate_page_p50=percentile(page_sizes[role], .5),
            candidate_page_p95=percentile(page_sizes[role], .95))
        rows.append(row)
    rows.sort(key=lambda r: r['measured_wait_seconds'], reverse=True)
    totals = {key: sum(r[key] for r in rows) for key in (
        'requests', 'uncached_requests', 'cache_hits', 'live_responses', 'pending_requests',
        'measured_wait_seconds', 'prompt_tokens', 'output_tokens', 'failed_attempts', 'validation_failures')}
    extraction = read_optional(directory / 'artifacts/extraction_quality.json', [])
    extraction_totals = {key: sum(row.get(key, 0) for row in extraction)
                         for key in ('reviewed', 'accepted', 'rejected', 'unresolved')} if isinstance(extraction, list) else {}
    unresolved = manifest.get('unresolved_items')
    if unresolved is None:
        unresolved = read_optional(directory / 'artifacts/unresolved_items.json', [])
    input_path = directory / 'input.txt'
    return dict(schema_version=1, run=str(directory), status=manifest.get('status', 'unknown'),
        wall_seconds=manifest.get('duration_seconds', last_elapsed),
        source_words=len(input_path.read_text(encoding='utf-8-sig').split()) if input_path.exists() else None,
        totals=totals, roles=rows,
        stages=[dict(stage=s, requests=n, measured_wait_seconds=stage_wait[s]) for s, n in stage_requests.items()],
        recorded_quality=dict(extraction=extraction_totals,
            unresolved_by_step=dict(Counter(r.get('step', 'unknown') for r in unresolved)) if isinstance(unresolved, list) else {},
            accuracy_verified=False),
        event_counts=dict(events), warnings=warnings,
        interpretation=[
            'Model agreement, rejection counts and schema validation are not independent accuracy measurements.',
            'Wait time sums observed request durations; concurrent waits can exceed wall time.',
            'Cached responses exclude historical inference tokens and durations; pending requests have unknown cost.',
            'Resolver null/match counts describe raw responses, not verified identity decisions.',
            'Compare quality and completed work before interpreting speed differences between runs.',
        ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, help='Optional JSON report destination')
    parser.add_argument('--top', type=int, default=10, help='Number of roles printed per run')
    args = parser.parse_args()
    if args.top < 1:
        parser.error('--top must be positive')
    reports = [profile_run(directory) for directory in args.runs]
    if args.output:
        if args.output.resolve() in {directory.resolve() for directory in args.runs} or args.output.exists():
            parser.error('--output must be a new report file; existing files are not overwritten')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(reports, stream, indent=2, ensure_ascii=False)
            stream.write('\n')
    for report in reports:
        print(f"\n{report['run']} ({report['status']})")
        total = report['totals']
        print(f"Wall: {report['wall_seconds'] / 60:.1f} min; requests: {total['requests']}; "
              f"cache hits: {total['cache_hits']}; pending: {total['pending_requests']}")
        print(f"{'Role':36} {'Requests':>8} {'Wait min':>9} {'p95 sec':>8} {'Out p95':>8} {'Fails':>6}")
        for row in report['roles'][:args.top]:
            latency = '-' if row['latency_p95_seconds'] is None else f"{row['latency_p95_seconds']:.2f}"
            tokens = '-' if row['output_tokens_p95'] is None else str(row['output_tokens_p95'])
            print(f"{row['role']:36} {row['requests']:8} {row['measured_wait_seconds']/60:9.2f} "
                  f"{latency:>8} {tokens:>8} {row['failed_attempts']:6}")
        print('Recorded quality:', json.dumps(report['recorded_quality']))
        for warning in report['warnings']:
            print('Warning:', warning)
    if args.output:
        print(f'\nReport: {args.output}')


if __name__ == '__main__':
    main()
