"""Run-local, transactional manual graph versions with an append-only audit log.

The pipeline never reads this sidecar. Readers overlay it only when opening saved
work. Generated artifacts and historical assessment snapshots remain immutable.
"""
import copy
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from .identity import concept_key


class EditConflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def semantics(graph):
    """Fact meaning including all endpoint and semantic participant definitions."""
    nodes = {n['id']: {k: n.get(k) for k in ('label', 'definition', 'kind')} for n in graph.get('nodes', [])}
    ignored = {'id', 'source', 'target', 'participants', 'evidence', 'supporting_evidence',
               'evidence_start', 'evidence_end', 'origin', 'chunk_id', 'paragraph_id',
               'confidence', 'score', 'scores', 'candidate_id', 'seed_id', 'source_order',
               'verification_basis', 'reason', 'tier', 'repair_of', 'gap_ids',
               'contribution_id', 'contributed_by', 'student_id', 'answer_id', 'session_id'}
    return {e['id']: digest([nodes[e['source']], {k: v for k, v in e.items() if k not in ignored},
                            nodes[e['target']], sorted([
                                {**p, 'node': nodes[p['node']]} for p in e.get('participants', [])
                            ], key=lambda p: json.dumps(p, sort_keys=True))]) for e in graph.get('edges', [])}


def affected(before, after):
    old, new = semantics(before), semantics(after)
    return sorted(k for k in old if old[k] != new.get(k))


NODE_FIELDS = {'label', 'definition'}
EDGE_FIELDS = {'source', 'target', 'label', 'definition', 'conditions', 'modality',
               'purpose', 'timing', 'participants', 'evidence'}


def validate(graph):
    nodes = graph['nodes']; edges = graph['edges']
    ids = {n['id'] for n in nodes}
    if len(ids) != len(nodes) or len({e['id'] for e in edges}) != len(edges):
        raise ValueError('Concept and relationship IDs must be unique')
    if len({concept_key(n['label']) for n in nodes}) != len(nodes):
        raise ValueError('A concept with that name already exists; use it as an endpoint')
    for edge in edges:
        if edge['source'] not in ids or edge['target'] not in ids:
            raise ValueError('Both relationship endpoints must be existing concepts')
        for p in edge.get('participants', []):
            if (not isinstance(p, dict) or set(p) != {'node', 'role', 'scope'} or p['node'] not in ids
                    or p['scope'] not in {'source', 'target', 'assertion', 'purpose'}
                    or not isinstance(p['role'], str) or not p['role'].strip() or len(p['role']) > 200):
                raise ValueError('Each participant needs an existing concept, a role, and a valid scope')


def differences(before, after):
    result = []
    for kind, collection in [('concept', 'nodes'), ('relationship', 'edges')]:
        old = {r['id']: r for r in before[collection]}; new = {r['id']: r for r in after[collection]}
        for key in sorted(old.keys() | new.keys()):
            if old.get(key) != new.get(key):
                result.append(dict(entity=kind, id=key, action='add' if key not in old else 'delete' if key not in new else 'edit',
                                   before=old.get(key), after=new.get(key)))
    return result


