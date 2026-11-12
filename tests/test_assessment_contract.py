"""Question scope, strict evidence, unresolved retries and versioned quiz material."""
import copy
import json
import unittest
import uuid
from unittest.mock import patch

from pipeline.assessment import mastery_marks, validate_spec
from pipeline.models import ModelResponseError
from pipeline.quiz_examiner import ExamQuestion, QuizExaminer, plain_language
from pipeline.student_store import StudentStore
from tests import test_professor as fixtures
from tests.test_quiz_grading import models_with


class ScopeTests(unittest.TestCase):
    def result(self, scope='component', status='complete'):
        return dict(assessment_version=2, assessment_spec=fixtures.assessment_spec([dict(id='fact')],scope),
                    rubric=[dict(fact_id='fact',status=status)],matches=[dict(id='fact',status='match')],
                    graph_assessment=dict(status='resolved'))

    def test_component_is_capped_even_with_a_valid_whole_graph_match(self):
        self.assertEqual(mastery_marks({},self.result()),{'fact':'related'})
        self.assertEqual(mastery_marks({},self.result(),{'fact':'match'},True),{'fact':'related'})

    def test_full_mastery_requires_both_requested_scope_and_valid_relationship_evidence(self):
        result=self.result('full_relationship')
        self.assertEqual(mastery_marks({},result),{'fact':'match'})
        result['matches']=[]
        self.assertEqual(mastery_marks({},result),{'fact':'related'})
        self.assertEqual(mastery_marks({},result,{'fact':'match'},True),{'fact':'match'})

    def test_unresolved_matching_never_changes_mastery(self):
        result=self.result('full_relationship')
        result['graph_assessment']=dict(status='unresolved',error='Invalid evidence')
        self.assertEqual(mastery_marks({},result),{})

    def test_partial_and_unassessed_facts_cannot_turn_green(self):
        result=self.result('full_relationship','partial')
        result['matches'].append(dict(id='incidental',status='match'))
        self.assertEqual(mastery_marks({},result),{'fact':'related'})

    def test_spec_requires_exact_nonduplicate_scope_and_substantive_criteria(self):
        spec=fixtures.assessment_spec([dict(id='fact')])
        for value in [[],spec*2,[dict(spec[0],fact_id='other')],[dict(spec[0],criteria=[' '])]]:
            with self.subTest(value=value),self.assertRaises(ValueError):
                validate_spec(value,['fact'])

    def test_legacy_history_is_not_regraded_or_discarded(self):
        self.assertIsNone(mastery_marks({},dict(matches=[dict(id='fact',status='match')])))

    def test_question_vocabulary_is_allowed_but_internal_records_are_rejected(self):
        draft=dict(question='How does the source affect the relationship under these conditions?',
                   expected_answer='A reference explanation.',assessed_fact_ids=['fact'],
                   assessment_spec=fixtures.assessment_spec([dict(id='fact')]))
        plain_language(ExamQuestion(**draft))
        for text in ['Explain edge_00011.', 'Use source: a, target: b.',
                     'Interpret ("a", "causes", "b").','Show the assessed_fact_ids.']:
            with self.subTest(text=text),self.assertRaises(ValueError):
                plain_language(ExamQuestion(**dict(draft,question=text)))


