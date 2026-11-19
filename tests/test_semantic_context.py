"""Context fidelity, scoped identity, ordering, and bounded independent verification."""
import copy
from pathlib import Path
import tempfile
import unittest

from pipeline.evaluation import (CONTEXT_FLAGS, ClaimMatch, EvaluationClaim,
                                 context_matches, reconstruction_context)
from pipeline.graph_quality import (CONTRACTS, Participant, refine_graph, require_quality,
                                    resolve_source_context, reference_obligations, ReviewPolicy)
from pipeline.graph_view import canonicalize_graph, concept_id
from pipeline.models import OutputLimitError
from pipeline.trace import Trace
from tests.test_graph_quality import Reviewer, sample


class SemanticContextTests(unittest.TestCase):
    def graph(self):
        names = ['cooling', 'temperature', 'vessel', 'air']
        nodes = [dict(id=concept_id(n), label=n, kind='concept', definition=n, origin='document') for n in names]
        return dict(nodes=nodes, edges=[dict(id='effect', source=nodes[0]['id'], target=nodes[1]['id'],
            label='reduces', definition=CONTRACTS['reduces'], origin='document', chunk_id='c1',
            participants=[dict(role='owner', scope='target', node=nodes[2]['id'])],
            purpose='prevent damage', timing='after filling', modality='may', conditions=None,
            source_order=40, evidence='PRIVATE source')])

    def test_different_owners_or_goals_do_not_collapse(self):
        graph = self.graph()
        second = copy.deepcopy(graph['edges'][0])
        second.update(id='other')
        second['participants'][0]['node'] = graph['nodes'][3]['id']
        third = copy.deepcopy(graph['edges'][0])
        third.update(id='other_goal', purpose='prepare storage')
        graph['edges'].extend([second, third])
        result = canonicalize_graph(graph)
        self.assertEqual(len(result['edges']), 3)
        ids = {n['id'] for n in result['nodes']}
        self.assertTrue(all(p['node'] in ids for e in result['edges'] for p in e['participants']))

    def test_reconstruction_retains_owner_goal_timing_and_source_order_without_quotes(self):
        graph = self.graph()
        first = copy.deepcopy(graph['edges'][0])
        first.update(id='earlier', source=graph['nodes'][2]['id'], target=graph['nodes'][3]['id'],
                     label='contains', source_order=0, participants=[])
        graph['edges'].append(first)
        result = reconstruction_context(graph, 'c1')
        self.assertEqual([r['relation'] for r in result['relations']], ['contains', 'reduces'])
        effect = result['relations'][1]
        self.assertEqual(effect['participants'], [dict(role='owner', scope='target', entity='vessel')])
        self.assertEqual((effect['purpose'], effect['timing'], effect['modality']), ('prevent damage', 'after filling', 'may'))
        self.assertNotIn('PRIVATE', str(result))

    def test_matching_core_fact_is_rejected_if_any_context_dimension_is_lost(self):
        for missing in CONTEXT_FLAGS:
            class Review:
                def ask(self, role, instruction, payload, schema, identifier):
                    self.role = role
                    flags = dict.fromkeys(CONTEXT_FLAGS, True)
                    flags[missing] = False
                    return schema(**flags, reason='The proposed equivalence omits a source qualification.')
            model = Review()
            claims = [EvaluationClaim(text='A qualified assertion', evidence='A qualified assertion')]
            accepted, audit = context_matches([ClaimMatch(original_index=0, reconstructed_index=0, reason='Same core')],
                'Original passage', 'Incomplete passage', claims, claims, model, 'test')
            self.assertEqual(accepted, [])
            self.assertFalse(audit[0]['accepted'])
            self.assertEqual(model.role, 'evaluation_context_review')

    def test_owner_only_participant_is_published_and_fingerprinted(self):
        class WithOwner(Reviewer):
            def ask(self, role, *args, **kwargs):
                result = super().ask(role, *args, **kwargs)
                if role == 'graph_fact_editor':
                    result.facts[0].participants = [Participant(role='owner', scope='target',
                        entity=dict(label='vessel', definition='Container whose property is affected.'))]
                    result.facts[0].purpose = 'prevent damage'
                return result
        with tempfile.TemporaryDirectory() as directory:
            trace = Trace(Path(directory)/'run', 'owner-test')
            try:
                graph = refine_graph(sample(), WithOwner(), trace)
                require_quality(graph, required=True)
                self.assertIn(concept_id('vessel'), [n['id'] for n in graph['nodes']])
                graph['edges'][0]['participants'][0]['scope'] = 'source'
                with self.assertRaisesRegex(ValueError, 'changed after'):
                    require_quality(graph, required=True)
            finally:
                trace.close()

    def test_background_budget_fallback_keeps_counterexample_rejection(self):
        class Exhausted(Reviewer):
            think = False
            options = dict(num_ctx=8192, num_predict=4096)
            def __init__(self):
                super().__init__()
                self.modes = []
            def ask(self, role, *args, **kwargs):
                if role == 'graph_background_challenge':
                    self.modes.append(self.think)
                    if self.think:
                        raise OutputLimitError('Budget exhausted')
                    return args[2](valid=False, counterexample='A supported exception exists.',
                                   required_qualification='Restrict the scope.', reason='Overclaim')
                return super().ask(role, *args, **kwargs)
        original = sample()
        background = copy.deepcopy(original['edges'][0])
        background.update(id='background', origin='background', evidence=None,
                          label='reduces', definition=CONTRACTS['reduces'])
        original['edges'].append(background)
        model = Exhausted()
        with tempfile.TemporaryDirectory() as directory:
            trace = Trace(Path(directory)/'run', 'background-budget')
            try:
                graph = refine_graph(original, model, trace, policy=ReviewPolicy(reasoning=True))
                self.assertEqual(model.modes[:2], [True, False])
                self.assertEqual(sum(e['origin'] == 'background' for e in graph['edges']), 0)
                self.assertFalse(model.think)
                self.assertEqual(model.options, dict(num_ctx=8192, num_predict=4096))
            finally:
                trace.close()

    def test_dismissing_background_objection_does_not_bypass_fact_verification(self):
        class Contested(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_background_challenge':
                    return schema(valid=False, counterexample='An example outside the stated scope.',
                                  required_qualification=None, reason='Objection')
                if role == 'graph_background_objection_review':
                    return schema(counterexample_applies=False, qualification_needed=False,
                                  assertion_supported=True, reason='The objection does not apply.')
                result = super().ask(role, instruction, payload, schema, identifier, validator)
                if role == 'graph_fact_reviewer' and payload['original']['origin'] == 'background':
                    result.facts[0].supported = False
                    result.facts[0].reason = 'The independent verifier remains uncertain.'
                return result
        original = sample()
        background = copy.deepcopy(original['edges'][0])
        background.update(id='background', origin='background', evidence=None,
                          label='reduces', definition=CONTRACTS['reduces'])
        original['edges'].append(background)
        with tempfile.TemporaryDirectory() as directory:
            trace = Trace(Path(directory)/'run', 'objection-test')
            try:
                graph = refine_graph(original, Contested(), trace)
                self.assertFalse(any(e['origin'] == 'background' for e in graph['edges']))
            finally:
                trace.close()

    def test_ambiguous_reference_cannot_be_assigned_an_antecedent(self):
        def ask(role, instruction, payload, schema, identifier, validator=None, **kwargs):
            result = schema(references=[dict(mention='it', antecedent='vessel', resolved_meaning='unclear',
                                            evidence='It moved it.', ambiguous=True)])
            validator(result)
            return result
        with self.assertRaisesRegex(ValueError, 'ambiguous reference'):
            resolve_source_context(dict(id='c1', text='It moved it.'), ask, 2,
                                   [dict(id='vessel-id', label='vessel')])

    def test_canonical_reference_choices_bind_to_ids_without_guessing(self):
        def ask(role, instruction, payload, schema, identifier, validator=None, **kwargs):
            if role == 'graph_reference_verifier':
                return schema(valid=True, issues=[])
            if role == 'graph_reference_binding_reviewer':
                return schema(antecedent='vessel', owned_property='temperature', performed_action=None)
            result = schema(references=[dict(mention='its temperature', antecedent='vessel',
                resolved_meaning='temperature of the vessel', evidence='The vessel lowers its temperature.',
                ambiguous=False, owned_property='temperature', performed_action=None)])
            validator(result)
            return result
        result = resolve_source_context(dict(id='c1', text='The vessel lowers its temperature.'), ask, 2,
            [dict(id='vessel-id', label='vessel'), dict(id='property-id', label='temperature')])
        self.assertEqual(result['references'][0]['antecedent_node'], 'vessel-id')
        self.assertEqual(result['references'][0]['owned_property_node'], 'property-id')

    def test_core_fact_approval_cannot_publish_a_missing_owner(self):
        from pipeline.models import ModelResponseError
        class MissingOwner(Reviewer):
            def ask(self, role, *args, **kwargs):
                if role == 'graph_source_repair':
                    raise ModelResponseError('Missing owner could not be repaired')
                result = super().ask(role, *args, **kwargs)
                if role == 'graph_fact_context_reviewer':
                    result.ownership_explicit = False
                    result.issues = ['The owner of the affected property is absent.']
                return result
        with tempfile.TemporaryDirectory() as directory:
            trace = Trace(Path(directory)/'run', 'missing-owner')
            try:
                with self.assertRaisesRegex(ModelResponseError, 'Missing owner'):
                    refine_graph(sample(), MissingOwner(), trace)
                self.assertFalse((trace.directory/'artifacts/graph.json').exists())
            finally:
                trace.close()

    def test_reference_binding_correction_requires_separate_source_verification(self):
        for approved in (False, True):
            def ask(role, instruction, payload, schema, identifier, validator=None, **kwargs):
                if role == 'graph_reference_verifier':
                    return schema(valid=True, issues=[])
                if role == 'graph_reference_binding_reviewer':
                    return schema(antecedent='vessel', owned_property='temperature', performed_action=None)
                if role == 'graph_reference_binding_verifier':
                    return schema(original_valid=False, alternative_valid=approved,
                                  reason='Source confirms correction' if approved else 'Unresolved identity')
                result = schema(references=[dict(mention='its temperature', antecedent='vessel',
                    resolved_meaning='temperature of the vessel', evidence='The vessel lowers its temperature.',
                    ambiguous=False, owned_property=None, performed_action=None)])
                validator(result)
                return result
            arguments = (dict(id='c1', text='The vessel lowers its temperature.'), ask, 1,
                [dict(id='vessel-id', label='vessel'), dict(id='property-id', label='temperature')])
            if approved:
                result = resolve_source_context(*arguments)
                self.assertEqual(result['references'][0]['owned_property_node'], 'property-id')
            else:
                with self.assertRaisesRegex(ValueError, 'remain unresolved'):
                    resolve_source_context(*arguments)

    def test_verified_reference_requires_the_actual_owner_and_correct_scope(self):
        graph = self.graph()
        edge = graph['edges'][0]
        nodes = {n['id']: n for n in graph['nodes']}
        bindings = [dict(antecedent_node=concept_id('vessel'), owned_property_node=concept_id('temperature'),
                         evidence='its temperature', ambiguous=False)]
        self.assertEqual(reference_obligations(edge, bindings, nodes), [])
        edge['participants'][0]['scope'] = 'source'
        self.assertEqual(len(reference_obligations(edge, bindings, nodes)), 1)
        edge['participants'][0].update(scope='target', node=concept_id('air'))
        self.assertEqual(len(reference_obligations(edge, bindings, nodes)), 1)
        edge['participants'] = []
        self.assertEqual(len(reference_obligations(edge, bindings, nodes)), 1)


if __name__ == '__main__':
    unittest.main()
