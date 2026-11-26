"""Version-aware fact identity and descriptive learning metrics (no model calls)."""
from collections import Counter, defaultdict
import json
from .settings import setting


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
            'id', 'source', 'target', 'evidence', 'supporting_evidence', 'evidence_start', 'evidence_end', 'origin', 'chunk_id', 'paragraph_id',
            'confidence', 'score', 'scores', 'candidate_id', 'seed_id'}}
        keys[e['id']] = json.dumps([nodes[e['source']], semantic, nodes[e['target']]], sort_keys=True)
    counts = Counter(keys.values())
    return {identifier: key for identifier, key in keys.items() if counts[key] == 1}


def retain_mastery(previous, current):
    """A valid independent demonstration survives later attempts, not overrides.

    Call while replaying effective (corrected) answers in chronological order.
    Replaying from scratch removes credit whose supporting answer was corrected.
    """
    if previous and previous['mark'] == 'match' and not previous['helped']:
        if current['mark'] != 'match' or current['helped']:
            return previous
    return current


def learning_node_status(graph, edge_status):
    """Green concepts have all incident relationships independently known."""
    adjacent = {n['id']: [] for n in graph['nodes']}
    for edge in graph['edges']:
        for key in {edge['source'], edge['target']}:
            adjacent[key].append(edge_status.get(edge['id']))
    result = {}
    for key, states in adjacent.items():
        if states and all(s == 'match' for s in states):
            result[key] = 'match'
        elif any(s in ('match', 'related') for s in states):
            result[key] = 'related'
        elif any(s == 'conflict' for s in states):
            result[key] = 'conflict'
        elif any(s == 'not_demonstrated' for s in states):
            result[key] = 'not_demonstrated'
    return result


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
    return dict(edge_status=edges, node_status=learning_node_status(graph, edges), completed=True)


def communities(graph):
    """Deterministic label propagation on the undirected graph; no new dependency."""
    labels = community_partition(graph)
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
            assessed_score=mean([100 * setting('assessment_weights', facts[k]['mark']) for k in assessed])))
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
    'Knowledge coverage': 'Relationships with a retained independent demonstration / all relationships in this graph version. Assisted success is not mastery. Later attempts do not erase earned green; corrections to its supporting evidence can revoke it.',
    'Assessment coverage': 'Relationships with an assessed answer / all relationships. Unassessed material is separate from incorrect answers.',
    'Answer performance': 'Mean score of the latest answer to each question using its recorded scoring weights, with independent and assisted answers reported separately. Only answers on the selected version count.',
    'Topic coverage': 'Knowledge coverage within deterministic graph communities; cross-community relationships form bridge topics. Community labels are representative concepts.',
    'Connected understanding': 'Mastered concepts in the largest undirected component of mastered relationships / all mastered concepts. For this connectivity calculation, a mastered concept is an endpoint of an independently correct relationship. Circle color instead summarizes all incident relationships and is green only when all are independently known.',
    'Fragmentation': 'Number of mastered components, including isolated mastered concepts. Isolates can only arise from a self-relationship under the endpoint-based definition; concept mentions do not establish mastery.',
    'Topic concentration': 'Sum of squared shares of mastered facts across communities (HHI). Near 1 means concentrated; smaller values mean spread across topics. This measures topic distribution, not connectivity.',
    'Progress': 'Cumulative coverage and latest-per-question answer performance after each answer, within this version. Transferred facts form the initial baseline. Professor corrections are reflected retrospectively.',
    'Class averages': 'Equal weight per student; unavailable values excluded with sample sizes shown. Coverage includes enrolled students with no assessments. Class edge proportions use the entire roster, alongside assessed counts.',
    'Version transfer': 'Only unique, exactly matching semantic facts from earlier runs of the same input transfer, with source run and answer retained. Changed or ambiguous facts remain unassessed. Historical answers and sessions are never deleted.'
}


