"""Compare saved background admission outcomes without making model calls."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def summarize(directory):
    directory = Path(directory)

    def read(name, default):
        path = directory / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

    manifest = read('manifest.json', {})
    debate = read('artifacts/debate.json', None)
    if debate is None:
        debate = read('artifacts/debate_progress.json', {})
    seeds = read('artifacts/seeds.json', {})
    selected = debate.get('seeds', seeds.get('selected', []))
    candidates = debate.get('candidates', [])
    accepted = [row for row in candidates if row.get('accepted')]
    gaps = {gap['id']: gap for seed in selected for gap in seed.get('gaps', [])}
    answered = {identifier for row in accepted for identifier in row.get('gap_ids', [])}
    reused = {identifier for transcript in debate.get('transcripts', [])
              for identifier in transcript.get('reused_gap_answers', {})}
    limits = []
    budget_failures = set()
    request_roles = {}
    events = directory / 'events.jsonl'
    if events.exists():
        for line in events.read_text(encoding='utf-8').splitlines():
            event = json.loads(line)
            data = event.get('data', {})
            if event.get('event') == 'model.request':
                request_roles[event.get('event_id')] = data.get('role')
            if event.get('event') == 'model.attempt_failed' and data.get('error_type') == 'OutputLimitError':
                limits.append(dict(entity_id=event.get('entity_id'),
                                   role=request_roles.get(event.get('parent_id')),
                                   reason=data['error']))
            if event.get('event') == 'repair.context_budget' and data.get('status') == 'unresolved':
                budget_failures.add(event.get('entity_id'))
    unresolved = read('artifacts/unresolved_items.json', [])
    # Link emitted budget failures to item diagnostics. Preserve the complete
    # unresolved list below as well: a pre-request failure may have no model event.
    recorded = {row['entity_id'] for row in limits} | budget_failures
    recorded |= {identifier.removesuffix('_repair') for identifier in recorded if identifier}
    resource_items = [row for row in unresolved if row.get('id') in recorded]
    config = manifest.get('config', {})
    source = directory / 'input.txt'
    return dict(directory=str(directory), status=manifest.get('status'), error=manifest.get('error'),
        input=config.get('input'), resume=config.get('resume'),
        input_sha256=hashlib.sha256(source.read_text(encoding='utf-8').encode('utf-8')).hexdigest() if source.exists() else None,
        accepted=len(accepted), total=len(candidates),
        original_proposals=sum(not row.get('repair_of') for row in candidates),
        repair_proposals=sum(bool(row.get('repair_of')) for row in candidates),
        connecting_repair_proposals=sum(row.get('repair_kind') == 'connection' for row in candidates),
        accepted_connecting_repairs=sum(row.get('repair_kind') == 'connection' for row in accepted),
        rejections_by_stage=dict(Counter(row.get('rejection_stage') or row.get('review_status', 'unknown')
                                         for row in candidates if not row.get('accepted'))),
        output_limit_events=len(limits), output_limit_details=limits,
        output_limits_by_role=dict(Counter(row['role'] or 'unknown' for row in limits)),
        context_budget_unresolved_ids=sorted(budget_failures), resource_unresolved_items=resource_items,
        unresolved_items=unresolved,
        planned_gaps=len(gaps), gaps_with_accepted_fact=len(set(gaps) & (answered | reused)),
        answered_gap_ids=sorted(set(gaps) & (answered | reused)),
        gap_measure='Distinct selected gap IDs linked to an accepted fact or verified reuse; not a completeness judgment.',
        accepted_facts=[{key: row.get(key) for key in
                        ('id', 'intended_fact', 'source', 'relation', 'target', 'relation_definition',
                         'conditions', 'modality', 'argument_qualifiers', 'gap_ids', 'decision_reason')}
                       for row in accepted])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path, nargs='+')
    args = parser.parse_args()
    print(json.dumps([summarize(path) for path in args.runs], indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
