"""Check saved full-pipeline runs without a topic vocabulary or live inference.

This validates provenance and completed checks, not independent factual truth.
Human-readable assertions are emitted for a separate source/meaning audit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.graph_quality import require_quality, context_view


def inspect_run(directory):
    def read(name):
        return json.loads((directory/name).read_text(encoding='utf-8'))
    manifest = read('manifest.json')
    assert manifest['status'] in {'completed', 'completed_with_issues'}, manifest['status']
    graph = read('artifacts/graph.json')
    require_quality(graph, required=True)
    quality = read('artifacts/graph_quality.json')
    assert quality['status'] == 'passed'
    assert quality['source_coverage']['complete']
    assert quality['final_review']['consistent']
    assert quality['final_review']['concepts_distinct']
    final_context = {}
    for row in quality.get('context_coverage', []):
        final_context[row['chunk_id']] = row
    if quality['version'] >= 3:
        assert final_context, 'Missing context coverage audit'
        assert all(c['passed'] for row in final_context.values() for c in row['checks']), 'Context coverage failed'
    text = (directory/'input.txt').read_bytes().decode('utf-8')
    assert graph['provenance']['text'] == text
    for name, entry in manifest['artifacts'].items():
        assert hashlib.sha256((directory/name).read_bytes()).hexdigest() == entry['sha256'], name
    nodes = {n['id']:n for n in graph['nodes']}
    assertions = []
    for edge in graph['edges']:
        limits = graph['quality'].get('format_limits', dict(predicate_words=3, predicate_chars=32))
        assert len(edge['label'].split('_')) <= limits['predicate_words'] and len(edge['label']) <= limits['predicate_chars']
        if edge['origin'] == 'document':
            assert text[edge['evidence_start']:edge['evidence_end']] == edge['evidence'], edge['id']
        assertions.append(dict(id=edge['id'], origin=edge['origin'],
            source=nodes[edge['source']]['label'], relation=edge['label'], target=nodes[edge['target']]['label'],
            source_definition=nodes[edge['source']]['definition'], target_definition=nodes[edge['target']]['definition'],
            definition=edge['definition'], conditions=edge.get('conditions'), modality=edge.get('modality'),
            **context_view(edge, nodes), source_order=edge.get('source_order'),
            evidence=edge.get('evidence'), verification_basis=edge['verification_basis']))
    evaluation = read('artifacts/evaluation.json')
    assert evaluation['status'] == 'completed', evaluation.get('reason')
    return dict(run=str(directory), status=manifest['status'], structural_checks_passed=True,
        words=len(text.split()), paragraphs=len(read('artifacts/paragraphs.json')),
        nodes=len(nodes), document_edges=sum(e['origin']=='document' for e in graph['edges']),
        background_edges=sum(e['origin']=='background' for e in graph['edges']),
        review_policy=quality.get('policy'),
        context_checks_passed=bool(final_context) and all(c['passed'] for row in final_context.values() for c in row['checks']),
        source_references=quality.get('source_references', {}),
        source_claims_reviewed=sum(len(sentence['claims']) for chunk in quality['source_coverage']['checks']
                                  for sentence in chunk.get('sentences', [])),
        excluded_background=len(quality['excluded_background']),
        unlinked_mentions=[n['label'] for n in quality['mentions']],
        unresolved_extraction_chunks=manifest.get('incomplete_extraction_chunks', []),
        unresolved_items=manifest.get('unresolved_items', []),
        model_estimated_reconstruction_score=evaluation['final_score'],
        independent_accuracy='Requires separate source and domain review; model agreement is not proof.',
        model=manifest['config']['model'],
        settings={k:manifest['config'].get(k) for k in ('seed_limit','background_proposal_limit','chunk_words',
            'context_tokens','batch_size','identity_candidates','max_output_tokens')},
        code_sha256=read('artifacts/environment.json')['code_sha256'], assertions=assertions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs', type=Path, nargs='+')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reports = [inspect_run(p) for p in args.runs]
    assert all(r['model']==reports[0]['model'] and r['settings']==reports[0]['settings'] for r in reports), 'Different model/settings'
    assert all(r['code_sha256']==reports[0]['code_sha256'] for r in reports), 'Different implementation versions'
    assert all(r['review_policy']==reports[0]['review_policy'] for r in reports), 'Different review policies'
    result = dict(checks_passed=True, same_code_and_settings=True, runs=reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({**result, 'runs':[{k:v for k,v in r.items() if k not in ('assertions','code_sha256')} for r in reports]}, indent=2))


if __name__ == '__main__':
    main()
