"""Question-aware evidence, scope, persistence and failure behavior."""
import copy
import unittest
from unittest.mock import patch

from pipeline.assessment import mastery_marks
from pipeline.models import ModelResponseError
from pipeline.quiz_grading import assess_contextual, original_learner_quote
from pipeline.student_store import StudentStore
from pipeline.quiz_examiner import QuizExaminer, ExamQuestion
from tests import test_professor as fixtures


class ContextModels:
    def __init__(self, judgment):self.judgment=judgment
    def ask(self,role,instruction,payload,schema,identifier,validator=None):
        result=schema.model_validate(self.judgment)
        if validator:validator(result)
        return result


class ContextEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.question=dict(text='What happens to memory use after quantization?',expected_answer='It decreases.',
            examiner_material=dict(facts=[dict(id='q')]),assessment_spec=[dict(fact_id='q',scope='full_relationship',
            requested='Explain the effect.',given='Quantization.',criteria=['Memory use decreases.'])])
        self.j=dict(fact_id='q',status='complete',evidence=[dict(statement_id='answer',quote='It needs less memory.')],
            demonstrated='You explain the decrease.',missing='',criteria_met=[0],relationship_demonstrated=True,
            context_used='after quantization')

    def test_contextual_paraphrase_can_earn_green_with_original_evidence(self):
        result=assess_contextual(ContextModels(self.j),self.question,'It needs less memory.')
        self.assertEqual(mastery_marks(self.question,result),{'q':'match'})
        self.assertEqual(result['matches'][0]['context_used'],'after quantization')
        self.assertEqual(result['matches'][0]['evidence'],self.j['evidence'])
        self.assertEqual(result['checked_records'],1)
        self.assertEqual(result['assessment_version'],3)

    def test_component_stays_yellow_despite_full_question_credit(self):
        self.question['assessment_spec'][0]['scope']='component'
        self.j['relationship_demonstrated']=False
        result=assess_contextual(ContextModels(self.j),self.question,'It needs less memory.')
        self.assertEqual(mastery_marks(self.question,result),{'q':'related'})
        self.assertEqual(mastery_marks(self.question,result,{'q':'match'},True),{'q':'related'})

    def test_evidence_cannot_be_borrowed_or_context_invented(self):
        for change in [dict(evidence=[dict(statement_id='answer',quote='memory requirements decrease')]),
                       dict(context_used='The question gives a reduction.'),dict(criteria_met=[]),
                       dict(criteria_met=[0,0]),dict(criteria_met=[5]),dict(relationship_demonstrated=False)]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                assess_contextual(ContextModels(dict(self.j,**change)),self.question,'It needs less memory.')

    def test_partial_requires_missing_meaning_and_never_green(self):
        self.j.update(status='partial',criteria_met=[],relationship_demonstrated=False,missing='Explain the direction.')
        result=assess_contextual(ContextModels(self.j),self.question,'It needs less memory.')
        self.assertEqual(mastery_marks(self.question,result),{'q':'related'})
        self.j['missing']=''
        with self.assertRaises(ValueError):assess_contextual(ContextModels(self.j),self.question,'It needs less memory.')

    def test_replaying_forged_or_incomplete_evidence_cannot_award_green(self):
        result=assess_contextual(ContextModels(self.j),self.question,'It needs less memory.')
        result['judgments'][0]['evidence'][0]['quote']='invented'
        self.assertEqual(mastery_marks(self.question,result),{'q':'related'})

    def test_explicit_contradiction_does_not_require_claiming_correct_understanding(self):
        self.j.update(status='contradiction',demonstrated='',missing='',criteria_met=[],relationship_demonstrated=False)
        result=assess_contextual(ContextModels(self.j),self.question,'It needs less memory.')
        self.assertEqual(mastery_marks(self.question,result),{'q':'conflict'})
        self.assertIn('contradicts',result['rubric'][0]['demonstrated'])

    def test_quote_repair_preserves_words_and_restores_original_punctuation(self):
        text='The model’s memory needs decrease.'
        self.assertEqual(original_learner_quote(text,"the model's memory needs decrease"),'The model’s memory needs decrease')
        self.assertEqual(original_learner_quote(text,'memory requirements decrease'),'memory requirements decrease')
        self.assertEqual(original_learner_quote(text,'memory decrease'),'memory decrease')

    def test_generation_excludes_other_facts_in_shared_source_quotes(self):
        model=fixtures.TeachingModels();model.quiz_policy='contextual_v3'
        graph=dict(nodes=[dict(id='water',label='Water',definition='Water enters soil and freezes into ice.'),
                          dict(id='soil',label='Soil')],edges=[dict(id='entry',source='water',target='soil',
                          label='enters',origin='document',evidence='Water enters soil and freezes into ice.')])
        original=model.ask;payloads=[]
        def capture(role,instruction,payload,schema,identifier,validator=None):
            payloads.append((role,payload))
            if role=='quiz_answer_grounding':return schema(supported=True,direction_preserved=True,conditions_preserved=True,reason='Fixture aligned.')
            result=original(role,instruction,payload,ExamQuestion if role=='quiz_question' else schema,identifier,None)
            if role=='quiz_question':result=schema.model_validate({k:v for k,v in result.model_dump().items() if k in schema.model_fields})
            if validator:validator(result)
            return result
        model.ask=capture
        question=QuizExaminer(model,graph).question('water',['entry'],1,[],'question')
        self.assertEqual(question['grading_policy'],'contextual_v3')
        for role,payload in payloads:
            if role in {'quiz_question','quiz_question_review'}:
                self.assertNotIn('definition',payload['material']['subject'])
                self.assertNotIn('evidence',payload['material']['facts'][0])


