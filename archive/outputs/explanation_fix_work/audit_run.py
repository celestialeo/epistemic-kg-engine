import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.stdout.reconfigure(errors='backslashreplace')

run = Path(sys.argv[1])
def read(name):
    path = run / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

manifest = read('manifest.json')
graph = read('artifacts/graph.json')
debate = read('artifacts/debate.json') or read('artifacts/debate_progress.json')
print('RUN', run)
print('STATUS', manifest['status'])
if not graph:
    print('No final graph yet')
else:
    names = {n['id']: n['label'] for n in graph['nodes']}
    adjacency = {node: set() for node in names}
    dangling = []
    for edge in graph['edges']:
        a, b = edge['source'], edge['target']
        if a not in names or b not in names: dangling.append(edge['id']); continue
        adjacency[a].add(b); adjacency[b].add(a)
    remaining, components = set(names), []
    while remaining:
        stack, component = [next(iter(remaining))], set()
        while stack:
            node = stack.pop()
            if node in component: continue
            component.add(node); stack.extend(adjacency[node] - component)
        remaining -= component
        components.append(sorted(names[node] for node in component))
    summary = dict(status=manifest['status'], nodes=len(names), edges=len(graph['edges']),
        origins=dict(Counter(e['origin'] for e in graph['edges'])), components=sorted(components, key=len, reverse=True),
        dangling=dangling, isolated=[names[n] for n, neighbors in adjacency.items() if not neighbors],
        definitions={n['label']:n.get('definition') for n in graph['nodes']},
        background_without_connectivity_validation=[r['id'] for r in (debate or {}).get('candidates', [])
            if r.get('accepted') and r.get('gates', {}).get('connected_to_seed') is not True],
        execution=manifest.get('execution'), unresolved_items=manifest.get('unresolved_items', []))
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    for edge in graph['edges']:
        qualifiers = {k:edge[k] for k in ('modality','conditions','argument_qualifiers') if edge.get(k)}
        print(edge['origin'], edge['id'], names[edge['source']], '--'+edge['label']+'-->', names[edge['target']], json.dumps(qualifiers))
        if edge['origin']=='background': print('  INTENDED',edge.get('intended_fact'))
    (run/'inspection_structure.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
if debate:
    seeds = defaultdict(list)
    for row in debate['candidates']: seeds[row['seed_id']].append(row)
    for seed, rows in seeds.items():
        print('SEED',seed,'accepted',sum(bool(r.get('accepted')) for r in rows),'of',len(rows))
        for row in rows:
            print(row['id'],row.get('accepted'),row.get('rejection_stage'),row.get('intended_fact'))
            if not row.get('accepted'): print('  ',row.get('decision_reason'))
