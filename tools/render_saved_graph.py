"""Refresh a completed run's portable graph view without inference or changing facts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.graph_quality import require_quality
from pipeline.graph_view import render_graph
import _submission_runtime as notebook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    manifest_path = args.run/'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest['status'] not in {'completed', 'completed_with_issues'}:
        raise ValueError('Only refresh completed runs')
    graph_path = args.run/'artifacts/graph.json'
    graph_bytes = graph_path.read_bytes()
    graph = json.loads(graph_bytes)
    require_quality(graph, required=True)
    if hashlib.sha256(graph_bytes).hexdigest() != manifest['artifacts']['artifacts/graph.json']['sha256']:
        raise ValueError('Graph artifact hash differs from the saved manifest')
    payload = render_graph(graph).encode('utf-8')
    artifact = dict(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
    old = manifest['artifacts'].get('knowledge_graph.html')
    if old == artifact:
        print('Portable graph already uses the current renderer.')
        return
    target = args.run/'knowledge_graph.html'
    temporary = target.with_suffix('.html.rendering')
    temporary.write_bytes(payload)
    temporary.replace(target)
    manifest['artifacts']['knowledge_graph.html'] = artifact
    manifest.setdefault('render_updates', []).append(dict(
        at=datetime.now(timezone.utc).isoformat(), previous_artifact=old, artifact=artifact,
        graph_sha256=hashlib.sha256(graph_bytes).hexdigest(),
        renderer_sha256=hashlib.sha256(notebook.asset_text('pipeline/graph_view.html').encode('utf-8')).hexdigest(),
        inference=False, graph_changed=False))
    temporary_manifest = manifest_path.with_suffix('.json.rendering')
    temporary_manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    temporary_manifest.replace(manifest_path)
    print(json.dumps(dict(run=str(args.run), updated='knowledge_graph.html', graph_changed=False)))


if __name__ == '__main__':
    main()
