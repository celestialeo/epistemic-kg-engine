"""Focused validator and complete-checkpoint continuation regressions."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from ollama import ChatResponse
from pipeline.debate import CounterexampleCheck, check_background_counterexamples, validate_counterexample, debate
from pipeline.checkpoints import Checkpoints
from pipeline.models import Models, ModelResponseError
from pipeline.registry import ConceptRegistry, RelationRegistry, FactIndex
from pipeline.trace import Trace
from pipeline.settings import snapshot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from resume_debate_checkpoint import (prepare_checkpoint, fingerprint, digest, VerifiedCheckpoints,
                                      check_preserved)


SUPPORTED = 'The premises are supported: six is even and is not divisible by four.'
UNSUPPORTED = 'The premises are unsupported: the proposed example incorrectly says that six is odd.'
REFUTES = 'The case refutes the claim: six satisfies the subject condition but lacks the asserted divisibility.'
OUTSIDE = 'The case does not refute the claim: it lies outside the explicit subject condition.'


def review(supported=True, refutes=True):
    return dict(case_reason=SUPPORTED if supported else UNSUPPORTED, case_is_supported=supported,
                refutation_reason=REFUTES if refutes else OUTSIDE, refutes_exact_assertion=refutes)


def audit(supported=True, refutes=True):
    return {name: dict(conclusion_quote=reason, justification_quote=reason,
                       conclusion=(('supported' if verdict else 'unsupported') if name == 'case_is_supported'
                                   else ('refutes' if verdict else 'does_not_refute')))
            for name, reason, verdict in [('case_is_supported', SUPPORTED if supported else UNSUPPORTED, supported),
                                         ('refutes_exact_assertion', REFUTES if refutes else OUTSIDE, refutes)]}


class CounterexampleFixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / 'run', 'run')
        self.addCleanup(self.trace.close)
        self.models = Models(self.trace, 'fixture', 'embed', 'http://localhost',
                             context_tokens=24576, max_output_tokens=4096)
        self.models.cache_enabled = False
        self.row = dict(id='example', source='even integers', relation='are_divisible_by', target='four',
                        accepted=True, review_status='completed')
        self.check = CounterexampleCheck(reason='Six is an exception.', sound_as_stated=False,
                                         counterexample='Six is even but is not divisible by four.')

    def responses(self, *values):
        return patch.object(self.models.client, 'chat', side_effect=[ChatResponse(
            message=dict(role='assistant', content=json.dumps(value)), done_reason='stop') for value in values])

    def requests(self):
        return [e['data'] for line in (self.trace.directory / 'events.jsonl').read_text(encoding='utf-8').splitlines()
                if (e := json.loads(line))['event'] == 'model.request']

    def test_contradiction_retries_applicability_without_regenerating_case(self):
        with self.responses(dict(review(), case_is_supported=False), audit(), review(), audit()):
            validate_counterexample(self.row, self.check, self.models, self.trace)
        requests = self.requests()
        self.assertEqual([r['role'] for r in requests],
                         ['background_counterexample_applicability', 'background_counterexample_consistency'] * 2)
        self.assertIn('case_is_supported=False contradicts', requests[2]['prompt'])
        self.assertFalse(self.check.sound_as_stated)
        payload = json.loads(requests[1]['prompt'].split('DATA:\n', 1)[1])
        self.assertEqual(set(payload), {'explanations', 'field_meanings'})

    def test_missing_explanation_retries_applicability(self):
        invalid = dict(review()); invalid.pop('case_reason')
        with self.responses(invalid, review(), audit()):
            validate_counterexample(self.row, self.check, self.models, self.trace)
        self.assertEqual(self.models.retries, 1)

    def test_unjustified_negative_retries_applicability(self):
        unsupported = review(False)
        unsupported['case_reason'] = 'The premises are unsupported.'
        finding = audit(False)
        finding['case_is_supported'].update(conclusion_quote=unsupported['case_reason'], justification_quote=None)
        with self.responses(unsupported, finding, review(), audit()):
            validate_counterexample(self.row, self.check, self.models, self.trace)
        self.assertEqual(self.models.retries, 1)

    def test_justified_negative_is_not_confused_with_missing_explanation(self):
        with self.responses(review(False), audit(False)):
            with self.assertRaisesRegex(ValueError, 'case_is_supported=false:'):
                validate_counterexample(self.row, self.check, self.models, self.trace)
        self.assertEqual(self.models.retries, 0)
        self.assertFalse(self.check.sound_as_stated)

    def test_supported_but_out_of_scope_case_stays_invalid(self):
        with self.responses(review(refutes=False), audit(refutes=False)):
            with self.assertRaisesRegex(ValueError, 'refutes_exact_assertion=false:'):
                validate_counterexample(self.row, self.check, self.models, self.trace)
        self.assertFalse(self.check.sound_as_stated)

    def test_reviewer_retries_are_bounded_and_cannot_publish(self):
        invalid = dict(review(), case_is_supported=False)
        with self.responses(*([invalid, audit()] * 3)):
            with self.assertRaises(ModelResponseError):
                validate_counterexample(self.row, self.check, self.models, self.trace)
        self.assertEqual(self.models.calls, 6)
        with patch.object(self.models, 'ask', side_effect=ModelResponseError('Exhausted')):
            check_background_counterexamples([self.row], self.models, self.trace)
        self.assertFalse(self.row['accepted'])
        self.assertEqual(self.row['review_status'], 'unresolved')
        self.assertEqual((self.trace.health.window, self.trace.health.minimum,
                          self.trace.health.max_failure_rate), (10, 5, 0.5))

    def test_fabricated_quotes_are_not_used_as_evidence(self):
        invented = audit()
        invented['case_is_supported']['justification_quote'] = 'A quotation that was not written.'
        with self.responses(*([review(), invented, invented, invented] * 3)):
            with self.assertRaises(ModelResponseError):
                validate_counterexample(self.row, self.check, self.models, self.trace)

    def test_uncertainty_withholds_without_fabricating_a_counterexample(self):
        with self.responses({'example': self.check.model_dump()}, review(False), audit(False),
                            {'example': dict(reason='The example does not establish either outcome.',
                                             sound_as_stated=False, counterexample=None)}):
            check_background_counterexamples([self.row], self.models, self.trace)
        self.assertFalse(self.row['accepted'])
        self.assertEqual(self.row['review_status'], 'rejected')

    def test_longer_complete_explanations_use_general_output_budget(self):
        value = review()
        value['case_reason'] += ' This conclusion concerns the stated premises rather than the original claim.' * 7
        finding = audit(); finding['case_is_supported'].update(
            conclusion_quote=value['case_reason'], justification_quote=value['case_reason'])
        with self.responses(value, finding):
            validate_counterexample(self.row, self.check, self.models, self.trace)
        self.assertEqual(self.requests()[0]['options']['num_predict'], 4096)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.code = {'pipeline/debate.py': 'old-debate', 'pipeline/settings.py': 'old-settings',
                     'pipeline/health.py': 'same-health', 'pipeline/registry.py': 'same-registry'}
        self.current = dict(self.code, **{'pipeline/debate.py': 'new-debate', 'pipeline/settings.py': 'new-settings'})
        self.settings = snapshot()
        self.config = dict(resolved_settings=self.settings, context_tokens=24576, think=False)
        self.models = {'models': [{'model': 'fixture', 'digest': 'unchanged'}]}
        self.policy = dict(id='test-version', changes={k: dict(before=self.code[k], after=self.current[k])
            for k in ['pipeline/debate.py', 'pipeline/settings.py']})
        data = dict(candidates=[dict(id='old', seed_id='completed', review_status='rejected', accepted=False)],
                    transcripts=[dict(seed=dict(id='completed'))], completed_seeds=['completed'])
        self.saved = dict(signature=fingerprint('input', self.config, self.code, self.models),
                          data=data, state={'health': {'background_candidate': [{'passed': False}]}},
                          artifacts={'artifacts/seeds.json': json.dumps({'selected': [{'id':'completed'}, {'id':'next'}]}),
                          'artifacts/debate_progress.json': json.dumps({k:data[k] for k in ['candidates','transcripts']})})
        self.environment = dict(code_sha256=self.code, model_details=dict(installed_models=self.models))
        self.manifest = dict(config=self.config,
                             artifacts={'artifacts/checkpoints/debate.json':
                                        {'sha256':hashlib.sha256(json.dumps(self.saved).encode()).hexdigest()}})

    def prepare(self, **kwargs):
        args=dict(checkpoint_bytes=json.dumps(self.saved).encode(), manifest=self.manifest,
                  environment=self.environment, text='input', current_code=self.current,
                  current_models=self.models, current_settings=self.settings, policy=self.policy)
        args.update(kwargs)
        return prepare_checkpoint(**args)

    def test_only_fingerprint_and_migration_metadata_change(self):
        original=copy.deepcopy(self.saved)
        prepared, migration=self.prepare()
        self.assertEqual(self.saved,original)
        for name in ['data','state','artifacts']: self.assertEqual(prepared[name],self.saved[name])
        self.assertEqual(prepared['signature'],fingerprint('input',self.config,self.current,self.models))
        self.assertEqual(migration['mode'],'pinned_validator_migration')

    def test_unrelated_code_change_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'exceed'):
            self.prepare(current_code=self.current|{'pipeline/health.py':'changed'})

    def test_unapproved_validator_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'not the approved'):
            self.prepare(current_code=self.current|{'pipeline/debate.py':'unreviewed'})

    def test_model_settings_input_and_checkpoint_integrity_are_checked(self):
        cases=[dict(current_models={'models':[]}), dict(current_settings={}), dict(text='different'),
               dict(checkpoint_bytes=json.dumps(self.saved).encode()+b' ')]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.prepare(**changes)

    def test_incomplete_seed_state_is_rejected(self):
        saved=copy.deepcopy(self.saved)
        saved['data']['candidates'][0]['seed_id']='next'
        raw=json.dumps(saved).encode()
        manifest=copy.deepcopy(self.manifest)
        manifest['artifacts']['artifacts/checkpoints/debate.json']['sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError,'incomplete seed'):
            self.prepare(checkpoint_bytes=raw,manifest=manifest)

    def test_same_code_still_uses_exact_compatibility(self):
        prepared,migration=self.prepare(current_code=self.code)
        self.assertEqual(prepared['signature'],self.saved['signature'])
        self.assertEqual(migration['mode'],'exact')

    def test_restore_preserves_state_and_skips_completed_seed_without_model_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=Trace(root/'source','source')
            target=Trace(root/'target','target')
            self.addCleanup(target.close); self.addCleanup(source.close)
            model=Mock(details=dict(installed_models=self.models))
            model.ask.side_effect=AssertionError('Completed seed must not run again')
            concepts,relations=ConceptRegistry(model,source),RelationRegistry(model,source)
            facts=FactIndex(relations)
            source.completed_items={('background_candidate','old')}
            source.unresolved_items=[dict(id='old',step='background_candidate',status='unresolved')]
            source.health.record('background_candidate',False,'Existing uncertainty','old')
            for key,value in self.saved['artifacts'].items(): source.text(key,value)
            with patch('pipeline.checkpoints.notebook.source_hashes',return_value=self.code):
                Checkpoints(source,model,'input',self.config,(concepts,relations,facts)).save('debate',self.saved['data'])
            raw=(source.directory/'artifacts/checkpoints/debate.json').read_bytes()
            manifest=copy.deepcopy(self.manifest)
            manifest['artifacts']['artifacts/checkpoints/debate.json']['sha256']=hashlib.sha256(raw).hexdigest()
            prepared,_=self.prepare(checkpoint_bytes=raw,manifest=manifest)
            target.save('migration/artifacts/checkpoints/debate.json',prepared)
            new_concepts,new_relations=ConceptRegistry(model,target),RelationRegistry(model,target)
            new_facts=FactIndex(new_relations)
            with patch('pipeline.checkpoints.notebook.source_hashes',return_value=self.current):
                target.checkpoints=VerifiedCheckpoints(target,model,'input',self.config,
                    (new_concepts,new_relations,new_facts),target.directory/'migration')
                result=debate([{'id':'completed'}],[],{},new_concepts,new_relations,new_facts,model,target)
            model.ask.assert_not_called()
            for name in ['candidates','transcripts']: self.assertEqual(result[name],prepared['data'][name])
            self.assertEqual(target.completed_items,source.completed_items)
            self.assertEqual(target.unresolved_items,source.unresolved_items)
            self.assertEqual(dict(target.health.history),dict(source.health.history))
            source.close(); target.close()


if __name__ == '__main__':
    unittest.main()
