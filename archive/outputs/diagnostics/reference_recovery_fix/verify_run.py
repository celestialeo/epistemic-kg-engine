"""Inspect the requested AI Test run; this is not pipeline input or a graph repair."""
import json
from pathlib import Path
import sys
from collections import Counter

root = Path(__file__).resolve().parents[3]
run = root / sys.argv[1]
graph = json.loads((run / 'artifacts/graph.json').read_text(encoding='utf-8'))
nodes = {n['id']: n['label'] for n in graph['nodes']}
document = [e for e in graph['edges'] if e['origin'] == 'document']

def reading(edge):
    return ' '.join(str(v or '') for v in (nodes[edge['source']], edge['label'],
        nodes[edge['target']], edge.get('conditions'), edge.get('modality'),
        *(edge.get('argument_qualifiers') or []))).casefold().replace('_', ' ')

def matching(*terms):
    return [e['id'] for e in document if all(t in reading(e) for t in terms)]

claims = {
    'self_attention_for_text': matching('small transformer', 'self attention', 'process text'),
    'backpropagation_training_purpose': matching('small transformer', 'backpropagation', 'improve', 'predictions', 'during training'),
    'regularization_generalization_owner': matching('regularization', 'generaliz', 'beyond', 'training examples', 'small transformer'),
    'quantization_memory_owner_and_timing': matching('quantization', 'memory requirements', 'small transformer', 'after training'),
    'rag_actor_action_and_timing': matching('retrieval augmented generation', 'small transformer', 'use external documents', 'answering questions'),
}
original = (run / 'input.txt').read_text(encoding='utf-8')
assert all(e.get('evidence') and e['evidence'] in original for e in document), 'Evidence changed'
assert all(claims.values()), claims
coverage = json.loads((run / 'artifacts/source_coverage.json').read_text(encoding='utf-8'))
assert all(c['status'] == 'covered_by_model_review' for c in coverage['chunks']), coverage
evaluation = json.loads((run / 'artifacts/evaluation.json').read_text(encoding='utf-8'))
stats = json.loads((run / 'statistics.json').read_text(encoding='utf-8'))
manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
result = dict(run=run.name, status=manifest['status'], claims=claims,
    graph=dict(nodes=len(nodes), edges=len(graph['edges']), origins=dict(Counter(e['origin'] for e in graph['edges']))),
    source_coverage=[c['status'] for c in coverage['chunks']],
    reconstruction_score=evaluation['final_score'], evaluation_status=evaluation['status'],
    document_metrics={k:v for k,v in (evaluation.get('document_metrics') or {}).items() if not isinstance(v,(dict,list))},
    unresolved_items=stats['unresolved_items'], model_usage=stats['models'],
    duration_seconds=manifest.get('duration_seconds'))
out = Path(__file__).with_name('verified-result.json')
out.write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
