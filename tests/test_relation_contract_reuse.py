"""Offline checks for existing-name proposals during relation definition."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ollama import ChatResponse
from pipeline.models import Models, ModelResponseError, ModelServiceError
from pipeline.registry import RelationRegistry
from pipeline.trace import Trace
from tests.test_semantics import FixtureModel, equivalence


class RelationContractReuseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / 'run', 'fixture')
        self.addCleanup(self.trace.close)
        self.context = dict(evidence='Fine-tuned LLMs usually have a very large number of parameters.',
                            modality='usually', conditions='after fine-tuning',
                            argument_qualifiers=['very large'])

    def make_registry(self, verdict, *, resolver_key=None):
        def respond(role, payload):
            if role == 'relation_resolver':
                return dict(key=resolver_key, exact_meaning=bool(resolver_key),
                            same_direction=bool(resolver_key), reason='Fixture retrieval')
            if role == 'relation_definition':
                return dict(key='has_parameter_count',
                            definition='Indicates that an entity possesses a count of parameters.',
                            symmetric=False, inverse=None)
            if role == 'relation_match_verifier':
                if isinstance(verdict, Exception):
                    raise verdict
                return verdict(payload) if callable(verdict) else verdict
            self.fail('Unexpected model role: ' + role)

        model = FixtureModel(respond)
        registry = RelationRegistry(model, self.trace)
        registry.entries.update(
            has=dict(key='has', definition='Possesses an attribute.', symmetric=False, inverse=None),
            has_parameter_count=dict(key='has_parameter_count',
                                     definition='Possesses a specific attribute or quantity.',
                                     symmetric=False, inverse=None))
        return model, registry

    def resolve(self, registry, context=None, entity_id='occurrence'):
        return registry.resolve('has', 'Indicates possession of a property.',
                                'fine tuned llm', 'parameter count',
                                self.context if context is None else context, entity_id)

    def test_collision_reuses_verified_stored_contract_without_overwriting_it(self):
        model, registry = self.make_registry(equivalence())
        before = copy.deepcopy(registry.entries)
        self.assertEqual(self.resolve(registry), 'has_parameter_count')
        self.assertEqual(registry.entries, before)
        verification = [p for role, _, p in model.requests if role == 'relation_match_verifier']
        self.assertEqual(len(verification), 1)
        payload = verification[0]
        self.assertEqual(payload['occurrence']['context'], self.context)
        self.assertEqual(payload['proposed_contract'], before['has_parameter_count'])
        for key in ('conditions', 'modality', 'argument_qualifiers'):
            self.assertEqual(payload['qualified_original'][key], self.context[key])
            self.assertEqual(payload['qualified_proposal'][key], self.context[key])
        for key, value in [('source', 'fine tuned llm'), ('target', 'parameter count')]:
            self.assertEqual(payload['qualified_proposal'][key], value)
        saved = json.loads((self.trace.directory / 'artifacts/relations.json').read_text())
        self.assertEqual(saved['decisions'][-1]['canonical_key'], 'has_parameter_count')

    def test_failed_meaning_direction_or_types_prevent_reuse(self):
        for dimension in ('exact_meaning', 'same_direction', 'compatible_types'):
            with self.subTest(dimension=dimension):
                model, registry = self.make_registry(dict(equivalence(), **{dimension: False}))
                before = copy.deepcopy(registry.entries)
                with self.assertRaisesRegex(ValueError, 'already has a different'):
                    self.resolve(registry)
                self.assertEqual(registry.entries, before)
                self.assertEqual(sum(r[0] == 'relation_match_verifier' for r in model.requests), 1)
                self.assertEqual(registry.decisions, [])

    def test_existing_rejection_is_not_rechecked_to_obtain_a_pass(self):
        model, registry = self.make_registry(equivalence(False), resolver_key='has_parameter_count')
        with self.assertRaisesRegex(ValueError, 'already has a different'):
            self.resolve(registry)
        self.assertEqual(sum(r[0] == 'relation_match_verifier' for r in model.requests), 1)

    def test_collision_verification_is_specific_to_each_occurrence(self):
        def verdict(payload):
            return equivalence(payload['qualified_original']['modality'] == 'usually')
        model, registry = self.make_registry(verdict)
        self.assertEqual(self.resolve(registry), 'has_parameter_count')
        with self.assertRaisesRegex(ValueError, 'already has a different'):
            self.resolve(registry, dict(self.context, modality='never'), 'another-occurrence')
        self.assertEqual(sum(r[0] == 'relation_match_verifier' for r in model.requests), 2)
        self.assertEqual(len(registry.decisions), 1)

    def test_verifier_failure_does_not_authorize_reuse(self):
        for error in (ModelResponseError('Invalid review'), ModelServiceError('Unavailable reviewer')):
            with self.subTest(error=type(error).__name__):
                _, registry = self.make_registry(error)
                before = copy.deepcopy(registry.entries)
                with self.assertRaises(type(error)):
                    self.resolve(registry)
                self.assertEqual(registry.entries, before)
                self.assertEqual(registry.decisions, [])

    def test_collision_cannot_bypass_protected_builtin_contract(self):
        def respond(role, payload):
            if role == 'relation_match_verifier':
                return equivalence(payload['proposed_contract']['key'] == 'causes')
            if role == 'relation_resolver':
                return dict(key=None, exact_meaning=False, same_direction=False, reason='No match')
            if role == 'relation_definition':
                return dict(key='causes', definition='Produces the target.', symmetric=False, inverse=None)
            self.fail(role)
        model = FixtureModel(respond)
        registry = RelationRegistry(model, self.trace)
        before = copy.deepcopy(registry.entries)
        with self.assertRaises(ValueError):
            registry.resolve('enables', 'Permits something.', 'sunlight', 'evaporation', {}, 'one')
        self.assertEqual(registry.entries, before)
        self.assertFalse(any(role == 'relation_match_verifier' and p['proposed_contract']['key'] == 'causes'
                             for role, _, p in model.requests))

    def test_real_model_validation_and_cache_reuse_verify_collision(self):
        responses = [
            dict(key=None, exact_meaning=False, same_direction=False, search_uncertain=False,
                 reason='Conclusive retrieval decision; exercise definition collision verification next.'),
            dict(key='has_parameter_count', definition='An entity possesses a parameter count.',
                 symmetric=False, inverse=None),
            equivalence(),
        ]
        with patch('pipeline.models.Client') as client:
            client.return_value.chat.side_effect = [
                ChatResponse(message=dict(role='assistant', content=json.dumps(value)), done_reason='stop')
                for value in responses]
            models = Models(self.trace, 'fixture', 'embed', 'http://localhost')
            _, registry = self.make_registry(equivalence())
            registry.models = models
            before = copy.deepcopy(registry.entries)
            self.assertEqual(self.resolve(registry), 'has_parameter_count')
            self.assertEqual(models.retries, 0)
            self.assertEqual(client.return_value.chat.call_count, 3)
            # Cached outer responses must still invoke semantic validation.
            with patch.object(registry, '_verify_contract', return_value=type('Verdict', (), equivalence(False))()):
                client.return_value.chat.side_effect = [
                    ChatResponse(message=dict(role='assistant', content=json.dumps(responses[1])), done_reason='stop')
                    for _ in range(3)]
                with self.assertRaises(ModelResponseError):
                    self.resolve(registry, entity_id='second')
            self.assertEqual(registry.entries, before)
            self.assertEqual(len(registry.decisions), 1)


if __name__ == '__main__':
    unittest.main()
