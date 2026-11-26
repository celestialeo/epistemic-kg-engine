"""Offline request-boundary regressions; no model service or pipeline execution."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.debate import BACKGROUND_POLICY, FactRepair
from pipeline.health import HealthFailure, HealthMonitor, finish_item
from pipeline.models import Models, request_budget
from pipeline.repair_budget import CONTEXT_POLICY, RepairContext, repair_candidates
from pipeline.settings import estimated_tokens, setting


class MemoryTrace:
    run_id = 'repair-budget-fixture'

    def __init__(self):
        self.events, self.saved = [], {}

    def emit(self, event, **data):
        self.events.append((event, copy.deepcopy(data)))
        return str(len(self.events))

    def save(self, path, value):
        self.saved[path] = copy.deepcopy(value)


def fixture():
    reason = 'The claim omits the required operating condition and mistakes possibility for certainty. ' * 8
    source = 'The mechanism may operate only under the stated condition. Its use in this case is unknown. ' * 8
    gap = dict(id='gap_1', question='How can the mechanism work?',
               source_chunk_ids=['chunk_1'], document_coverage=source)
    seed = dict(concept='mechanism', definition='A general process.',
                case_specific_unknowns=[dict(question='Was it used here?', source_chunk_ids=['chunk_1'])])
    row = dict(id='candidate_1', intended_fact='The mechanism may affect the outcome under a condition.',
               reason='A general explanation, conditional on the operating condition.',
               source='mechanism', target='outcome', relation='affects',
               conditions='Only under the stated operating condition.', modality='possible',
               gap_ids=['gap_1'], gaps=[gap], chunk_id='chunk_1', accepted=False,
               decision_reason=reason, rejection_stage='representation',
               representation_check=dict(reason=reason, scope_preserved=False),
               novelty=dict(status='duplicate', evidence_ids=['fact_remote'],
                            related_reference_ids=['chunk_2'], reason='Compare fact_remote and chunk_2.'),
               source_context=[dict(id='chunk_extra', text='Supplemental source context. ' * 100)])
    chunks = [dict(id='chunk_1', text=source), dict(id='chunk_2', text='The comparison has a different scope.')]
    facts = [dict(id='fact_remote', source='other', relation='affects', target='elsewhere',
                  conditions='Only in the comparison setting.', modality='possible', evidence='Complete quoted evidence.'),
             dict(id='fact_local', source='mechanism', relation='affects', target='outcome',
                  conditions='A local qualification.', modality='possible'),
             dict(id='fact_extra', source='mechanism', target='extra', relation='relates',
                  reason='Supplemental fact explanation. ' * 80)]
    sibling = dict(id='candidate_other', gap_ids=['gap_1'], source='mechanism', target='extra',
                   decision_reason='Supplemental sibling explanation. ' * 100)
    return row, seed, dict(overview='Supplemental chapter overview. ' * 200), chunks, facts, [row, sibling]


def resolve(payload):
    """Decode exact-text references and fail on dangling pointers."""
    def walk(value):
        if isinstance(value, dict):
            if set(value) == {'same_text_as'}:
                target = payload
                for part in value['same_text_as'].split('/')[1:]:
                    part = part.replace('~1', '/').replace('~0', '~')
                    target = target[int(part)] if isinstance(target, list) else target[part]
                assert isinstance(target, str)
                return target
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value
    return walk(payload)


def response(value):
    return SimpleNamespace(model_dump=lambda **kwargs: dict(message=dict(content=json.dumps(value)), done_reason='stop'))


class RepairBudgetTests(unittest.TestCase):
    instruction = BACKGROUND_POLICY + 'Correct the candidate responsibly or return corrected_fact=null.'

    def make_models(self, trace, context):
        return Models(trace, 'offline', 'offline', 'http://unused.invalid',
                      context_tokens=context, max_output_tokens=4096)

    def call(self, data, models, trace):
        row, seed, chapter, chunks, facts, siblings = data
        return repair_candidates([row], seed, chapter, chunks, facts, siblings,
                                 models, trace, FactRepair, self.instruction)

    def assert_request_fits(self, request):
        total = (estimated_tokens(request['prompt'])
                 + setting('model', 'prompt_reserve_tokens') + request['options']['num_predict'])
        self.assertLessEqual(total, request['options']['num_ctx'])
        self.assertEqual(request['options']['num_predict'], setting('model', 'repair_output_tokens'))

    @patch('pipeline.models.Client')
    def test_oversized_context_preserves_complete_evidence_and_qualifications(self, client):
        data = fixture()
        original = copy.deepcopy(data)
        plan = RepairContext(*data)
        options = dict(num_ctx=100000, num_predict=setting('model', 'repair_output_tokens'))
        instruction = self.instruction + CONTEXT_POLICY
        minimum = request_budget(instruction, plan.variants[-1][1], FactRepair, options)['total_tokens']
        trace = MemoryTrace()
        models = self.make_models(trace, minimum)
        client.return_value.chat.return_value = response(dict(reason='No responsible correction.', corrected_fact=None))
        results, errors = self.call(data, models, trace)
        self.assertFalse(errors)
        self.assertIsNone(results['candidate_1']['corrected_fact'])
        request = next(v for k, v in trace.events if k == 'model.request')
        self.assert_request_fits(request)
        payload = json.loads(request['prompt'].split('\nDATA:\n')[1])
        self.assertEqual(resolve(payload)['essential'], original_essential := plan.variants[0][1]['essential'])
        self.assertEqual(payload['supplemental'], {})
        self.assertEqual({r['id'] for r in original_essential['source_evidence']}, {'chunk_1', 'chunk_2'})
        self.assertEqual({r['id'] for r in original_essential['comparison_evidence']}, {'fact_remote', 'fact_local'})
        self.assertEqual(data, original)
        measurements = trace.saved['artifacts/repair_budgets/candidate_1.json']['attempts'][0]['measurements']
        self.assertFalse(measurements[0]['fits'])
        self.assertTrue(measurements[-1]['fits'])
        self.assertEqual(measurements[-1]['total_tokens'], minimum)

    @patch('pipeline.models.Client')
    def test_retry_rebudgets_actual_feedback_and_keeps_gap_validation(self, client):
        data = fixture()
        plan = RepairContext(*data)
        instruction = self.instruction + CONTEXT_POLICY
        options = dict(num_ctx=100000, num_predict=setting('model', 'repair_output_tokens'))
        # First attempt exactly fits; validation feedback forces further reduction.
        context = request_budget(instruction, plan.variants[2][1], FactRepair, options)['total_tokens']
        invalid = dict(reason='A proposed correction.', corrected_fact=dict(
            intended_fact='The mechanism may affect the outcome under a condition.', confidence=.7,
            reason='A conditional explanation.', gap_ids=['unrelated_gap'], added_knowledge='A mechanism.'))
        valid = copy.deepcopy(invalid)
        valid['corrected_fact']['gap_ids'] = ['gap_1']
        client.return_value.chat.side_effect = [response(invalid), response(valid)]
        trace = MemoryTrace()
        results, errors = self.call(data, self.make_models(trace, context), trace)
        self.assertFalse(errors)
        self.assertEqual(results['candidate_1']['corrected_fact']['gap_ids'], ['gap_1'])
        requests = [v for k, v in trace.events if k == 'model.request']
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assert_request_fits(request)
            payload = json.loads(request['prompt'].split('\nDATA:\n')[1].split('\nPrevious response failed validation:')[0])
            self.assertEqual(resolve(payload)['essential'], plan.variants[0][1]['essential'])
        self.assertIn("A corrected fact must address the original candidate's questions", requests[1]['prompt'])
        attempts = trace.saved['artifacts/repair_budgets/candidate_1.json']['attempts']
        self.assertNotEqual(attempts[0]['measurements'][-1]['variant'], attempts[1]['measurements'][-1]['variant'])
        self.assertGreater(attempts[1]['measurements'][-1]['retry_feedback_tokens'], 0)
        self.assertFalse(data[0]['accepted'])  # A repair is still only a proposal.

    @patch('pipeline.models.Client')
    def test_minimum_overflow_is_unresolved_before_call_or_on_retry(self, client):
        for retry in (False, True):
            with self.subTest(retry=retry):
                client.return_value.chat.reset_mock()
                data = fixture()
                plan = RepairContext(*data)
                minimum = request_budget(self.instruction + CONTEXT_POLICY, plan.variants[-1][1],
                                         FactRepair, dict(num_ctx=100000, num_predict=setting('model', 'repair_output_tokens')))['total_tokens']
                trace = MemoryTrace()
                # No spare tokens for retry feedback in the second case.
                models = self.make_models(trace, minimum if retry else minimum - 1)
                client.return_value.chat.return_value = response(dict(reason='Missing corrected_fact field.'))
                results, errors = self.call(data, models, trace)
                self.assertEqual(results, {})
                self.assertIn('minimum required content', errors['candidate_1'])
                self.assertIn('not truncated', errors['candidate_1'])
                self.assertEqual(client.return_value.chat.call_count, int(retry))
                self.assertFalse(data[0]['accepted'])
                attempts = trace.saved['artifacts/repair_budgets/candidate_1.json']['attempts']
                self.assertEqual(attempts[-1]['status'], 'unresolved')
                trace.health = HealthMonitor(trace)
                # Existing 6/10 threshold still stops unresolved repairs.
                for i in range(4):
                    finish_item(trace, 'background_repair', f'passed_{i}')
                with self.assertRaises(HealthFailure):
                    for i in range(6):
                        finish_item(trace, 'background_repair', f'failed_{i}', errors['candidate_1'])
                self.assertEqual(trace.saved['artifacts/unresolved_items.json'][-1]['status'], 'unresolved')
                self.assertEqual(trace.saved['artifacts/health.json']['max_failure_rate'], .5)


if __name__ == '__main__':
    unittest.main()
