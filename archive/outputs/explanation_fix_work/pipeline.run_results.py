"""Read-only run summary from saved artifacts; missing measurements stay null."""
import json


def summarize(snapshot):
    root, manifest = snapshot.directory, snapshot.manifest
    def read(name, json_data=False):
        try:
            text = (root / name).read_text(encoding='utf-8')
            return json.loads(text) if json_data else text
        except (OSError, ValueError):
            return None
    stats = read('statistics.json', True) or {}
    evaluation = read('artifacts/evaluation.json', True) or {}
    stages = {name: dict(name=name, status=None, duration=None, counts={})
              for name in ['input', 'preflight', *manifest.get('pipeline_stages', ['extraction', 'debate', 'graph', 'evaluation'])]}
    starts = {}
    try:
        with (root / 'events.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                if '"stage.' not in line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                name, action = event.get('stage'), event.get('event')
                if not name or action not in {'stage.started', 'stage.completed', 'stage.failed'}:
                    continue
                stage = stages.setdefault(name, dict(name=name, counts={}))
                stage['status'] = action.split('.')[1]
                if action == 'stage.started':
                    starts[name] = event.get('elapsed_seconds')
                    stage['duration'] = None
                else:
                    duration = event.get('data', {}).get('duration_seconds')
                    if duration is None and starts.get(name) is not None and event.get('elapsed_seconds') is not None:
                        duration = event['elapsed_seconds'] - starts[name]
                    stage['duration'] = duration
    except OSError:
        pass
    fields = {'input': ['paragraphs', 'chunks', 'words'], 'extraction': ['claims', 'relations', 'unresolved_records'],
              'debate': ['seeds', 'proposed', 'accepted', 'rejected', 'unresolved'], 'graph': ['nodes', 'edges']}
    for name, keys in fields.items():
        if name in stages:
            stages[name]['counts'] = {k: stats.get(name, {}).get(k) for k in keys}
    if 'evaluation' in stages:
        stages['evaluation']['counts'] = {'reconstructed_chunks': len(evaluation['results']) if 'results' in evaluation else None}
        stages['evaluation']['status'] = stages['evaluation']['status'] or manifest.get('evaluation_status')
    unresolved = manifest.get('unresolved_items', stats.get('unresolved_items'))
    quality = read('artifacts/extraction_quality.json', True)
    review = read('artifacts/extraction_review.json', True)
    graph_review = read('artifacts/graph_quality.json', True)
    graph_summary = None
    if graph_review:
        graph_summary = dict(status=graph_review.get('status'), scope=graph_review.get('scope'),
            nodes=graph_review.get('final_nodes'), relationships=graph_review.get('final_edges'),
            excluded_background=len(graph_review.get('excluded_background', [])),
            unresolved_attachments=len(graph_review.get('unresolved_attachments', [])),
            unlinked_mentions=len(graph_review.get('mentions', [])))
        stage = stages.setdefault('graph_quality', dict(name='graph_quality', duration=None))
        stage.update(status=graph_summary['status'], counts={k:v for k,v in graph_summary.items()
                     if k not in {'status', 'scope'}})

    extraction = stats.get('extraction', {})
    validation = dict(relations=extraction.get('relations'))
    for field in ('accepted', 'rejected', 'unresolved'):
        validation[field] = (sum(row[field] for row in quality) if isinstance(quality, list)
                             and all(isinstance(row, dict) and isinstance(row.get(field), (int, float)) for row in quality)
                             else None)
    return dict(validation=validation, configuration=manifest.get('config'),
        graph_acceptance_policy=manifest.get('graph_acceptance_policy'),
        graph_quality_status=manifest.get('graph_quality_status'),
        validation_records=dict(chunk_quality=quality, reviews=review, graph_quality=graph_summary,
                                issues=read('artifacts/extraction_issues.json', True)), run_name=manifest.get('run_id', root.name), input_topic=manifest.get('config', {}).get('chapter'),
        input=manifest.get('config', {}).get('input'), date=manifest.get('started_at_utc') or manifest.get('started_at'),
        status=manifest.get('status'), duration=manifest.get('duration_seconds'), steps=list(stages.values()),
        nodes=len(snapshot.graph['nodes']), manual_revision=snapshot.revision,
        graph_version='edited' if snapshot.graph.get('_manual') else 'generated',
        edges=len(snapshot.graph['edges']),
        accepted=(sum(e.get('origin')=='background' for e in snapshot.graph['edges']) if graph_summary else stats.get('debate', {}).get('accepted')),
        rejected=((stats.get('debate', {}).get('rejected') or 0) + graph_summary['excluded_background'] if graph_summary else stats.get('debate', {}).get('rejected')),
        unresolved=((len(unresolved) if isinstance(unresolved, list) else 0) + graph_summary['unresolved_attachments']
                    if graph_summary else len(unresolved) if isinstance(unresolved, list) else None),
        reconstruction_score=evaluation.get('final_score', manifest.get('reconstruction_score')),
        scores=evaluation.get('summary', stats.get('fidelity', {})),
        interpretation=evaluation.get('interpretation', stats.get('interpretation')),
        metric_version=evaluation.get('metric_version', stats.get('evaluation_metric_version')),
        original=read('input.txt'), reconstructed=read('reconstruction.txt'),
        comparisons=[{k: r.get(k) for k in ('chunk_id', 'original', 'reconstruction', 'final_score', 'status')}
                     for r in evaluation.get('results', [])])
