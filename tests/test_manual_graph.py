"""Manual graph persistence, concurrency, audit/reversion and assessment semantics."""
from concurrent.futures import ThreadPoolExecutor
import json
import uuid
import unittest

from pipeline.explorer import load_snapshot
from pipeline.graph_edits import ManualGraph, EditConflict, semantics
from pipeline.professor import run_identity
from pipeline.student_store import StudentStore
from tests import test_professor as fixtures


class ManualGraphTests(unittest.TestCase):
    setUp = fixtures.ProfessorTests.setUp
    new_client = fixtures.ProfessorTests.new_client
    post = fixtures.ProfessorTests.post
    command = fixtures.ProfessorTests.command

    def state(self):
        response = self.client.get('/api/professor/runs/' + self.topic['id'] + '/manual-graph')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def change(self, action, entity=None, id=None, values=None, expected=200, **extra):
        return self.post('runs/' + self.topic['id'] + '/manual-graph', dict(
            action=action, entity=entity, id=id, values=values or {},
            revision=self.state()['revision'], request_id=str(uuid.uuid4()), **extra), expected)

    def knowledge(self):
        return self.client.get('/api/professor/runs/' + self.topic['id'] + '/knowledge',
                               params={'student_id': self.student}).json()

    def test_crud_original_restart_audit_and_new_runs(self):
        initial = self.state()
        original_bytes = (self.run / 'artifacts/graph.json').read_bytes()
        state = self.change('add', 'concept', values={'label': 'Cloud', 'definition': 'Visible water droplets'},
                            professor='Dr Example', reason='Add missing concept')
        concept = state['graph']['nodes'][-1]
        existing = initial['graph']['nodes'][0]['id']
        state = self.change('add', 'relationship', values={'source': existing, 'target': concept['id'],
                            'label': 'forms', 'definition': 'Combines into droplets', 'conditions': 'when cooled'})
        edge = state['graph']['edges'][-1]
        self.change('edit', 'concept', concept['id'], {'label': 'Cloud droplets', 'definition': 'Condensed water'})
        state = self.change('edit', 'relationship', edge['id'], {'label': 'condenses into'})
        self.assertEqual(len(state['changes']), 4)
        self.assertEqual(state['changes'][0]['professor'], {'name': 'Dr Example', 'source': 'self_reported'})
        self.assertIn('timestamp', state['changes'][0])
        self.assertIsNone(state['changes'][0]['items'][0]['before'])
        self.assertEqual(state['changes'][0]['items'][0]['after']['label'], 'Cloud')
        self.assertEqual((self.run / 'artifacts/graph.json').read_bytes(), original_bytes)
        snapshot = load_snapshot(self.run)
        self.assertEqual(run_identity(snapshot), self.topic['id'])
        self.assertEqual(snapshot.graph, state['graph'])
        self.assertEqual(snapshot.original_graph, initial['original'])
        original = self.client.get('/professor/graph/' + self.topic['id'] + '?version=original').text
        edited = self.client.get('/professor/graph/' + self.topic['id']).text
        self.assertNotIn('Cloud droplets', original)
        self.assertIn('Cloud droplets', edited)
        self.client = self.new_client()
        self.assertEqual(self.state(), state)
        self.assertEqual(len(self.client.get('/api/professor/catalog').json()['versions']), 1)
        results = self.client.get('/api/professor/runs/' + self.topic['id'] + '/results').json()
        self.assertEqual((results['nodes'], results['edges']), (3, 2))
        scope = self.client.get('/api/professor/scope').json()
        self.assertEqual(scope['unique_relationships'], 2)
        later = fixtures.write_run(self.runs, name='run_02', timestamp='2026-11-20T12:00:00+00:00')
        self.assertEqual(len(load_snapshot(later).graph['nodes']), 2)
        self.assertFalse((later / 'manual_graph.sqlite3').exists())
        self.assertEqual(load_snapshot(self.run).graph, state['graph'])

    def test_cascade_deletion_reversion_and_revert_of_revert_keep_audit(self):
        initial = self.state()
        node = initial['graph']['nodes'][0]['id']
        state = self.change('delete', 'concept', node)
        self.assertEqual(len(state['changes'][0]['items']), 2)
        self.assertEqual(state['graph']['edges'], [])
        state = self.change('revert', change_revision=1)
        self.assertEqual(state['graph'], initial['graph'])
        self.assertFalse(state['edited'])
        self.assertEqual(state['changes'][1]['reverts'], 1)
        state = self.change('revert', change_revision=2)
        self.assertEqual(state['graph']['edges'], [])
        self.assertEqual(len(state['changes']), 3)

    def test_conflicts_idempotency_and_validation_are_atomic(self):
        first = self.state()
        path = 'runs/' + self.topic['id'] + '/manual-graph'
        body = dict(action='edit', entity='relationship', id='entry', values={'conditions': 'during rain'},
                    revision=0, request_id=str(uuid.uuid4()))
        state = self.post(path, body)
        self.assertEqual(self.post(path, body)['revision'], 1)
        self.post(path, {**body, 'values': {'conditions': 'at night'}}, 409)
        self.post(path, {**body, 'request_id': str(uuid.uuid4())}, 409)
        self.change('edit', 'relationship', 'entry', {'conditions': 'after rain'})
        self.change('revert', change_revision=1, expected=409)
        self.assertEqual(self.state()['revision'], 2)
        self.change('revert', change_revision=2)
        self.change('revert', change_revision=1)
        self.assertEqual(self.state()['graph'], first['graph'])
        for values in [{'source': 'missing'}, {'id': 'different'}, {'label': ' '}, {'participants': [{'node': 'missing'}]}]:
            before = self.state()
            self.change('edit', 'relationship', 'entry', values, expected=422)
            self.assertEqual(self.state(), before)
        self.change('add', 'concept', values={'label': first['graph']['nodes'][0]['label'], 'definition': 'duplicate'}, expected=422)
        response = self.client.post('/api/professor/' + path, json=body, headers={'origin': 'https://untrusted.example'})
        self.assertEqual(response.status_code, 403)

    def test_invalid_first_edit_leaves_valid_readable_state(self):
        self.change('edit', 'concept', 'missing', {'label': 'x'}, expected=422)
        self.assertEqual(self.state()['revision'], 0)
        self.client = self.new_client()
        self.assertEqual(self.state()['revision'], 0)

    def test_two_writers_cannot_overwrite_each_other(self):
        original = self.state()['original']
        def write(label):
            command = dict(action='add', entity='concept', values={'label': label, 'definition': 'A new concept'},
                           revision=0, request_id=str(uuid.uuid4()))
            try:
                return ManualGraph(self.run, original).apply(command)['revision']
            except EditConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(write, ['First concept', 'Second concept']))
        self.assertCountEqual(outcomes, [1, 'conflict'])
        self.assertEqual(len(self.state()['graph']['nodes']), 3)
        self.assertEqual(len(self.state()['changes']), 1)

    def test_reverting_new_concept_rejects_later_relationship_dependency(self):
        state = self.change('add', 'concept', values={'label': 'Cloud', 'definition': 'Water droplets'})
        node = state['graph']['nodes'][-1]
        self.change('add', 'relationship', values={'label': 'forms', 'definition': 'Combines into droplets',
                    'source': state['graph']['nodes'][0]['id'], 'target': node['id']})
        before = self.state()
        self.change('revert', change_revision=1, expected=422)
        self.assertEqual(self.state(), before)
        self.change('revert', change_revision=2)
        self.change('revert', change_revision=1)
        self.assertFalse(self.state()['edited'])

    def test_legacy_assessments_use_original_semantics_after_edit(self):
        session = self.command('start')
        self.command('answer', session, text='Water enters soil.')
        store = StudentStore(self.db)
        # Simulate a saved assessment written before graph versioning existed.
        with store.connect() as db:
            row = db.execute('SELECT id,question FROM answers').fetchone()
            question = json.loads(row['question']); question.pop('graph_fingerprints')
            db.execute('UPDATE answers SET question=? WHERE id=?', (json.dumps(question), row['id']))
            row = db.execute('SELECT id,checkpoint FROM sessions').fetchone()
            checkpoint = json.loads(row['checkpoint']); checkpoint.pop('graph_snapshot')
            db.execute('UPDATE sessions SET checkpoint=? WHERE id=?', (json.dumps(checkpoint), row['id']))
        self.change('edit', 'relationship', 'entry', {'definition': 'The opposite direction'})
        self.assertEqual(self.knowledge()['knowledge'], {})
        self.assertEqual(store.answers()[0]['graph_changes'], ['entry'])
        self.client = self.new_client()
        response = self.client.get('/api/professor/sessions/' + session['id'])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['answers'][0]['score'], 100)
        self.change('revert', change_revision=1)
        self.assertEqual(self.knowledge()['knowledge']['entry']['mark'], 'match')

    def test_history_flags_meaning_changes_without_rewriting_grades(self):
        session = self.command('start')
        self.command('answer', session, text='Water enters soil.')
        before = StudentStore(self.db).answers()[0]
        self.assertEqual(self.knowledge()['knowledge']['entry']['mark'], 'match')
        self.change('edit', 'relationship', 'entry', {'conditions': 'only during rain'})
        after = StudentStore(self.db).answers()[0]
        for field in ('question', 'result', 'marks', 'score', 'original_score', 'text'):
            self.assertEqual(after[field], before[field])
        self.assertEqual(after['graph_changes'], ['entry'])
        self.assertEqual(self.knowledge()['knowledge'], {})
        self.assertEqual(self.knowledge()['selected']['metrics']['knowledge_coverage'], 0)
        self.assertEqual(len(self.state()['affected_assessments']), 1)
        self.client = self.new_client()
        self.assertEqual(self.knowledge()['knowledge'], {})
        self.change('revert', change_revision=1)
        self.assertEqual(self.knowledge()['knowledge']['entry']['mark'], 'match')
        self.assertEqual(StudentStore(self.db).answers()[0]['graph_changes'], [])

    def test_renaming_endpoint_invalidates_old_question_and_mastery(self):
        session = self.command('start')
        node = self.state()['graph']['nodes'][0]
        self.change('edit', 'concept', node['id'], {'definition': 'A different concept meaning'})
        response = self.client.get('/api/professor/sessions/' + session['id']).json()
        self.assertTrue(response['graph_review']['changed'])
        self.assertEqual(response['graph_review']['affected_question'], ['entry'])
        self.post('quiz', dict(action='answer', session_id=session['id'], question_id=session['state']['question']['id'],
                              text='Water enters soil.', request_id=str(uuid.uuid4())), 409)
        self.assertEqual(StudentStore(self.db).answers(), [])

    def test_new_quiz_uses_edited_meaning_and_historical_evidence_stays_versioned(self):
        self.change('edit', 'relationship', 'entry', {'conditions': 'during rain'})
        session = self.command('start')
        checkpoint = StudentStore(self.db).session(session['id'])['checkpoint']
        self.assertEqual(checkpoint['question']['examiner_material']['facts'][0]['conditions'], 'during rain')
        self.command('answer', session, text='Water enters soil during rain.')
        self.assertEqual(self.knowledge()['knowledge']['entry']['mark'], 'match')
        self.change('revert', change_revision=1)
        self.assertEqual(self.knowledge()['knowledge'], {})
        self.assertEqual(StudentStore(self.db).answers()[0]['score'], 100)
        # A new generated run never borrows an edited meaning simply because IDs match.
        later = fixtures.write_run(self.runs, name='run_02', timestamp='2026-11-20T12:00:00+00:00')
        catalog = self.client.get('/api/professor/catalog').json()
        latest = next(r for r in catalog['versions'] if r['run_name'] == 'run_02')
        self.assertEqual(StudentStore(self.db).knowledge(self.student, latest['id']), {})

    def test_nonsemantic_edit_keeps_valid_mastery(self):
        session = self.command('start')
        self.command('answer', session, text='Water enters soil.')
        self.change('edit', 'relationship', 'entry', {'evidence': 'A corrected source reference'})
        self.assertEqual(self.knowledge()['knowledge']['entry']['mark'], 'match')
        self.assertEqual(StudentStore(self.db).answers()[0]['graph_changes'], [])

    def test_deletion_restores_historical_session_and_retains_pending_answer(self):
        session = self.command('start')
        self.models.fail = True
        request = dict(action='answer', session_id=session['id'], question_id=session['state']['question']['id'],
                       text='Water enters soil.', request_id=str(uuid.uuid4()))
        self.post('quiz', request, 503)
        self.change('delete', 'concept', self.state()['graph']['nodes'][0]['id'])
        self.client = self.new_client()
        historical = self.client.get('/api/professor/sessions/' + session['id'])
        self.assertEqual(historical.status_code, 200, historical.text)
        self.assertEqual(historical.json()['pending_answers'][0]['text'], request['text'])
        self.models.fail = False
        self.post('quiz', request)
        self.assertEqual(StudentStore(self.db).answers()[0]['score'], 100)
        self.assertEqual(self.knowledge()['knowledge'], {})

    def test_participant_semantics_and_deletion_integrity(self):
        state = self.change('add', 'concept', values={'label': 'Temperature', 'definition': 'Thermal state'})
        node = state['graph']['nodes'][-1]
        self.change('edit', 'relationship', 'entry', {'participants': [{'node': node['id'], 'scope': 'assertion', 'role': 'condition'}]})
        before = semantics(self.state()['graph'])
        state = self.change('edit', 'concept', node['id'], {'definition': 'A specific thermal threshold'})
        self.assertNotEqual(before, semantics(state['graph']))
        self.assertEqual(state['changes'][-1]['affected_relationships'], ['entry'])
        state = self.change('delete', 'concept', node['id'])
        self.assertEqual(state['graph']['edges'], [])
        state = self.change('revert', change_revision=4)
        self.assertEqual(len(state['graph']['edges']), 1)


if __name__ == '__main__':
    unittest.main()