class ContractFlowTests(unittest.TestCase):
    setUp=fixtures.ProfessorTests.setUp
    new_client=fixtures.ProfessorTests.new_client
    post=fixtures.ProfessorTests.post
    command=fixtures.ProfessorTests.command

    def component_models(self):
        original=self.models.ask
        def respond(role,instruction,payload,schema,entity_id,validator=None):
            if role=='quiz_question':
                value=dict(question='What does water enter?',expected_answer='soil',assessed_fact_ids=['entry'],
                           assessment_spec=[dict(fact_id='entry',scope='component',requested='Name the destination.',
                                                given='Water enters something.',criteria=['Name soil.'])])
            elif role=='quiz_statements':
                value=dict(statements=[dict(text=payload['learner_answer'],is_assertion=False)])
            elif role=='quiz_statement_review':
                value=dict(statement_id='statement_1',kind='answer_fragment',reason='Names the requested destination.')
            else:
                return original(role,instruction,payload,schema,entity_id,validator)
            result=schema.model_validate(value)
            if validator:validator(result)
            return result
        return respond

    def test_short_answer_scores_correctly_without_awarding_entire_relationship(self):
        with patch.object(self.models,'ask',side_effect=self.component_models()):
            state=self.command('start')
            answer=self.command('answer',state,text='soil')
            self.assertEqual(answer['answer_score'],100)
            self.assertEqual(answer['state']['edge_status'],{'entry':'related'})
        store=StudentStore(self.db)
        record=store.answers()[0]
        self.assertEqual(record['result']['rubric'][0]['evidence'],[dict(statement_id='statement_1',quote='soil')])
        self.assertEqual(record['result']['matches'],[])
        self.assertEqual(record['question']['assessment_spec'],record['result']['assessment_spec'])
        self.client=self.new_client()
        self.assertEqual(store.knowledge(self.student,self.topic['id'])['entry']['mark'],'related')
        self.post('answers/'+record['id']+'/override',dict(marks={'entry':'match'},feedback='Correct term.',reason='Confirms the destination only.'))
        self.assertEqual(store.knowledge(self.student,self.topic['id'])['entry']['mark'],'related')

    def test_paraphrase_uses_original_quotes_and_can_demonstrate_full_connection(self):
        original=self.models.ask
        text='The liquid moves into the ground.'
        def respond(role,instruction,payload,schema,entity_id,validator=None):
            if role!='quiz_meaning':return original(role,instruction,payload,schema,entity_id,validator)
            result=schema.model_validate(dict(judgments=[dict(statement_id='statement_1',edge_id='entry',meaning='equivalent',
                asserts_relation=True,source_identified=True,target_identified=True,source_quote='The liquid',
                target_quote='the ground',relation_quote='moves into',reason='Equivalent movement and entities in this context.')]))
            if validator:validator(result)
            return result
        with patch.object(self.models,'ask',side_effect=respond):
            state=self.command('start')
            result=self.command('answer',state,text=text)
        self.assertEqual(result['answer_score'],100)
        self.assertEqual(result['state']['edge_status'],{'entry':'match'})
        saved=StudentStore(self.db).answers()[0]['result']
        for key in ['source_quote','target_quote','relation_quote']:
            self.assertIn(saved['matches'][0][key],text)

    def test_bad_rubric_quote_exhausts_three_attempts_and_never_runs_matching(self):
        original=self.models.ask
        invalid=dict(fact_id='entry',status='complete',evidence=[dict(statement_id='statement_1',quote='Invented learner words')],
                     demonstrated='Movement.',missing='')
        rubric_models=models_with(invalid,invalid,invalid)
        def respond(role,instruction,payload,schema,entity_id,validator=None):
            if role=='quiz_rubric':return rubric_models.ask(role,instruction,payload,schema,entity_id,validator)
            return original(role,instruction,payload,schema,entity_id,validator)
        state=self.command('start');store=StudentStore(self.db);before=store.session(state['id'])
        request=dict(action='answer',request_id=str(uuid.uuid4()),session_id=state['id'],question_id=state['state']['question']['id'],text='Water enters soil.')
        with patch.object(self.models,'ask',side_effect=respond),patch('pipeline.quiz_grading.QuizGrader.match') as match:
            self.post('quiz',request,503)
            match.assert_not_called()
        self.assertEqual(rubric_models.client.chat.call_count,3)
        self.assertEqual(store.session(state['id']),before)
        self.assertEqual(store.answers(),[])
        pending=store.pending_answers(state['id'])[0]
        self.assertEqual(pending['grading_status'],'unresolved')
        self.assertIsNone(pending['score'])
        self.assertIn('verbatim',pending['error'])
        self.client=self.new_client()
        result=self.post('quiz',pending['request'])
        self.assertEqual(result['answer_score'],100)
        self.assertEqual(self.post('quiz',pending['request']),result)
        self.assertEqual(len(store.answers()),1)

    def test_failed_graph_retry_preserves_score_original_answer_and_mastery(self):
        state=self.command('start')
        with patch('pipeline.quiz_grading.QuizGrader.match',side_effect=ModelResponseError('Overlapping source and target quotes')):
            response=self.command('answer',state,text='Water enters soil.')
            store=StudentStore(self.db);answer=store.answers()[0]
            self.assertEqual(response['answer_score'],100)
            self.client=self.new_client()
            retry=self.post('answers/'+answer['id']+'/retry-matching',{})
            self.assertEqual(retry['status'],'unresolved')
        saved=store.answers()[0]
        for key in ['text','score','marks','question','helped','created_at']:
            self.assertEqual(saved[key],answer[key])
        self.assertEqual(store.knowledge(self.student,self.topic['id']),{})
        self.assertEqual(len(store.answers()),1)
        self.assertEqual(self.post('answers/'+answer['id']+'/retry-matching',{})['status'],'resolved')
        self.assertEqual(store.knowledge(self.student,self.topic['id'])['entry']['mark'],'match')

    def background_run(self,name='run_background',definition='Water moves into soil.'):
        run=fixtures.write_run(self.runs,name=name,timestamp='2026-11-10T12:00:00+00:00' if name=='run_background' else '2026-11-11T12:00:00+00:00')
        p=run/'artifacts/graph.json';g=json.loads(p.read_text());g['edges'][0].update(origin='background',definition=definition)
        p.write_text(json.dumps(g));self.topic=self.client.get('/api/professor/catalog').json()['topics'][0]
        return self.topic['id']

    def test_background_evidence_text_is_not_auto_trusted_approval_is_persisted_and_version_bound(self):
        run_id=self.background_run()
        material=self.client.get('/api/professor/runs/'+run_id+'/quiz-material').json()
        self.assertFalse(material['facts'][0]['eligible'])  # Even a generated evidence field is not independent proof.
        self.post('quiz',dict(action='start',request_id=str(uuid.uuid4()),student_id=self.student,run_id=run_id),422)
        self.post('runs/'+run_id+'/facts/entry/approval',dict(approved=True,reason='Professor verified the claim against the chapter.'))
        self.client=self.new_client()
        state=self.command('start')
        self.assertTrue(StudentStore(self.db).session(state['id'])['checkpoint']['question']['provenance']['entry']['approved'])
        other=self.background_run('run_changed','A different definition.')
        self.assertNotEqual(run_id,other)
        self.assertFalse(self.client.get('/api/professor/runs/'+other+'/quiz-material').json()['facts'][0]['eligible'])

    def test_revoked_background_approval_preserves_a_submitted_answer_as_unresolved(self):
        run_id=self.background_run()
        path='runs/'+run_id+'/facts/entry/approval'
        self.post(path,dict(approved=True,reason='Professor checked source.'))
        state=self.command('start')
        self.post(path,dict(approved=False,reason='Support requires further review.'))
        request=dict(action='answer',request_id=str(uuid.uuid4()),session_id=state['id'],question_id=state['state']['question']['id'],text='Water enters soil.')
        self.post('quiz',request,503)
        store=StudentStore(self.db)
        self.assertEqual(store.pending_answers(state['id'])[0]['text'],request['text'])
        self.assertEqual(store.knowledge(self.student,run_id),{})
        self.post(path,dict(approved=True,reason='Professor reverified the supporting reference.'))
        self.assertEqual(self.post('quiz',request)['answer_score'],100)

    def test_unapproved_background_is_not_used_for_hints_or_reveal(self):
        run_id=self.background_run();path='runs/'+run_id+'/facts/entry/approval'
        self.post(path,dict(approved=True,reason='Professor checked the source.'))
        state=self.command('start')
        self.post(path,dict(approved=False,reason='Support withdrawn for review.'))
        before=StudentStore(self.db).session(state['id'])
        for action in ['hint','reveal']:
            request=dict(action=action,request_id=str(uuid.uuid4()),session_id=state['id'],question_id=state['state']['question']['id'])
            response=self.post('quiz',request,503)
            self.assertIn('approval',response['detail'])
        self.assertEqual(StudentStore(self.db).session(state['id']),before)

    def test_disagreeing_graph_assessment_cannot_award_mastery(self):
        original=self.models.ask
        def respond(role,instruction,payload,schema,entity_id,validator=None):
            result=original(role,instruction,payload,schema,entity_id,validator)
            if role=='quiz_meaning':
                for item in result.judgments:item.meaning='contradiction'
            return result
        with patch.object(self.models,'ask',side_effect=respond):
            state=self.command('start');answer=self.command('answer',state,text='Water enters soil.')
        self.assertEqual(answer['answer_score'],100)
        self.assertEqual(answer['state']['last_result']['graph_assessment']['status'],'unresolved')
        self.assertIn('disagree',answer['state']['last_result']['graph_assessment']['error'])
        self.assertEqual(StudentStore(self.db).knowledge(self.student,self.topic['id']),{})

    def test_standalone_failure_preserves_answer_in_diagnostics_without_scoring(self):
        from fastapi.testclient import TestClient
        from pipeline.explorer import create_app
        with TestClient(create_app([self.run],model_factory=lambda *_:self.models),base_url='http://127.0.0.1') as client:
            state=client.post('/runs/0/quiz',json=dict(action='start',page_id=str(uuid.uuid4()),request_id=str(uuid.uuid4()))).json()
            request=dict(action='answer',page_id=str(uuid.uuid4()),request_id=str(uuid.uuid4()),quiz_id=state['quiz_id'],
                         question_id=state['question']['id'],text='Water enters soil.')
            with patch('pipeline.quiz.assess_rubric',side_effect=ModelResponseError('Unresolved rubric evidence')):
                response=client.post('/runs/0/quiz',json=request)
                self.assertEqual(response.status_code,503)
            paths=list(self.run.rglob('unresolved_*.json'))
            self.assertEqual(len(paths),1)
            record=json.loads(paths[0].read_text(encoding='utf-8'))
            self.assertEqual(record['request'],request)
            self.assertEqual(record['assessment_status'],'unresolved')
            self.assertIsNone(record['score'])
            success=client.post('/runs/0/quiz',json=request)
            self.assertEqual(success.status_code,200,success.text)
            self.assertEqual(success.json()['question']['attempts'],1)

    def test_scope_disagreement_in_review_rejects_question_without_a_session(self):
        original=self.models.ask
        def respond(role,instruction,payload,schema,entity_id,validator=None):
            result=original(role,instruction,payload,schema,entity_id,validator)
            if role=='quiz_question_review':
                result.specification_aligned=False
                result.reason='The question asks for a term but the spec claims a full relationship.'
            return result
        with patch.object(self.models,'ask',side_effect=respond):
            self.post('quiz',dict(action='start',request_id=str(uuid.uuid4()),student_id=self.student,run_id=self.topic['id']),422)
        self.assertEqual(StudentStore(self.db).history(),[])

    def test_legacy_active_question_gets_a_spec_without_rewriting_question_or_answer(self):
        state=self.command('start');store=StudentStore(self.db)
        row=store.session(state['id']);question=row['checkpoint']['question'];question.pop('assessment_spec');question.pop('assessment_version')
        with store.connect() as db:db.execute('UPDATE sessions SET checkpoint=? WHERE id=?',(json.dumps(row['checkpoint']),state['id']))
        result=self.command('answer',state,text='Water enters soil.')
        self.assertEqual(result['answer_score'],100)
        saved=store.answers()[0]
        self.assertEqual(saved['question']['text'],question['text'])
        self.assertEqual(saved['result']['assessment_version'],2)
        self.assertTrue(saved['question']['assessment_spec'])


if __name__=='__main__':unittest.main()
