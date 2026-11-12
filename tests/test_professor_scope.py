"""Topic scopes preserve source identity, exact denominators, and durable evidence."""
import json
import unittest
import uuid

from tests import test_professor as fixtures
from pipeline.student_store import StudentStore
from pipeline.professor_scope import union_graph


class ScopeTests(unittest.TestCase):
    setUp = fixtures.ProfessorTests.setUp
    new_client = fixtures.ProfessorTests.new_client
    post = fixtures.ProfessorTests.post
    command = fixtures.ProfessorTests.command

    def scope(self, **params):
        response = self.client.get('/api/professor/scope', params={'student_id': self.student, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def add_topic(self, title='overlap', conditions=None, name='run_01', timestamp='2026-10-30T12:00:00+00:00'):
        run = fixtures.write_run(self.runs, topic=title, name=name, timestamp=timestamp)
        if conditions:
            file = run/'artifacts/graph.json'
            graph = json.loads(file.read_text())
            graph['edges'][0]['conditions'] = conditions
            file.write_text(json.dumps(graph))
        catalog = self.client.get('/api/professor/catalog').json()
        return next(r for r in catalog['versions'] if r['title'] == title and r['run_name'] == name)

    def begin(self, run, **kwargs):
        return self.post('quiz', dict(action='start', request_id=str(uuid.uuid4()), student_id=self.student,
                                     run_id=run, **kwargs))

    def test_overlap_counts_once_but_keeps_all_sources_and_topic_rows(self):
        self.add_topic()
        data = self.scope()
        self.assertEqual(data['unique_relationships'], 1)
        self.assertEqual(data['source_relationships'], 2)
        self.assertEqual(len(data['graph']['edges'][0]['sources']), 2)
        self.assertEqual(len(data['topics']), 2)
        self.assertEqual(data['selected']['categories']['unassessed'], 1)
        self.assertIsNone(data['selected']['metrics']['average_score'])
        # Provenance quotes must not prevent de-duplication, qualifications must.
        other = self.add_topic('qualified', 'only during rain')
        self.assertEqual(self.scope()['unique_relationships'], 2)
        response = self.client.get('/api/professor/scope', params={'topic':other['topic_key'], 'run_id':self.topic['id']})
        self.assertEqual(response.status_code, 422)

    def test_latest_version_only_and_history_keeps_earlier_versions(self):
        first = self.command('start')
        self.command('answer', first, text='Water enters soil.')
        new = self.add_topic('water', name='run_02')
        data = self.scope()
        self.assertEqual([r['id'] for r in data['runs']], [new['id']])
        self.assertEqual(data['selected']['metrics']['knowledge_coverage'], 100)
        self.assertIsNone(data['selected']['metrics']['average_score'])
        self.assertEqual(data['history'][0]['run_id'], self.topic['id'])
        self.assertFalse(data['history'][0]['included_in_metrics'])
        old = self.scope(topic=self.topic['topic_key'], run_id=self.topic['id'])
        self.assertEqual(old['selected']['metrics']['average_score'], 100)
        self.assertTrue(old['history'][0]['included_in_metrics'])
        self.client = self.new_client()
        restored = self.client.get('/api/professor/sessions/'+first['id']).json()
        self.assertEqual(restored['run_id'], self.topic['id'])
        self.assertEqual(restored['student_id'], self.student)

    def test_earned_mastery_survives_assisted_review_and_corrections_are_authoritative(self):
        overlap = self.add_topic()
        first = self.command('start')
        self.command('answer', first, text='Water enters soil.')
        second = self.begin(overlap['id'], review_mode=True)
        second = self.command('hint', second)
        self.command('answer', second, text='Water enters soil.')
        data = self.scope()
        self.assertEqual(data['selected']['categories']['assisted_correct'], 0)
        self.assertEqual(data['selected']['categories']['independent'], 1)
        self.assertEqual(data['selected']['metrics']['independent_answers'], 1)
        self.assertEqual(data['selected']['metrics']['assisted_answers'], 1)
        answer = StudentStore(self.db).answers(second['id'])[0]
        self.post('answers/'+answer['id']+'/override', dict(marks={'entry':'conflict'}, feedback='Corrected', reason='Professor review'))
        self.client = self.new_client()
        current = self.scope()
        self.assertEqual(current['selected']['categories']['independent'], 1)
        earned = StudentStore(self.db).answers(first['id'])[0]
        self.post('answers/'+earned['id']+'/override', dict(marks={'entry':'conflict'}, feedback='Credit corrected', reason='Review'))
        current = self.scope()
        self.assertEqual(current['selected']['categories']['incorrect'], 1)
        self.assertEqual(len(current['history']), 2)
        self.assertEqual(len(StudentStore(self.db).answers(second['id'])[0]['overrides']), 1)

    def test_all_topic_quiz_does_not_repeat_independently_known_overlap(self):
        overlap = self.add_topic()
        first = self.command('start')
        self.command('answer', first, text='Water enters soil.')
        data = self.scope()
        self.assertEqual(data['recommendations'], [])
        self.post('quiz', dict(action='start', request_id=str(uuid.uuid4()), student_id=self.student,
                              run_id=overlap['id'], scope_all=True), 422)
        # Independent exact-match mastery also carries into single-topic quizzes.
        self.post('quiz', dict(action='start', request_id=str(uuid.uuid4()), student_id=self.student,
                              run_id=overlap['id']), 422)
        second = self.begin(overlap['id'], review_mode=True)
        self.assertEqual(second['run_id'], overlap['id'])

    def test_class_denominators_and_student_breakdown_are_separate(self):
        self.post('students', {'name':'Unassessed learner'})
        state = self.command('start')
        self.command('answer', state, text='Water enters soil.')
        data = self.scope()
        self.assertEqual(data['averages']['knowledge_coverage'], {'value':50, 'n':2})
        self.assertEqual(data['averages']['average_score'], {'value':100, 'n':1})
        self.assertEqual(data['topics'][0]['knowledge_coverage'], 100)
        self.assertEqual(data['class_topics'][0]['knowledge_coverage'], 50)
        self.assertEqual(data['overlay'][0]['known'], 1)
        self.assertEqual(data['overlay'][0]['assessed'], 1)
        self.assertEqual(data['overlay'][0]['students'], 2)

    def test_all_topic_quiz_keeps_pinned_progress_on_resume_and_corrections(self):
        learned = self.command('start')
        self.command('answer', learned, text='Water enters soil.')
        run = fixtures.write_run(self.runs, topic='overlap')
        path = run/'artifacts/graph.json'
        graph = json.loads(path.read_text())
        graph['edges'].append(dict(graph['edges'][0], id='rain', conditions='only in rain'))
        path.write_text(json.dumps(graph))
        topic = next(r for r in self.client.get('/api/professor/catalog').json()['topics'] if r['title']=='overlap')
        quiz = self.begin(topic['id'], scope_all=True)
        self.assertEqual(quiz['state']['edge_status']['entry'], 'match')
        pinned = StudentStore(self.db).session(quiz['id'])['checkpoint']['scope_run_ids']
        self.assertEqual(set(pinned), {self.topic['id'], topic['id']})
        newer = self.add_topic('water', conditions='changed meaning', name='run_02')
        self.client = self.new_client()
        resumed = self.client.get('/api/professor/sessions/'+quiz['id']).json()
        self.assertEqual(resumed['state']['edge_status']['entry'], 'match')
        hinted = self.command('hint', resumed)
        self.assertEqual(hinted['state']['edge_status']['entry'], 'match')
        self.assertEqual(hinted['scope_run_ids'], pinned)
        self.assertNotIn(newer['id'], hinted['scope_run_ids'])
        answer = StudentStore(self.db).answers(learned['id'])[0]
        self.post('answers/'+answer['id']+'/override', dict(marks={'entry':'conflict'}, feedback='Corrected', reason='Review'))
        corrected = self.client.get('/api/professor/sessions/'+quiz['id']).json()
        self.assertEqual(corrected['state']['edge_status']['entry'], 'conflict')

    def test_graph_and_pipeline_views_are_read_only_and_missing_metrics_remain_null(self):
        before = StudentStore(self.db).history()
        for mode in ('source','student','class'):
            response = self.client.get('/professor/scope-graph', params={'mode':mode,'student_id':self.student})
            self.assertEqual(response.status_code, 200)
            self.assertIn('source', response.text)
        result = self.client.get('/api/professor/runs/'+self.topic['id']+'/results').json()
        self.assertTrue(all(v is None for v in result['validation'].values()))
        self.assertIsNone(result['reconstruction_score'])
        self.assertEqual(self.models.calls, [])
        self.assertEqual(before, StudentStore(self.db).history())
        quality = [dict(chunk_id='one', accepted=2, rejected=1, unresolved=0),
                   dict(chunk_id='two', accepted=1, rejected=0, unresolved=2)]
        (self.run/'artifacts/extraction_quality.json').write_text(json.dumps(quality))
        result = self.client.get('/api/professor/runs/'+self.topic['id']+'/results').json()
        self.assertEqual(result['validation'], dict(relations=None, accepted=3, rejected=1, unresolved=2))
        self.assertEqual(result['validation_records']['chunk_quality'], quality)
        self.assertIsNone(result['reconstruction_score'])
        self.assertEqual(self.models.calls, [])

    def test_legacy_request_signatures_remain_idempotent(self):
        request = dict(action='start', request_id=str(uuid.uuid4()), student_id=self.student, run_id=self.topic['id'])
        first = self.post('quiz', request)
        with StudentStore(self.db).connect() as db:
            signature = db.execute('SELECT signature FROM requests WHERE id=?', (request['request_id'],)).fetchone()['signature']
        self.assertNotIn('scope_all', json.loads(signature))
        replay = self.post('quiz', request)
        self.assertEqual(first['id'], replay['id'])
        self.assertEqual(len(StudentStore(self.db).history(self.student)), 1)


if __name__ == '__main__':
    unittest.main()
