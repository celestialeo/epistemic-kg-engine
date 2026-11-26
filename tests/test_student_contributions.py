"""Contribution workflow at the model boundary; live demo uses actual models."""
import copy
import unittest
import uuid
from tests import test_professor as fixtures
from pipeline.assessment import eligible_fact
from pipeline.contributions import Contributions
from pipeline.student_store import StudentStore


class ContributionModels(fixtures.TeachingModels):
    def __init__(self):
        super().__init__()
        self.claim = dict(statement='Soil stores carbon.', quote='Soil stores carbon.',
            source=dict(name='Soil', definition='Soil', existing_id='soil'),
            target=dict(name='Carbon', definition='A chemical element', existing_id=None),
            relation='stores', definition='Soil can store carbon.', conditions=None, modality=None,
            argument_qualifiers=[])
        self.verdict = dict(reason='Fixture review.', correctness='supported', relevant=True,
            novel=True, educational=True, faithful_to_student=True, duplicate_fact_id=None)
        self.fail_contribution = False
        self.fail_review = False

    def ask(self, role, instruction, payload, schema, entity_id, validator=None):
        if not role.startswith('student_contribution_'):
            return super().ask(role, instruction, payload, schema, entity_id, validator)
        self.calls.append(role)
        if self.fail_contribution: raise RuntimeError('Contribution model unavailable')
        if self.fail_review and not role.endswith('extract'): raise RuntimeError('Review interrupted')
        value = (dict(claims=[self.claim] if 'carbon' in payload['target_passage'].lower() else [])
                 if role.endswith('extract') else self.verdict)
        result = schema.model_validate(copy.deepcopy(value))
        if validator: validator(result)
        return result


