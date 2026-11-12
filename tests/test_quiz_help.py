"""Help prose, precise retries, non-answer hints and validated reveal fallback."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch, Mock

from fastapi.testclient import TestClient
from pipeline.explorer import create_app
from pipeline.models import ModelResponseError, ModelServiceError
from pipeline.quiz_examiner import HelpGenerationError, QuizExaminer, StudentText, validate_help_text
from pipeline.student_store import StudentStore
from tests import test_professor as fixtures
from tests.test_quiz_grading import models_with


def graph():
    return dict(nodes=[dict(id='node_1',label='Water'),dict(id='node_2',label='Soil')],
                edges=[dict(id='edge_1',source='node_1',target='node_2',label='enters',origin='document')])


def question():
    return dict(text='Where does water go?', expected_answer='Water enters soil.', hint_history=[],
                examiner_material=dict(facts=[dict(id='edge_1',source='Water',target='Soil',relation='enters')]))


def approved_hint():
    return dict(grounded_in_material=True,reveals_answer=False,answer_leak_quote='',
                reason='A thinking strategy without stating the answer.')


class HelpValidationTests(unittest.TestCase):
    def test_ordinary_subject_words_and_nonrecord_headings_are_allowed(self):
        for text in (
            'Consider the source of energy and the relationship between temperature and pressure.',
            'Under these conditions, water changes direction at the edge of the surface.',
            'Source: sunlight. Conditions: warm weather.',
            'The coordinates are (1, 2, 3).',
        ):
            with self.subTest(text=text):
                validate_help_text(StudentText(text=text),graph()['nodes'],graph()['edges'])

    def test_internal_identifiers_and_graph_records_get_specific_feedback(self):
        cases=[('See edge_1.','edge_1'),('Check node_987.','node_987'),
               ('source: Water; target: Soil; relation: enters','source'),
               ('{"source":"Water","target":"Soil"}','target'),
               ('("Water", "enters", "Soil")','tuple/list'),
               ('(Water, enters, Soil)','triple'),
               ('Water -> enters -> Soil','arrow'),
               ('Water -[enters]-> Soil','arrow'),
               ('| source | relation | target |\n| Water | enters | Soil |','table'),
               ('The assessed_fact_ids are hidden.','assessed_fact_ids')]
        for text,feedback in cases:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,feedback):
                validate_help_text(StudentText(text=text),graph()['nodes'],graph()['edges'])

    def test_actual_custom_id_is_blocked_but_a_matching_human_label_is_allowed(self):
        nodes=[dict(id='C17',label='Carbon'),dict(id='H2O',label='H2O')]
        with self.assertRaisesRegex(ValueError,'C17'):
            validate_help_text(StudentText(text='Inspect C17.'),nodes,[])
        validate_help_text(StudentText(text='H2O is water.'),nodes,[])

    def test_reveal_allows_source_without_retry_or_fallback(self):
        models=models_with(dict(text='The source of information shifts to the external document.'))
        examiner=QuizExaminer(models,graph())
        result=examiner.help(question(),True,'reveal-test')
        self.assertIn('source',result)
        self.assertEqual(models.client.chat.call_count,1)
        self.assertEqual(examiner.last_help_source,'generated')
        prompt=models.client.chat.call_args.kwargs['messages'][0]['content']
        self.assertNotIn('Never use relationship',prompt)

    def test_reveal_retry_names_the_bad_identifier(self):
        models=models_with(dict(text='Use edge_1.'),dict(text='Water enters soil.'))
        result=QuizExaminer(models,graph()).help(question(),True,'reveal-test')
        self.assertEqual(result,'Water enters soil.')
        self.assertEqual(models.client.chat.call_count,2)
        retry=models.client.chat.call_args.kwargs['messages'][0]['content']
        self.assertIn("Remove internal identifier 'edge_1'",retry)
        self.assertIn('ordinary name',retry)

    def test_hint_accepts_ordinary_words_after_non_disclosure_review(self):
        models=models_with(dict(text='Consider the relationship and the conditions that allow movement.'),approved_hint())
        examiner=QuizExaminer(models,graph())
        result=examiner.help(question(),False,'hint-test')
        self.assertIn('relationship',result)
        self.assertEqual(models.client.chat.call_count,2)
        self.assertEqual(examiner.last_help_source,'generated')

    def test_hint_retry_feedback_is_specific_and_repaired_hint_is_reviewed(self):
        models=models_with(dict(text='Look at node_1.'),dict(text='Think about where a liquid can move.'),approved_hint())
        result=QuizExaminer(models,graph()).help(question(),False,'hint-test')
        self.assertEqual(result,'Think about where a liquid can move.')
        retry=models.client.chat.call_args_list[1].kwargs['messages'][0]['content']
        self.assertIn("Remove internal identifier 'node_1'",retry)
        self.assertEqual(models.client.chat.call_count,3)

    def test_direct_answer_in_hint_is_rejected_without_answer_fallback(self):
        models=models_with(*[dict(text='Remember: water enters soil!')]*3)
        examiner=QuizExaminer(models,graph())
        with self.assertRaises(HelpGenerationError) as error:
            examiner.help(question(),False,'hint-test')
        self.assertEqual(error.exception.action,'hint')
        self.assertNotIn('Water enters soil',str(error.exception))
        self.assertIsNone(examiner.last_help_source)
        self.assertEqual(models.client.chat.call_count,3)
        self.assertIn('complete expected answer',models.client.chat.call_args.kwargs['messages'][0]['content'])

    def test_paraphrased_answer_in_hint_is_rejected_by_review(self):
        outputs=[]
        for hint in ('The liquid moves into the ground.', 'Moisture passes into the earth.', 'The ground receives the liquid.'):
            review=dict(grounded_in_material=True,reveals_answer=True,answer_leak_quote=hint,
                        reason='This states the requested destination and movement.')
            outputs.extend([dict(text=hint),review])
        models=models_with(*outputs)
        with self.assertRaises(HelpGenerationError):
            QuizExaminer(models,graph()).help(question(),False,'hint-test')
        self.assertEqual(models.client.chat.call_count,6)
        retry=models.client.chat.call_args_list[2].kwargs['messages'][0]['content']
        self.assertIn('Remove the answer-disclosing hint passage',retry)

    def test_unavailable_hint_review_does_not_release_unchecked_hint(self):
        models=models_with(dict(text='Think about movement.'),RuntimeError('Model offline'))
        with self.assertRaises(HelpGenerationError):
            QuizExaminer(models,graph()).help(question(),False,'hint-test')
        self.assertEqual(models.client.chat.call_count,2)

    def test_reveal_uses_expected_answer_after_invalid_outputs_or_service_failure(self):
        for outputs in ([dict(text='See edge_1.')]*3,[RuntimeError('Model offline')]):
            with self.subTest(outputs=outputs):
                models=models_with(*outputs)
                examiner=QuizExaminer(models,graph())
                self.assertEqual(examiner.help(question(),True,'reveal-test'),question()['expected_answer'])
                self.assertEqual(examiner.last_help_source,'validated_expected_answer')
                self.assertTrue(any(call.args[0]=='quiz.reveal_fallback' for call in models.trace.emit.call_args_list))
        # A model adapter can also fail before converting its error to Models'
        # exception types. The same explicit-reveal policy applies.
        adapter=Mock()
        adapter.ask.side_effect=RuntimeError('Adapter initialization failed')
        examiner=QuizExaminer(adapter,graph())
        self.assertEqual(examiner.help(question(),True,'reveal-test'),question()['expected_answer'])
        with self.assertRaises(HelpGenerationError):
            examiner.help(question(),False,'hint-test')
        adapter.ask.side_effect=KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            examiner.help(question(),True,'reveal-test')

    def test_unsafe_expected_answer_is_not_exposed_as_fallback(self):
        for expected in ('','   ','See edge_1.','{"source":"Water","target":"Soil"}'):
            with self.subTest(expected=expected):
                examiner=QuizExaminer(models_with(RuntimeError('Offline')),graph())
                with self.assertRaises(HelpGenerationError) as error:
                    examiner.help(dict(question(),expected_answer=expected),True,'reveal-test')
                self.assertEqual(error.exception.action,'reveal')
                self.assertIsNone(examiner.last_help_source)


class HelpPersistenceTests(unittest.TestCase):
    setUp=fixtures.ProfessorTests.setUp
    new_client=fixtures.ProfessorTests.new_client
    post=fixtures.ProfessorTests.post
    command=fixtures.ProfessorTests.command

    def test_failed_hint_changes_nothing_and_reports_help_error_not_save_failure(self):
        state=self.command('start');store=StudentStore(self.db)
        before=copy.deepcopy(store.session(state['id']))
        request=dict(action='hint',request_id=str(uuid.uuid4()),session_id=state['id'],question_id=state['state']['question']['id'])
        with patch.object(self.models,'ask',side_effect=ModelResponseError('Unsafe hint')):
            result=self.post('quiz',request,422)
        self.assertEqual(result['detail']['code'],'hint_generation')
        self.assertNotIn('Assessment could not be saved',result['detail']['message'])
        self.assertEqual(store.session(state['id']),before)
        self.assertEqual(store.pending_answers(state['id']),[])
        self.assertEqual(store.answers(),[])
        recovered=self.post('quiz',request)
        self.assertEqual(recovered['state']['question']['hints'],1)
        self.assertEqual(self.post('quiz',request),recovered)

    def test_fallback_reveal_is_saved_once_and_later_answer_is_assisted(self):
        state=self.command('start');store=StudentStore(self.db)
        request=dict(action='reveal',request_id=str(uuid.uuid4()),session_id=state['id'],question_id=state['state']['question']['id'])
        with patch.object(self.models,'ask',side_effect=ModelServiceError('Offline')):
            revealed=self.post('quiz',request)
            self.assertEqual(self.post('quiz',request),revealed)
        self.assertTrue(revealed['state']['question']['revealed'])
        self.assertEqual(revealed['state']['question']['help_text'],'Water enters soil.')
        self.assertEqual(revealed['state']['question']['help_source'],'validated_expected_answer')
        self.assertEqual(store.answers(),[])
        self.assertEqual(sum(h['action']=='reveal' for h in store.session(state['id'])['checkpoint']['history']),1)
        self.client=self.new_client()
        resumed=self.client.get('/api/professor/sessions/'+state['id']).json()
        self.assertEqual(resumed['state']['question']['help_source'],'validated_expected_answer')
        graded=self.command('answer',resumed,text='Water enters soil.')
        self.assertEqual(graded['state']['edge_status']['entry'],'related')
        self.assertTrue(store.answers()[0]['helped'])

    def test_model_startup_failure_still_allows_saved_answer_reveal(self):
        state=self.command('start')
        def unavailable(*_args):
            raise ModelServiceError('Ollama unavailable during initialization')
        with TestClient(create_app([],professor_store=StudentStore(self.db),runs_root=self.runs,
                                   model_factory=unavailable),base_url='http://127.0.0.1') as client:
            response=client.post('/api/professor/quiz',json=dict(action='reveal',request_id=str(uuid.uuid4()),
                                 session_id=state['id'],question_id=state['state']['question']['id']))
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['state']['question']['help_source'],'validated_expected_answer')

    def test_unsafe_fallback_reports_reveal_error_without_mutating_quiz(self):
        state=self.command('start');store=StudentStore(self.db)
        checkpoint=store.session(state['id'])['checkpoint']
        checkpoint['question']['expected_answer']='source: Water; target: Soil'
        with store.connect() as db:
            db.execute('UPDATE sessions SET checkpoint=? WHERE id=?',(json.dumps(checkpoint),state['id']))
        before=copy.deepcopy(store.session(state['id']))
        with patch.object(self.models,'ask',side_effect=ModelServiceError('Offline')):
            response=self.post('quiz',dict(action='reveal',request_id=str(uuid.uuid4()),
                session_id=state['id'],question_id=state['state']['question']['id']),422)
        self.assertEqual(response['detail']['code'],'reveal_generation')
        self.assertEqual(store.session(state['id']),before)

    def test_standalone_explorer_uses_same_help_recovery(self):
        with TestClient(create_app([self.run],model_factory=lambda *_args:self.models),base_url='http://127.0.0.1') as client:
            state=client.post('/runs/0/quiz',json=dict(action='start',page_id=str(uuid.uuid4()),request_id=str(uuid.uuid4()))).json()
            base=dict(page_id=str(uuid.uuid4()),quiz_id=state['quiz_id'],question_id=state['question']['id'])
            with patch.object(self.models,'ask',side_effect=ModelServiceError('Offline')):
                failure=client.post('/runs/0/quiz',json=dict(base,action='hint',request_id=str(uuid.uuid4())))
                self.assertEqual(failure.status_code,422,failure.text)
                self.assertIn('No hint was shown',failure.json()['detail'])
                reveal=client.post('/runs/0/quiz',json=dict(base,action='reveal',request_id=str(uuid.uuid4())))
                self.assertEqual(reveal.status_code,200,reveal.text)
                self.assertEqual(reveal.json()['question']['help_source'],'validated_expected_answer')


if __name__=='__main__':
    unittest.main()
