"""Knowledge denominators, version transfer, adaptive selection and run summaries."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch

from pipeline.knowledge import metrics, fact_keys
from pipeline.quiz import QuizSession
from pipeline.student_store import StudentStore
from tests import test_professor as fixtures


class KnowledgeFlowTests(unittest.TestCase):
    setUp = fixtures.ProfessorTests.setUp
    new_client = fixtures.ProfessorTests.new_client
    post = fixtures.ProfessorTests.post
    command = fixtures.ProfessorTests.command

    def report(self, student=None, run=None):
        response = self.client.get('/api/professor/runs/'+(run or self.topic['id'])+'/knowledge',
                                   params={'student_id': student or self.student})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_assistance_is_not_mastery_and_student_state_survives_restart(self):
        other = self.post('students', dict(name='Other'))['id']
        state = self.command('start')
        state = self.command('hint', state)
        state = self.command('reveal', state)
        self.assertEqual(self.report()['selected']['metrics']['assessed'], 0)
        state = self.command('answer', state, text='Water enters soil.')
        self.assertEqual(state['state']['edge_status'], {'entry': 'related'})
        report = self.report()
        self.assertEqual(report['selected']['metrics']['knowledge_coverage'], 0)
        self.assertEqual(report['selected']['metrics']['assessment_coverage'], 100)
        self.assertEqual(report['selected']['metrics']['assisted_score'], 100)
        self.assertIsNone(report['selected']['metrics']['independent_score'])
        self.assertEqual(self.report(other)['knowledge'], {})
        self.client = self.new_client()
        self.assertEqual(self.report()['knowledge'], report['knowledge'])
        retry = self.command('start')
        self.assertEqual(retry['state']['edge_status'], {'entry': 'related'})
        correct = self.command('answer', retry, text='Water enters soil.')
        self.assertEqual(correct['state']['edge_status'], {'entry': 'match'})
        report = self.report()
        self.assertEqual(report['selected']['metrics']['knowledge_coverage'], 100)
        self.assertEqual(report['overlay'][0]['known'], 1)
        self.assertEqual(report['overlay'][0]['assessed'], 1)
        self.assertEqual(report['overlay'][0]['students'], 2)
        self.assertEqual(report['averages']['knowledge_coverage'], {'value': 50, 'n': 2})
        self.assertEqual(report['averages']['independent_score'], {'value': 100, 'n': 1})
        self.assertEqual([p['knowledge_coverage'] for p in report['selected']['progress']], [0, 100])
        self.assertEqual(self.command('next', correct)['state']['completed'], True)
        self.post('quiz', dict(action='start', request_id=str(uuid.uuid4()), student_id=self.student,
                              run_id=self.topic['id']), 422)
        review = self.command('start', review_mode=True)
        self.assertEqual(StudentStore(self.db).session(review['id'])['checkpoint']['question']['target_ids'], ['entry'])

    def test_version_transfer_is_exact_and_preserves_provenance_and_history(self):
        state = self.command('start')
        self.command('answer', state, text='Water enters soil.')
        run = fixtures.write_run(self.runs, name='run_02', timestamp='2026-10-30T12:00:00+00:00')
        path = run / 'artifacts/graph.json'
        graph = json.loads(path.read_text())
        graph['edges'][0]['id'] = 'new-id'
        graph['edges'].append(dict(graph['edges'][0], id='changed', conditions='only during rain'))
        path.write_text(json.dumps(graph))
        newest = self.client.get('/api/professor/catalog').json()['topics'][0]
        report = self.report(run=newest['id'])
        self.assertEqual(set(report['knowledge']), {'new-id'})
        self.assertTrue(report['knowledge']['new-id']['transferred'])
        self.assertEqual(report['knowledge']['new-id']['source_run_id'], self.topic['id'])
        self.assertEqual(report['selected']['metrics']['knowledge_coverage'], 50)
        self.assertIsNone(report['selected']['metrics']['average_score'])
        self.assertEqual(report['selected']['progress'][0]['label'], 'Transferred baseline')
        self.client = self.new_client()
        self.assertEqual(self.report(run=newest['id'])['knowledge'], report['knowledge'])
        self.assertEqual(len(StudentStore(self.db).history(self.student)), 1)
        self.assertEqual(self.report()['selected']['metrics']['knowledge_coverage'], 100)

    def test_results_missing_metrics_and_recorded_stage_durations(self):
        endpoint = '/api/professor/runs/'+self.topic['id']+'/results'
        data = self.client.get(endpoint).json()
        self.assertIsNone(data['duration'])
        self.assertIsNone(data['accepted'])
        self.assertIsNone(data['original'])
        self.assertEqual(data['nodes'], 2)
        (self.run/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in [
            dict(stage='extraction', event='stage.started', elapsed_seconds=1),
            dict(stage='extraction', event='stage.completed', data={'duration_seconds': 3}),
            dict(stage='debate', event='stage.started', elapsed_seconds=4),
            dict(stage='debate', event='stage.failed', elapsed_seconds=6)]))
        (self.run/'statistics.json').write_text(json.dumps(dict(debate=dict(accepted=0, rejected=2))))
        (self.run/'input.txt').write_text('Original <text>')
        (self.run/'reconstruction.txt').write_text('Rebuilt text')
        data = self.client.get(endpoint).json()
        steps = {s['name']: s for s in data['steps']}
        self.assertEqual(steps['extraction']['duration'], 3)
        self.assertEqual(steps['debate']['duration'], 2)
        self.assertEqual(steps['debate']['status'], 'failed')
        self.assertEqual(data['accepted'], 0)
        self.assertEqual(data['original'], 'Original <text>')


class LearningMathTests(unittest.TestCase):
    def graph(self):
        return dict(nodes=[dict(id=k, label=k, definition=k, kind='concept') for k in 'abcdef'],
                    edges=[dict(id=k, source=a, target=b, label='links', origin='document')
                           for k,a,b in [('ab','a','b'),('bc','b','c'),('de','d','e'),('ef','e','f')]])

    def test_metrics_separate_connectivity_concentration_and_unassessed(self):
        graph = self.graph()
        facts = {k: dict(mark='match', helped=False) for k in ['ab','bc','de']}
        groups = [dict(id='one', title='One', facts=['ab','bc']), dict(id='two', title='Two', facts=['de','ef'])]
        m = metrics(graph, facts, groups=groups)
        self.assertEqual(m['knowledge_coverage'], 75)
        self.assertEqual(m['assessment_coverage'], 75)
        self.assertEqual(m['connected_understanding'], 60)
        self.assertEqual(m['mastered_components'], 2)
        self.assertEqual(m['isolated_mastered_concepts'], 0)
        self.assertEqual(m['concentration'], .556)
        self.assertEqual(m['unassessed'], 1)
        self.assertIsNone(m['average_score'])
        self.assertEqual([t['knowledge_coverage'] for t in m['topics']], [100, 50])
        facts['ef'] = dict(mark='conflict', helped=False)
        updated = metrics(graph, facts, groups=groups)
        self.assertEqual(updated['assessment_coverage'], 100)
        self.assertEqual(updated['knowledge_coverage'], 75)
        self.assertEqual(updated['topics'][1]['assessed_score'], 50)
        empty = metrics(dict(nodes=[], edges=[]), {})
        self.assertIsNone(empty['knowledge_coverage'])
        self.assertIsNone(empty['connected_understanding'])
        self.assertIsNone(empty['concentration'])

    def test_fact_identity_rejects_reversal_ambiguity_modality_and_definition_changes(self):
        graph = self.graph()
        original = fact_keys(graph)['ab']
        for changes in [dict(source='b', target='a'), dict(modality='may'), dict(conditions='when wet'), dict(definition='different')]:
            modified = copy.deepcopy(graph);modified['edges'][0].update(changes)
            self.assertNotEqual(original, fact_keys(modified)['ab'])
        graph['edges'].append(dict(graph['edges'][0], id='duplicate'))
        self.assertNotIn('ab', fact_keys(graph))
        self.assertNotIn('duplicate', fact_keys(graph))

    def test_adaptive_questions_skip_independent_and_bridge_known_to_unknown(self):
        graph = self.graph()
        def question(focus, ids, number, previous, request, fallback):
            return dict(text='Explain.', examiner_material=dict(facts=[dict(id=k) for k in ids]))
        with patch('pipeline.quiz_examiner.QuizExaminer.question', side_effect=question):
            quiz = QuizSession(graph, uuid.uuid4(), None, focus_id='a', adaptive=True,
                prior_knowledge={'ab': dict(mark='match', helped=False), 'de': dict(mark='related', helped=False),
                                 'ef': dict(mark='match', helped=True)})
            self.assertEqual(quiz.question['target_ids'], ['bc'])
            self.assertEqual(quiz.focus, 'b')
            self.assertEqual(quiz.independent, {'ab'})
            self.assertEqual(quiz.edge_status['ef'], 'related')
            restored = QuizSession.restore(graph, None, quiz.checkpoint())
            self.assertTrue(restored.adaptive)
            self.assertEqual(restored.independent, {'ab'})
            next_q = restored._question(2)
            self.assertNotIn('ab', next_q['target_ids'])
            self.assertIn(next_q['target_ids'][0], ['de','ef'])


if __name__ == '__main__':
    unittest.main()