class ContributionTests(unittest.TestCase):
    setUp = fixtures.ProfessorTests.setUp
    new_client = fixtures.ProfessorTests.new_client
    post = fixtures.ProfessorTests.post
    command = fixtures.ProfessorTests.command

    def submit(self):
        self.models = ContributionModels()
        state = self.command('start', review_mode=True)
        self.models.claim['source']['existing_id'] = next(n['id'] for n in self.graph()['nodes'] if n['label'].lower() == 'soil')
        state = self.command('answer', state, text='Water enters soil. Soil stores carbon.')
        self.answer_id = state['contribution_answer_id']
        self.session_id = state['id']
        self.assertEqual(state['answer_score'], 100)
        self.assertFalse(any(c.startswith('student_contribution_') for c in self.models.calls))
        return state

    def check(self):
        return self.post('answers/'+self.answer_id+'/contributions/check', {})

    def graph(self):
        return self.client.get('/api/professor/runs/'+self.topic['id']+'/manual-graph').json()['graph']

    def test_publication_persistence_attribution_idempotency_and_undo(self):
        self.submit()
        self.models.claim['source']['existing_id'] = 'untrusted-model-id'
        row = self.check()['contributions'][0]
        self.assertEqual(self.models.calls.count('student_contribution_extract'), 2)
        self.assertEqual(row['status'], 'accepted')
        self.assertTrue(row['published'])
        self.assertEqual(row['student_id'], self.student)
        edge = self.graph()['edges'][-1]
        self.assertEqual(edge['answer_id'], self.answer_id)
        self.assertEqual(edge['origin'], 'student')
        self.assertFalse(eligible_fact(edge))
        self.check()
        self.assertEqual(len(self.graph()['edges']), 2)
        self.client = self.new_client()
        self.assertEqual(len(self.graph()['edges']), 2)
        state = self.client.get('/api/professor/sessions/'+self.session_id).json()
        self.assertFalse(state['graph_review']['changed'])
        self.assertEqual(state['answers'][0]['score'], 100)
        self.command('next', state)
        self.post('contributions/'+row['id']+'/review', dict(action='undo', professor='Teacher', reason='Review correction'))
        self.assertEqual(len(self.graph()['edges']), 1)
        self.assertEqual(len(self.graph()['nodes']), 2)
        self.assertEqual(Contributions(StudentStore(self.db)).rows()[0]['status'], 'undone')

    def test_uncertain_claim_stays_out_until_professor_review(self):
        self.submit(); self.models.verdict['correctness'] = 'uncertain'
        row = self.check()['contributions'][0]
        self.assertEqual(row['status'], 'needs_review')
        self.assertEqual(len(self.graph()['edges']), 1)
        self.post('contributions/'+row['id']+'/review', dict(action='approve', professor='Teacher', reason='Checked supporting source'))
        self.assertEqual(len(self.graph()['edges']), 2)
        self.assertEqual(self.graph()['edges'][-1]['verification_basis'], 'professor_review')

    def test_contribution_failure_preserves_grade_and_can_retry(self):
        self.submit(); self.models.fail_contribution = True
        data = self.check()
        self.assertEqual(data['jobs'][0]['status'], 'needs_review')
        state = self.client.get('/api/professor/sessions/'+self.session_id).json()
        self.assertEqual(state['answers'][0]['score'], 100)
        self.models.fail_contribution = False
        self.assertEqual(self.check()['contributions'][0]['status'], 'accepted')

    def test_false_irrelevant_and_unfaithful_claims_are_not_published(self):
        self.submit()
        for field, value, expected in [('correctness','contradicted','rejected'),
                ('relevant',False,'rejected'), ('educational',False,'rejected'),
                ('faithful_to_student',False,'needs_review')]:
            with self.subTest(field=field):
                with StudentStore(self.db).connect() as db:
                    db.execute('DELETE FROM contributions')
                    db.execute("UPDATE contribution_jobs SET status='pending'")
                original = self.models.verdict[field]; self.models.verdict[field] = value
                self.assertEqual(self.check()['contributions'][0]['status'], expected)
                self.assertEqual(len(self.graph()['edges']), 1)
                self.models.verdict[field] = original

    def test_interrupted_review_is_visible_and_retryable_after_restart(self):
        self.submit(); self.models.fail_review = True
        row = self.check()['contributions'][0]
        self.assertEqual(row['status'], 'needs_review')
        self.assertIn('Review interrupted', row['validation_error'])
        self.client = self.new_client(); self.models.fail_review = False
        self.assertEqual(self.check()['contributions'][0]['status'], 'accepted')
        self.assertEqual(self.models.calls.count('student_contribution_extract'), 2)
        self.assertEqual(StudentStore(self.db).answers()[0]['score'], 100)

    def test_exact_duplicate_is_blocked_even_if_model_misses_it(self):
        state = self.submit(); self.check()
        state = self.command('next', state)
        state = self.command('answer', state, text='Water enters soil. Soil stores carbon.')
        self.answer_id = state['contribution_answer_id']
        data = self.check()
        self.assertEqual([r['status'] for r in data['contributions']], ['accepted','duplicate'])
        self.assertEqual(len(self.graph()['edges']), 2)

    def test_semantic_duplicate_and_invalid_endpoint_never_publish(self):
        self.submit(); self.models.verdict.update(novel=True, duplicate_fact_id='entry')
        self.assertEqual(self.check()['contributions'][0]['status'], 'duplicate')
        with StudentStore(self.db).connect() as db:
            db.execute('DELETE FROM contributions'); db.execute("UPDATE contribution_jobs SET status='pending'")
        self.models.verdict.update(novel=True, duplicate_fact_id=None)
        self.models.claim['source']['name'] = 'stores'
        self.assertEqual(self.check()['contributions'][0]['status'], 'needs_review')
        self.assertEqual(len(self.graph()['edges']), 1)

    def test_forged_quote_is_unresolved_and_no_publication_route_bypass(self):
        self.submit(); self.models.claim['quote'] = 'An invented quote'
        self.assertEqual(self.check()['jobs'][0]['status'], 'needs_review')
        self.assertEqual(len(self.graph()['edges']), 1)
        self.post('runs/'+self.topic['id']+'/manual-graph', dict(action='contribute',
            request_id=str(uuid.uuid4()), revision=0), expected=422)

    def test_undo_retains_concept_reused_by_later_contributions(self):
        state = self.submit(); first = self.check()['contributions'][0]
        state = self.command('next', state)
        state = self.command('answer', state, text='Water enters soil. Water dissolves carbon.')
        self.answer_id = state['contribution_answer_id']
        self.models.claim.update(statement='Water dissolves carbon.', quote='Water dissolves carbon.', relation='dissolves')
        self.models.claim['source'] = dict(name='water',definition='Water',existing_id=None)
        second = self.check()['contributions'][-1]
        self.assertEqual(second['status'], 'accepted')
        self.post('contributions/'+first['id']+'/review', dict(action='undo', professor='Teacher', reason='Undo first only'))
        graph = self.graph()
        self.assertEqual(len(graph['nodes']), 3)
        self.assertIn(second['edge_id'], {e['id'] for e in graph['edges']})
        self.assertNotIn(first['edge_id'], {e['id'] for e in graph['edges']})


if __name__ == '__main__': unittest.main()
