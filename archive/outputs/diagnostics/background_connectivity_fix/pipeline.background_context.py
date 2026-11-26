"""Run-local graph context for constructing and repairing connected explanations."""
import copy


def connection_record(row):
    return {key: copy.deepcopy(row[key]) for key in
            ('id', 'source', 'relation', 'target', 'relation_definition',
             'conditions', 'modality', 'argument_qualifiers', 'origin') if key in row}


def seed_neighborhood(seed, facts, concepts):
    """Offer names and actual links, never infer an attachment from proximity."""
    connections = [connection_record(row) for row in facts
                   if seed['concept'] in (row.get('source'), row.get('target'))
                   or (seed.get('id') is not None and row.get('seed_id') == seed['id'])]
    names = {seed['concept']} | {row[side] for row in connections for side in ('source', 'target')}
    return dict(seed={key: seed.get(key) for key in ('id', 'concept', 'definition', 'kind')},
                existing_concepts=[copy.deepcopy(concepts.get(name, {'name': name})) for name in sorted(names)],
                existing_connections=connections)


def connectivity_context(row, seed, facts):
    """Preserve the attachment graph even when optional repair prose is removed."""
    neighborhood = seed_neighborhood(seed, facts, {})
    endpoints = {row.get('source'), row.get('target')} - {None}
    nearby = [connection_record(fact) for fact in facts
              if endpoints & {fact.get('source'), fact.get('target')}]
    connections = {fact['id']: fact for fact in neighborhood['existing_connections'] + nearby}
    reachable = {seed['concept']}
    while True:
        expanded = reachable | {fact[side] for fact in connections.values()
                                if reachable & {fact['source'], fact['target']}
                                for side in ('source', 'target')}
        if expanded == reachable:
            break
        reachable = expanded
    return dict(seed=seed['concept'], unconnected_concepts=sorted(endpoints - reachable),
                candidate_endpoints=sorted(endpoints), attachment_concepts=sorted(reachable),
                existing_connections=list(connections.values()))