def community_partition(graph):
    """Stable reference partition, reused for every learner in a scope."""
    neighbors = {n['id']: set() for n in graph['nodes']}
    for e in graph['edges']:
        if e['source'] != e['target']:
            neighbors[e['source']].add(e['target'])
            neighbors[e['target']].add(e['source'])
    labels = {n: n for n in neighbors}
    for _ in range(setting('operations', 'community_passes')):
        changed = False
        for node in sorted(neighbors):
            counts = Counter(labels[n] for n in sorted(neighbors[node]))
            if counts:
                best = min(counts, key=lambda label: (-counts[label], label))
                changed |= labels[node] != best
                labels[node] = best
        if not changed:
            break
    return labels


def graph_metrics(graph, facts, partition=None):
    """Twelve metric families; topology and fact evidence have separate denominators.

    Simple undirected topology collapses parallel facts and excludes self-links.
    Degree/density/clustering/components use demonstrated endpoints. Efficiency
    includes all reference nodes, including unreachable ones. Directed degrees
    count distinct incoming/outgoing neighbors, never statement repetitions.
    """
    from collections import deque
    partition = community_partition(graph) if partition is None else partition
    nodes = {n['id']: n for n in graph['nodes']}
    edges = {e['id']: e for e in graph['edges']}
    facts = {k: v for k, v in facts.items() if k in edges}
    known = {k for k, v in facts.items() if v['mark'] == 'match' and not v['helped']}
    adj = {k: set() for k in nodes}
    incoming, outgoing = {k: set() for k in nodes}, {k: set() for k in nodes}
    incident, mastered, assessed = defaultdict(set), defaultdict(set), defaultdict(set)
    reached, bridges, bins = set(), set(), Counter()
    for key, e in edges.items():
        a, b = e['source'], e['target']
        if partition[a] != partition[b]:
            bridges.add(key)
        for node in {a, b}:
            incident[node].add(key)
            if key in facts:
                assessed[node].add(key)
            if key in known:
                mastered[node].add(key)
        if key in known:
            reached.update((a, b))
            bins[tuple(sorted({partition[a], partition[b]}))] += 1
            if a != b:
                adj[a].add(b); adj[b].add(a)
                outgoing[a].add(b); incoming[b].add(a)
    components, remaining = [], set(reached)
    while remaining:
        pending, component = [min(remaining)], set()
        while pending:
            node = pending.pop()
            if node not in component:
                component.add(node)
                pending.extend(adj[node] - component)
        remaining -= component
        components.append(component)
    pair_count = sum(map(len, adj.values())) // 2
    clustering = {}
    inverse_distances = 0.0
    for node in reached:
        neighbors = adj[node]
        k = len(neighbors)
        clustering[node] = (sum(len(neighbors & adj[v]) for v in neighbors) / (k*(k-1))) if k > 1 else 0.0
        distances, queue = {node: 0}, deque([node])
        while queue:
            current = queue.popleft()
            for target in adj[current]:
                if target not in distances:
                    distances[target] = distances[current] + 1
                    inverse_distances += 1 / distances[target]
                    queue.append(target)
    group_degree, internal = Counter(), Counter()
    for node in reached:
        group_degree[partition[node]] += len(adj[node])
        internal[partition[node]] += sum(partition[node] == partition[v] for v in adj[node]) / 2
    modularity = (sum(internal[g]/pair_count - (degree/(2*pair_count))**2
                      for g, degree in group_degree.items()) if pair_count else None)
    concepts = []
    for key, node in nodes.items():
        concepts.append(dict(id=key, label=node['label'], degree=len(adj[key]),
            in_degree=len(incoming[key]), out_degree=len(outgoing[key]),
            known=len(mastered[key]), total=len(incident[key]), assessed=len(assessed[key]),
            completeness=percentage(len(mastered[key]), len(incident[key])),
            clustering=round(clustering[key], 3) if key in clustering else None,
            community=nodes[partition[key]]['label'], reached=key in reached))
    n = len(reached)
    values = dict(relationship_coverage=percentage(len(known), len(edges)),
        assessment_coverage=percentage(len(facts), len(edges)),
        concept_reach=percentage(n, len(nodes)),
        concept_completeness=mean([c['completeness'] for c in concepts]),
        average_degree=round(2*pair_count/n, 3) if n else None,
        density=round(100*2*pair_count/(n*(n-1)), 2) if n > 1 else None,
        components=len(components) if n else None,
        largest_component=percentage(max(map(len, components), default=0), n),
        clustering=mean(list(clustering.values()), 3),
        cross_topic_coverage=percentage(len(bridges & known), len(bridges)),
        global_efficiency=round(inverse_distances/(len(nodes)*(len(nodes)-1)), 3) if n and len(nodes)>1 else None,
        modularity=round(modularity, 3) if modularity is not None else None,
        concentration=round(sum((count/len(known))**2 for count in bins.values()), 3) if known else None,
        connection_strength=mean([c['known'] for c in concepts], 3))
    groups = []
    names = {key: n['label'] for key, n in nodes.items()}
    for group in sorted(set(partition.values())):
        ids = {e['id'] for e in edges.values() if partition[e['source']] == group and partition[e['target']] == group}
        groups.append(dict(id=group, title=names[group], concepts=sum(g == group for g in partition.values()),
            total=len(ids), known=len(ids & known), assessed=len(ids & facts.keys()),
            coverage=percentage(len(ids & known), len(ids))))
    return dict(values=values, concepts=concepts, communities=groups,
        degree_distribution=[dict(degree=d, concepts=c) for d,c in sorted(Counter(len(adj[k]) for k in reached).items())],
        known=len(known), assessed=len(facts), total=len(edges), reached=n, nodes=len(nodes),
        links=pair_count, largest_size=max(map(len, components), default=0), bridge_total=len(bridges), bridge_known=len(bridges & known),
        community_count=len(set(partition.values())))


