"""Reviewed-question recovery and durable mastery across normal quizzes."""
import copy
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

from pipeline.knowledge import display_state
from pipeline.models import ModelResponseError, ModelServiceError
from pipeline.quiz import QuizSession
from pipeline.quiz_examiner import QuizExaminer, QuestionGenerationError
from pipeline.student_store import StudentStore
from tests import test_professor as fixtures


def graph():
    return dict(_quiz_approvals={'yellow':{'basis':'Explicit fixture professor approval'}}, nodes=[dict(id=n, label=n.title(), definition=n, kind='concept', origin='document')
                       for n in ('water', 'soil', 'plant')], edges=[
        dict(id='known', source='water', target='soil', label='enters', origin='document'),
        dict(id='document-gap', source='water', target='plant', label='supports', origin='document'),
        dict(id='yellow', source='soil', target='plant', label='feeds', origin='background')])


def generated(focus, ids, *_args):
    return dict(text='Explain the process.', expected_answer='Reference answer.',
                examiner_material=dict(facts=[dict(id=i) for i in ids]))


class ReviewModels:
    def __init__(self, draft, review, audit):
        self.draft, self.review, self.audit = draft, review, audit
        self.calls = []

    def ask(self, role, instruction, payload, schema, entity_id, validator=None):
        self.calls.append((role, instruction, copy.deepcopy(payload), entity_id))
        value = self.draft if role=='quiz_question' else self.audit if ':review-audit:' in entity_id else self.review
        result = schema.model_validate(value)
        try:
            if validator:
                validator(result)
        except ValueError as exc:
            raise ModelResponseError(str(exc)) from exc
        return result


class QuestionRecoveryTests(unittest.TestCase):
    def model(self, actual_leak=False):
        question = ('The missing resource is a dynamic knowledge base. What is the resource?' if actual_leak else
                    'When a model uses external documents, what kind of resource does it access?')
        quote = 'dynamic knowledge base' if actual_leak else 'what kind of resource does it access?'
        draft = dict(question=question, expected_answer='dynamic knowledge base', assessed_fact_ids=['known'],
                     assessment_spec=fixtures.assessment_spec([dict(id='known')], 'component'))
        review = dict(plain_exam_language=False, open_question=True, grounded_in_material=True, specification_aligned=True,
                      reveals_answer=True, answer_leak_quote=quote, reason='Initial disputed review.')
        audit = dict(review, plain_exam_language=True, reveals_answer=actual_leak,
                     answer_leak_quote=quote if actual_leak else '',
                     reason='Requested answer is stated.' if actual_leak else 'The category is a clue, not the answer.')
        return ReviewModels(draft, review, audit)

    def test_disputed_clue_is_audited_before_acceptance(self):
        models = self.model()
        result = QuizExaminer(models, graph()).question('water', ['known'], 1, [], 'test')
        self.assertEqual(result['text'], models.draft['question'])
        self.assertEqual(len(models.calls), 3)
        self.assertIn('disputed_review', models.calls[-1][2])
        self.assertIn('NOT answer leakage', models.calls[-1][1])

    def test_real_answer_leakage_is_not_bypassed_and_repeated_draft_is_rejected(self):
        models = self.model(actual_leak=True)
        with self.assertRaisesRegex(ModelResponseError, 'repeats a rejected draft'):
            QuizExaminer(models, graph()).question('water', ['known'], 1, [], 'test')
        second = models.calls[-1][2]
        self.assertEqual(second['rejected_drafts'], [models.draft['question']])
        self.assertNotEqual(second['revision_strategy'], models.calls[0][2]['revision_strategy'])

    def test_fallback_prefers_document_and_never_asks_green(self):
        calls = []
        def question(focus, ids, *args):
            calls.append(ids)
            if ids == ['document-gap']:
                raise QuestionGenerationError('Rejected document draft')
            return generated(focus, ids, *args)
        with patch.object(QuizExaminer, 'question', side_effect=question):
            session = QuizSession(graph(), uuid.uuid4(), None, adaptive=True,
                prior_knowledge={'known':dict(mark='match', helped=False),
                                 'yellow':dict(mark='match', helped=True)})
        self.assertEqual(calls, [['document-gap'], ['yellow']])
        self.assertEqual(session.question['target_ids'], ['yellow'])
        self.assertEqual(session.asked, {'yellow'})
        self.assertEqual(session.deferred_facts, {'document-gap'})
        self.assertNotIn('document-gap', session.edge_status)
        restored = QuizSession.restore(graph(), None, session.checkpoint())
        self.assertEqual(restored.deferred_facts, session.deferred_facts)

    def test_failed_next_question_does_not_mutate_checkpoint(self):
        with patch.object(QuizExaminer, 'question', side_effect=generated):
            session = QuizSession(graph(), uuid.uuid4(), None, adaptive=True)
        before = copy.deepcopy(session.checkpoint())
        with patch.object(QuizExaminer, 'question', side_effect=QuestionGenerationError('Draft rejected')):
            with self.assertRaises(QuestionGenerationError):
                session._question(2)
        self.assertEqual(before, session.checkpoint())

    def test_service_outage_does_not_retry_other_facts(self):
        with patch.object(QuizExaminer, 'question', side_effect=ModelServiceError('offline')) as generate:
            with self.assertRaises(ModelServiceError):
                QuizSession(graph(), uuid.uuid4(), None, adaptive=True)
        self.assertEqual(generate.call_count, 1)

    def test_green_circle_requires_all_incident_facts_known(self):
        state = display_state(graph(), {'known':dict(mark='match', helped=False)})
        self.assertEqual(state['edge_status']['known'], 'match')
        self.assertEqual(state['node_status']['water'], 'related')
        all_known = display_state(graph(), {e['id']:dict(mark='match', helped=False) for e in graph()['edges']})
        self.assertEqual(set(all_known['node_status'].values()), {'match'})


