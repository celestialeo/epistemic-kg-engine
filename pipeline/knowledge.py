"""Version-aware fact identity and descriptive learning metrics (no model calls)."""
from collections import Counter, defaultdict
import json


def percentage(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def mean(values, digits=1):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), digits) if values else None


def fact_keys(graph):
    """Conservative exact semantic match, independent of generated IDs.

    Preserve direction, endpoint definitions, conditions and modality. Ambiguous
    duplicates cannot transfer. Deliberately do not infer synonyms or paraphrases.
    """
    nodes = {n['id']: {k: n.get(k) for k in ('label', 'definition', 'kind')} for n in graph['nodes']}
    keys = {}
    for e in graph['edges']:
        semantic = {k: v for k, v in e.items() if k not in {
            'id', 'source', 'target', 'evidence', 'origin', 'chunk_id', 'paragraph_id',
            'confidence', 'score', 'scores', 'candidate_id', 'seed_id'}}
        keys[e['id']] = json.dumps([nodes[e['source']], semantic, nodes[e['target']]], sort_keys=True)
    counts = Counter(keys.values())
    return {identifier: key for identifier, key in keys.items() if counts[key] == 1}


def display_state(graph, facts):
    edges, nodes = {}, {}
    rank = {'not_demonstrated': 1, 'related': 2, 'conflict': 3, 'match': 4}
    for edge in graph['edges']:
        fact = facts.get(edge['id'])
        if not fact:
            continue
        # Assisted success is visibly provisional, never independently green.
        mark = 'related' if fact['mark'] == 'match' and fact['helped'] else fact['mark']
        edges[edge['id']] = mark
        for node in (edge['source'], edge['target']):
            if rank[mark] > rank.get(nodes.get(node), 0):
                nodes[node] = mark
    return dict(edge_status=edges, node_status=nodes, completed=True)


def communities(graph):
    """Deterministic label propagation on the undirected graph; no new dependency."""
    neighbors = {n['id']: set() for n in graph['nodes']}
    for e in graph['edges']:
        neighbors[e['source']].add(e['target'])
        neighbors[e['target']].add(e['source'])
    labels = {n: n for n in neighbors}
    for _ in range(30):
        changed = False
        for node in sorted(neighbors):
            counts = Counter(labels[n] for n in neighbors[node])
            if not counts:
                continue
            best = min(counts, key=lambda label: (-counts[label], label))
            if labels[node] != best:
                labels[node] = best
                changed = True
        if not changed:
            break
    groups = defaultdict(list)
    for e in graph['edges']:
        # Cross-community relationships have their own explicit bridge topic.
        groups[tuple(sorted({labels[e['source']], labels[e['target']]}))].append(e['id'])
    names = {n['id']: n['label'] for n in graph['nodes']}
    return [{'id': '|'.join(key), 'title': ' / '.join(names[n] for n in key), 'facts': ids}
            for key, ids in sorted(groups.items())]


def metrics(graph, facts, answers=(), groups=None):
    edges = {e['id']: e for e in graph['edges']}
    facts = {k: v for k, v in facts.items() if k in edges}
    mastered = {k for k, v in facts.items() if v['mark'] == 'match' and not v['helped']}
    adjacency = defaultdict(set)
    for key in mastered:
        edge = edges[key]
        adjacency[edge['source']].add(edge['target'])
        adjacency[edge['target']].add(edge['source'])
    remaining, components = set(adjacency), []
    while remaining:
        pending, component = [min(remaining)], set()
        while pending:
            node = pending.pop()
            if node not in component:
                component.add(node)
                pending.extend(adjacency[node] - component)
        remaining -= component
        components.append(component)
    topics = []
    for group in groups if groups is not None else communities(graph):
        ids = set(group['facts'])
        assessed = ids & facts.keys()
        topics.append(dict(id=group['id'], title=group['title'], total=len(ids),
            mastered=len(ids & mastered), assessed=len(assessed), unassessed=len(ids-assessed),
            knowledge_coverage=percentage(len(ids & mastered), len(ids)),
            assessed_score=mean([{'match': 100, 'related': 50, 'conflict': 0, 'not_demonstrated': 0}[facts[k]['mark']] for k in assessed])))
    latest = {a['question']['id']: a for a in answers}
    independent = [a['score'] for a in latest.values() if not a['helped']]
    assisted = [a['score'] for a in latest.values() if a['helped']]
    concentration = sum((t['mastered']/len(mastered))**2 for t in topics) if mastered else None
    return dict(total=len(edges), assessed=len(facts), independent=len(mastered),
        assisted=sum(v['mark'] == 'match' and v['helped'] for v in facts.values()),
        unassessed=len(edges)-len(facts), knowledge_coverage=percentage(len(mastered), len(edges)),
        assessment_coverage=percentage(len(facts), len(edges)),
        average_score=mean([a['score'] for a in latest.values()]),
        independent_score=mean(independent), assisted_score=mean(assisted),
        independent_answers=len(independent), assisted_answers=len(assisted),
        connected_understanding=percentage(max(map(len, components), default=0), len(adjacency)),
        mastered_concepts=len(adjacency), mastered_components=len(components),
        isolated_mastered_concepts=sum(len(c) == 1 for c in components),
        concentration=round(concentration, 3) if concentration is not None else None,
        topics=topics)


DEFINITIONS = {
    'Knowledge coverage': 'Independently correct relationships / all relationships in this graph version. Assisted success is not mastery.',
    'Assessment coverage': 'Relationships with an assessed answer / all relationships. Unassessed material is separate from incorrect answers.',
    'Answer performance': 'Mean score of the latest answer to each question (correct 1, partial 0.5, incorrect or not demonstrated 0), with independent and assisted answers reported separately. Only answers on the selected version count.',
    'Topic coverage': 'Knowledge coverage within deterministic graph communities; cross-community relationships form bridge topics. Community labels are representative concepts.',
    'Connected understanding': 'Mastered concepts in the largest undirected component of mastered relationships / all mastered concepts. A concept is mastered only as an endpoint of an independently correct relationship.',
    'Fragmentation': 'Number of mastered components, including isolated mastered concepts. Isolates can only arise from a self-relationship under the endpoint-based definition; concept mentions do not establish mastery.',
    'Topic concentration': 'Sum of squared shares of mastered facts across communities (HHI). Near 1 means concentrated; smaller values mean spread across topics. This measures topic distribution, not connectivity.',
    'Progress': 'Cumulative coverage and latest-per-question answer performance after each answer, within this version. Transferred facts form the initial baseline. Professor corrections are reflected retrospectively.',
    'Class averages': 'Equal weight per student; unavailable values excluded with sample sizes shown. Coverage includes enrolled students with no assessments. Class edge proportions use the entire roster, alongside assessed counts.',
    'Version transfer': 'Only unique, exactly matching semantic facts from earlier runs of the same input transfer, with source run and answer retained. Changed or ambiguous facts remain unassessed. Historical answers and sessions are never deleted.'
}
