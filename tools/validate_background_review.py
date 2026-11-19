"""Independently review saved background candidates without publishing a reference graph.

This diagnostic does not regenerate or certify document facts. It records accepted
and withheld background assertions separately; debate acceptance alone cannot pass.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.graph_quality import refine_graph, require_quality, edge_node_ids
from pipeline.models import Models
from pipeline.settings import snapshot
from pipeline.trace import Trace
import _submission_runtime as notebook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume-review', type=Path, help='Reuse exact validated requests from a prior diagnostic')
    args = parser.parse_args()
    read = lambda name: json.loads((args.source/name).read_text(encoding='utf-8'))
    manifest = read('manifest.json')
    config = manifest['config']
    original_path = args.source/'artifacts/graph_before_review.json'
    if not original_path.exists():
        original_path = args.source/'artifacts/graph.json'
    original = json.loads(original_path.read_text(encoding='utf-8'))
    graph = copy.deepcopy(original)
    graph.pop('quality', None)
    graph['edges'] = [e for e in graph['edges'] if e['origin'] == 'background']
    if not graph['edges']:
        parser.error('The saved run contains no background candidates')
    ids = set().union(*(edge_node_ids(e) for e in graph['edges']))
    graph['nodes'] = [dict(n, origin='background') for n in graph['nodes'] if n['id'] in ids]
    # This isolates model-knowledge verification. The original source graph is
    # neither modified nor presented as a newly source-verified graph.
    graph['provenance'] = dict(text='', chunks=[], diagnostic_source=str(args.source),
                              scope='background_only_no_document_publication')
    trace = Trace(args.output, args.output.name)
    metadata = dict(status='running', scope='background_verification_diagnostic',
                    source=str(args.source), source_graph_sha256=hashlib.sha256(original_path.read_bytes()).hexdigest(),
                    source_input_sha256=hashlib.sha256((args.source/'input.txt').read_bytes()).hexdigest(),
                    code_sha256=notebook.source_hashes(), settings=snapshot(), reference_graph_published=False)
    try:
        models = Models(trace, config['model'], config['embedding_model'], config.get('host', 'http://localhost:11434'))
        models.preflight()
        trace.save('artifacts/environment.json', dict(model_details=models.details,
                   code_sha256=notebook.source_hashes(), settings=snapshot(), diagnostic_only=True))
        models.load_cache(args.source)
        if args.resume_review:
            models.load_cache(args.resume_review)
        reviewed = refine_graph(graph, models, trace)
        require_quality(reviewed, required=True)
        trace.save('checked_background.json', reviewed)
        metadata.update(status='diagnostic_completed', submitted=len(graph['edges']),
                        independently_verified=len(reviewed['edges']),
                        withheld=reviewed['quality']['excluded_background'])
        print(json.dumps(metadata, ensure_ascii=True, indent=2))
    except BaseException as exc:
        metadata.update(status='diagnostic_failed', error=str(exc))
        raise
    finally:
        trace.save('diagnostic.json', metadata)
        trace.close()


if __name__ == '__main__':
    main()