class ManualGraph:
    def __init__(self, directory, original):
        self.directory = Path(directory).resolve()
        self.path = self.directory / 'manual_graph.sqlite3'
        self.original = original

    def _state(self, db):
        row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
        if row is None or row['original_hash'] != digest(self.original):
            raise EditConflict('The generated graph no longer matches these manual edits')
        events = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM changes ORDER BY revision')]
        return dict(graph=json.loads(row['graph']), original=self.original, revision=row['revision'],
                    changes=events, edited=json.loads(row['graph']) != self.original)

    def read(self):
        if not self.path.exists():
            return dict(graph=copy.deepcopy(self.original), original=self.original, revision=0, changes=[], edited=False)
        with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            return self._state(db)

    def apply(self, command, actor=None):
        if not self.directory.is_dir():
            raise ValueError('The source run folder is unavailable; restore it before editing')
        signature = digest([command, actor])
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, original_hash TEXT, graph TEXT, revision INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS changes (revision INTEGER PRIMARY KEY, request_id TEXT UNIQUE, signature TEXT, payload TEXT)')
            db.execute('INSERT OR IGNORE INTO state VALUES (1,?,?,0)', (digest(self.original), json.dumps(self.original)))
            db.commit()  # An empty valid sidecar survives a rejected first edit.
            db.execute('BEGIN IMMEDIATE')
            state = self._state(db)
            receipt = db.execute('SELECT signature FROM changes WHERE request_id=?', (command['request_id'],)).fetchone()
            if receipt:
                if receipt['signature'] != signature:
                    raise EditConflict('This request ID was already used for another change')
                return state
            if command['revision'] != state['revision']:
                raise EditConflict('This graph was edited elsewhere. Reload manual changes before saving again.')
            before = state['graph']; graph = copy.deepcopy(before)
            action = command['action']; kind = command.get('entity'); identifier = command.get('id')
            if action == 'revert':
                event = next((e for e in state['changes'] if e['revision'] == command.get('change_revision')), None)
                if event is None:
                    raise ValueError('Manual change not found')
                # Compare-and-swap each affected record. Never discard later edits.
                for change in event['items']:
                    collection = graph['nodes' if change['entity'] == 'concept' else 'edges']
                    current = next((r for r in collection if r['id'] == change['id']), None)
                    if event['action'] == 'contribute' and change['entity'] == 'concept' and change['action'] == 'add':
                        removed_edges = {i['id'] for i in event['items'] if i['entity'] == 'relationship' and i['action'] == 'add'}
                        # Undo this student's relationship without deleting later uses of its concept.
                        if any(e['id'] not in removed_edges and change['id'] in
                               {e['source'], e['target'], *(p['node'] for p in e.get('participants', []))}
                               for e in graph['edges']):
                            continue
                    if current != change['after']:
                        raise EditConflict('A later change affects this item. Revert that later change first.')
                    collection[:] = [r for r in collection if r['id'] != change['id']]
                    if change['before'] is not None:
                        collection.append(copy.deepcopy(change['before']))
            elif action == 'contribute':
                # Internal validated publication: one atomic, reversible graph change.
                additions, edge = copy.deepcopy(command['nodes']), copy.deepcopy(command['edge'])
                existing = {n['id'] for n in graph['nodes']}
                if (len(additions) > 1 or edge.get('origin') != 'student'
                        or any(n.get('origin') != 'student' for n in additions)
                        or not ({edge['source'], edge['target']} & existing)
                        or edge['source'] == edge['target']):
                    raise ValueError('A student contribution must connect to the existing graph')
                graph['nodes'].extend(additions)
                graph['edges'].append(edge)
            else:
                if kind not in {'concept', 'relationship'} or action not in {'add', 'edit', 'delete'}:
                    raise ValueError('Choose a valid concept or relationship action')
                collection = graph['nodes' if kind == 'concept' else 'edges']
                current = next((r for r in collection if r['id'] == identifier), None)
                data = copy.deepcopy(command.get('values') or {})
                fields = NODE_FIELDS if kind == 'concept' else EDGE_FIELDS
                if set(data) - fields:
                    raise ValueError('Unsupported editable fields: ' + ', '.join(sorted(set(data) - fields)))
                for key, value in data.items():
                    if key == 'participants':
                        if not isinstance(value, list) or len(value) > 100:
                            raise ValueError('Participants must be a list of at most 100 entries')
                    elif not isinstance(value, str) or len(value) > (500 if key in {'label', 'source', 'target'} else 10000):
                        raise ValueError('Enter bounded text for ' + key)
                    else:
                        data[key] = value.strip()
                if action != 'add' and current is None:
                    raise ValueError('The selected item no longer exists')
                if action == 'delete':
                    collection.remove(current)
                    if kind == 'concept':
                        graph['edges'] = [e for e in graph['edges'] if identifier not in
                                          {e['source'], e['target'], *(p['node'] for p in e.get('participants', []))}]
                else:
                    if action == 'add':
                        row = dict(id=('manual_concept_' if kind == 'concept' else 'manual_relationship_') + uuid.uuid4().hex,
                                   origin='manual', **({'kind': 'concept'} if kind == 'concept' else {}), **data)
                    else:
                        row = {**current, **data}
                    if any(not row.get(k) for k in ({'label', 'definition'} | ({'source', 'target'} if kind == 'relationship' else set()))):
                        raise ValueError('Name and definition are required; relationships also need both endpoints')
                    if action == 'edit' and row != current and kind == 'relationship':
                        # Generated paraphrases/support must not claim to verify a new professor assertion.
                        if set(data) - {'evidence'}:
                            for key in ('link_reading', 'intended_fact', 'supporting_evidence', 'evidence_start', 'evidence_end'):
                                row.pop(key, None)
                            row['origin'] = 'manual'
                            row['verification_basis'] = 'professor_edit'
                    if action == 'add':
                        collection.append(row)
                    else:
                        collection[collection.index(current)] = row
            validate(graph)
            items = differences(before, graph)
            if not items:
                raise ValueError('No changes to save')
            # Restore original order and quality metadata when all edits have been undone.
            if not differences(self.original, graph):
                graph = copy.deepcopy(self.original)
            else:
                graph.pop('quality', None)
                graph['_manual'] = True
            revision = state['revision'] + 1
            event = dict(revision=revision, action=action, entity=kind, id=identifier,
                         timestamp=datetime.now(timezone.utc).isoformat(), professor=actor,
                         reason=command.get('reason', ''), reverts=command.get('change_revision') if action == 'revert' else None,
                         affected_relationships=affected(before, graph), items=items)
            db.execute('UPDATE state SET graph=?,revision=? WHERE id=1', (json.dumps(graph), revision))
            db.execute('INSERT INTO changes VALUES (?,?,?,?)', (revision, command['request_id'], signature, json.dumps(event)))
            db.commit()
            return dict(graph=graph, original=self.original, revision=revision, changes=[*state['changes'], event], edited=graph != self.original)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