class ContextFlowTests(unittest.TestCase):
    setUp=fixtures.ProfessorTests.setUp
    new_client=fixtures.ProfessorTests.new_client
    post=fixtures.ProfessorTests.post
    command=fixtures.ProfessorTests.command

    def contextual(self,status='complete',fail=False):
        original=self.models.ask
        self.models.quiz_policy='contextual_v3'
        def ask(role,instruction,payload,schema,entity_id,validator=None):
            if role=='quiz_answer_grounding':return schema(supported=True,direction_preserved=True,conditions_preserved=True,reason='Fixture aligned.')
            if role=='quiz_question':
                result=original(role,instruction,payload,ExamQuestion,entity_id,None)
                result=schema.model_validate({k:v for k,v in result.model_dump().items() if k in schema.model_fields})
                if validator:validator(result)
                return result
            if role not in {'quiz_contextual','quiz_contextual_review'}:return original(role,instruction,payload,schema,entity_id,validator)
            if fail:raise ModelResponseError('Unresolved model response')
            result=schema.model_validate(dict(fact_id=payload['fact']['id'],status=status,
                evidence=[] if status=='not_demonstrated' else [dict(statement_id='answer',quote=payload['learner_answer'])],
                demonstrated='' if status=='not_demonstrated' else 'Demonstrated meaning.',
                missing='' if status=='complete' else 'Missing requested connection.',criteria_met=list(range(len(payload['assessment_spec']['criteria']))) if status=='complete' else [],
                relationship_demonstrated=status=='complete',context_used=''))
            if validator:validator(result)
            return result
        return patch.object(self.models,'ask',side_effect=ask)

    def test_green_paraphrase_persists_and_assisted_success_is_yellow(self):
        with self.contextual():
            state=self.command('start');state=self.command('answer',state,text='It soaks into the ground.')
            self.assertEqual(state['state']['edge_status'],{'entry':'match'})
            self.assertEqual(state['answer_score'],100)
            self.client=self.new_client()
            self.assertEqual(StudentStore(self.db).knowledge(self.student,self.topic['id'])['entry']['mark'],'match')
            other=self.post('students',dict(name='Assisted demo'))['id'];self.student=other
            state=self.command('start');state=self.command('reveal',state)
            state=self.command('answer',state,text='It soaks into the ground.')
            self.assertEqual(state['state']['edge_status'],{'entry':'related'})

    def test_unrelated_answer_is_red_only_for_requested_fact(self):
        with self.contextual('not_demonstrated'):
            state=self.command('start');state=self.command('answer',state,text='I like pizza.')
            self.assertEqual(state['state']['edge_status'],{'entry':'not_demonstrated'})
            self.assertEqual(state['answer_score'],0)

    def test_failed_contextual_grade_is_pending_not_a_zero(self):
        with self.contextual(fail=True):
            state=self.command('start')
            import uuid
            response=self.client.post('/api/professor/quiz',json=dict(action='answer',request_id=str(uuid.uuid4()),
                session_id=state['id'],question_id=state['state']['question']['id'],text='It soaks into the ground.'))
            self.assertEqual(response.status_code,503)
            self.assertEqual(StudentStore(self.db).answers(),[])
            self.assertEqual(len(StudentStore(self.db).pending_answers(state['id'])),1)


if __name__=='__main__':unittest.main()