def scope_graph_metrics(graph, rows):
    """Keep class topology as a distribution of individual results, not a union."""
    from statistics import median
    partition = community_partition(graph)
    reference_facts = {e['id']: dict(mark='match', helped=False) for e in graph['edges']}
    reference = graph_metrics(graph, reference_facts, partition)
    # Reference topology includes concepts with no incident facts.
    n, m = len(graph['nodes']), reference['links']
    reference['values']['average_degree'] = round(2*m/n, 3) if n else None
    reference['values']['density'] = round(100*2*m/(n*(n-1)), 2) if n>1 else None
    isolates = sum(c['total'] == 0 for c in reference['concepts'])
    reference['values']['components'] = (reference['values']['components'] or 0) + isolates if n else None
    reference['values']['largest_component'] = percentage(max(1 if isolates else 0, reference['largest_size']), n)
    reference['values']['clustering'] = mean([c['clustering'] or 0 for c in reference['concepts']], 3)
    for row in rows:
        row['graph_metrics'] = graph_metrics(graph, row['knowledge'], partition)
    averages = {}
    for key in reference['values']:
        values = [r['graph_metrics']['values'][key] for r in rows if r['graph_metrics']['values'][key] is not None]
        averages[key] = dict(value=mean(values, 3), n=len(values),
            median=round(median(values), 3) if values else None,
            low=min(values) if values else None, high=max(values) if values else None)
    prevalence = {e['id']: sum(e['id'] in r['knowledge'] and r['knowledge'][e['id']]['mark']=='match'
                              and not r['knowledge'][e['id']]['helped'] for r in rows) for e in graph['edges']}
    collective = sum(v>0 for v in prevalence.values())
    shared_fraction = setting('metrics', 'shared_knowledge_fraction')
    shared = sum(v/len(rows)>=shared_fraction for v in prevalence.values()) if rows else 0
    concepts = []
    concept_maps = [{c['id']: c for c in r['graph_metrics']['concepts']} for r in rows]
    for c in reference['concepts']:
        individual = [mapping[c['id']] for mapping in concept_maps]
        concepts.append(dict(c, mean_degree=mean([x['degree'] for x in individual], 3),
            strength=mean([x['known'] for x in individual], 3),
            completeness=mean([x['completeness'] for x in individual]),
            assessed_students=sum(x['assessed']>0 for x in individual)))
    return dict(reference=reference, averages=averages, concepts=concepts,
        collective_coverage=percentage(collective, len(graph['edges'])) if rows else None,
        shared_coverage=percentage(shared, len(graph['edges'])) if rows else None,
        collective=collective, shared=shared, shared_knowledge_fraction=shared_fraction, students=len(rows))