class DurableMasteryTests(unittest.TestCase):
    setUp = fixtures.ProfessorTests.setUp
    new_client = fixtures.ProfessorTests.new_client
    post = fixtures.ProfessorTests.post
    command = fixtures.ProfessorTests.command

    def test_yellow_becomes_green_in_new_quiz_and_survives_later_review(self):
        first = self.command('start')
        first = self.command('hint', first)
        first = self.command('answer', first, text='Water enters soil.')
        self.assertEqual(first['state']['edge_status']['entry'], 'related')
        self.client = self.new_client()
        second = self.command('start')
        green = self.command('answer', second, text='Water enters soil.')
        self.assertEqual(green['state']['edge_status']['entry'], 'match')
        review = self.command('start', review_mode=True)
        wrong = self.command('answer', review, text='Water never enters soil.')
        self.assertEqual(wrong['answer_score'], 0)
        self.assertEqual(wrong['state']['edge_status']['entry'], 'match')
        self.client = self.new_client()
        facts = StudentStore(self.db).knowledge(self.student, self.topic['id'])
        self.assertEqual(facts['entry']['mark'], 'match')
        self.assertFalse(facts['entry']['helped'])
        report = self.client.get('/api/professor/runs/'+self.topic['id']+'/knowledge',
                                 params={'student_id':self.student}).json()['selected']
        self.assertEqual(report['metrics']['knowledge_coverage'],100)
        self.assertEqual(report['metrics']['average_score'],66.7)
        self.assertEqual([p['knowledge_coverage'] for p in report['progress']],[0,100,100])
        self.post('quiz', dict(action='start',request_id=str(uuid.uuid4()),student_id=self.student,run_id=self.topic['id']),422)
        # Correcting the supporting independent answer revokes that credit,
        # while retaining the original scores, answer text and override audit.
        earned = StudentStore(self.db).answers(second['id'])[0]
        self.post('answers/'+earned['id']+'/override', dict(marks={'entry':'related'}, feedback='Partial', reason='Review'))
        again = self.command('start')
        self.assertNotEqual(again['state']['edge_status']['entry'], 'match')
        self.assertEqual(len(StudentStore(self.db).answers()), 3)

    def test_resume_skips_question_mastered_in_another_quiz_without_model_calls(self):
        waiting = self.command('start')
        other = self.command('start')
        self.command('answer', other, text='Water enters soil.')
        self.client = self.new_client()
        before = len(self.models.calls)
        resumed = self.client.get('/api/professor/sessions/'+waiting['id']).json()
        self.assertTrue(resumed['state']['question_mastered'])
        self.post('quiz',dict(action='answer',request_id=str(uuid.uuid4()),session_id=waiting['id'],
                             question_id=waiting['state']['question']['id'],text='Water enters soil.'),422)
        finished = self.command('next', resumed)
        self.assertTrue(finished['state']['completed'])
        self.assertEqual(len(self.models.calls), before)
        self.assertEqual(StudentStore(self.db).answers(waiting['id']), [])

    def test_question_failure_has_clear_recoverable_error_and_no_saved_attempt(self):
        request = dict(action='start',request_id=str(uuid.uuid4()),student_id=self.student,run_id=self.topic['id'])
        with patch.object(QuizExaminer,'question',side_effect=QuestionGenerationError('Rejected drafts')):
            error = self.post('quiz',request,422)
        self.assertEqual(error['detail']['code'],'question_generation')
        self.assertTrue(error['detail']['progress_unchanged'])
        store = StudentStore(self.db)
        self.assertEqual(store.history(),[])
        self.assertEqual(store.answers(),[])
        result = self.post('quiz',request)
        self.assertEqual(result['student_id'],self.student)
        self.assertEqual(len(store.history()),1)


if __name__=='__main__':
    unittest.main()
