"""Topic-free fixtures for background naming, attachment, repair and budgeting."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import Field, create_model
from pipeline.background_context import seed_neighborhood, connectivity_context
from pipeline.debate import debate, FactRepair, connected_explanation
from pipeline.models import Models, request_budget
from pipeline.records import Record
from pipeline.registry import ConceptRegistry, RelationRegistry, FactIndex
from pipeline.repair_budget import RepairContext, repair_candidates
from pipeline.settings import setting, budgeted_pages


class MemoryTrace:
    run_id = 'fixture'

    def __init__(self):
        self.events, self.saved = [], {}

    def emit(self, event, **data):
        self.events.append((event, copy.deepcopy(data)))
        return str(len(self.events))

    def save(self, path, value):
        self.saved[path] = copy.deepcopy(value)


def concept(name):
    return dict(name=name, definition=name, kind='entity')


def fact(sentence, gap='gap'):
    return dict(intended_fact=sentence, confidence=1, reason='A, B and C are related as stated.',
                added_knowledge=sentence, gap_ids=[gap])


class BackgroundConnectionTests(unittest.TestCase):
    def test_neighborhood_contains_only_seed_and_actual_connections(self):
        rows = [dict(id='ab', source='a', relation='has_part', target='b'),
                dict(id='cd', source='c', relation='has_part', target='d')]
        result = seed_neighborhood(dict(id='seed', concept='a'), rows,
                                   {name: concept(name) for name in 'abcd'})
        self.assertEqual([c['name'] for c in result['existing_concepts']], ['a', 'b'])
        self.assertEqual([r['id'] for r in result['existing_connections']], ['ab'])
        result['existing_connections'][0]['target'] = 'c'
        self.assertEqual(rows[0]['target'], 'b')

    def test_repair_minimum_preserves_topology_and_qualified_connections(self):
        seed = dict(id='seed', concept='a')
        known = dict(id='ab', source='a', relation='has_part', target='b',
                     conditions='under C', argument_qualifiers=['with D'])
        row = dict(id='candidate', source='c', target='d', gap_ids=['gap'],
                   gaps=[dict(id='gap', source_chunk_ids=['chunk'])],
                   rejection_stage='connectivity', decision_reason='No path',
                   intended_fact='C changes D.', reason='C changes D.', chunk_id='chunk')
        plan = RepairContext(row, seed, {}, [dict(id='chunk', text='A has B.')], [known], [])
        for _, payload in plan.variants:
            graph = payload['essential']['connectivity']
            self.assertEqual(graph['unconnected_concepts'], ['c', 'd'])
            self.assertEqual(graph['attachment_concepts'], ['a', 'b'])
            self.assertEqual(graph['existing_connections'][0]['conditions'], 'under C')
            self.assertEqual(graph['existing_connections'][0]['argument_qualifiers'], ['with D'])

    def test_number_variants_use_context_and_preserve_explicit_contrast(self):
        calls = []
        def ask(role, instruction, payload, schema, entity_id, **kwargs):
            calls.append(role)
            self.assertEqual(role, 'concept_alias_verifier')
            contrast = payload['context'].get('contrast', False)
            return schema.model_validate(dict(same_concept=not contrast, same_scope=not contrast,
                reason='The reference is determined by the supplied context.',
                **({'distinction': 'An item and a group.' if contrast else None}
                   if 'distinction' in schema.model_fields else {})))
        registry = ConceptRegistry(SimpleNamespace(ask=ask), MemoryTrace())
        registry.resolve(concept('A B'), {}, 'first')
        self.assertEqual(registry.resolve_background(concept('A Bs'), {}, 'second'), 'a b')
        self.assertEqual(registry.resolve_background(concept('A-B'), {}, 'third'), 'a b')
        self.assertEqual(registry.resolve_background(concept('A Bs'), {'contrast': True}, 'fourth'), 'a bs')
        self.assertEqual(set(registry.entries), {'a b', 'a bs'})
        self.assertEqual(registry.aliases['a bs'], 'a bs')
        self.assertEqual(calls, ['concept_alias_verifier', 'concept_alias_verifier'])

    def test_spelling_resemblance_cannot_override_different_meaning(self):
        def ask(role, instruction, payload, schema, entity_id, **kwargs):
            return schema.model_validate(dict(same_concept=False, same_scope=True,
                                             distinction='Different referents.', reason='Different referents.'))
        registry = ConceptRegistry(SimpleNamespace(ask=ask), MemoryTrace())
        registry.resolve(concept('B'), {}, 'first')
        self.assertEqual(registry.resolve_background(concept('Bs'), {}, 'second'), 'bs')

    def test_number_variant_is_not_displaced_by_a_related_definition(self):
        def ask(role, instruction, payload, schema, entity_id, **kwargs):
            self.assertEqual(role, 'concept_alias_verifier')
            self.assertEqual(payload['existing_concept']['name'], 'a b')
            return schema.model_validate(dict(same_concept=True, same_scope=True,
                                             distinction=None, reason='Same term in generic use.'))
        registry = ConceptRegistry(SimpleNamespace(ask=ask, identity_candidates=1), MemoryTrace())
        registry.resolve(concept('A B'), {}, 'first')
        registry.resolve(dict(name='A C', definition='A Bs', kind='entity'), {}, 'second')
        self.assertEqual(registry.resolve_background(concept('A Bs'), {}, 'third'), 'a b')

    def test_connecting_repairs_cannot_change_question_or_bypass_other_rejections(self):
        for rejection, gap, correction in [('connectivity', 'other', fact('B changes C.')),
                                           ('novelty', 'gap', fact('B changes C.')),
                                           ('connectivity', 'gap', None)]:
            with self.subTest(rejection=rejection, gap=gap, correction=correction):
                seed = dict(id='seed', concept='a')
                row = dict(id='candidate', source='b', target='c', gap_ids=['gap'],
                    gaps=[dict(id='gap', source_chunk_ids=['chunk'])], chunk_id='chunk',
                    rejection_stage=rejection, decision_reason='Rejected.', intended_fact='B changes C.')
                def ask(role, instruction, payload, schema, entity_id, validator=None, **kwargs):
                    value = schema.model_validate(dict(reason='A proposed connection.', corrected_fact=correction,
                                                       connecting_facts=[fact('A has B.', gap=gap)]))
                    validator(value)
                    return value
                with self.assertRaises(ValueError):
                    repair_candidates([row], seed, {}, [dict(id='chunk', text='A relates to C.')], [], [],
                                      SimpleNamespace(ask=ask), MemoryTrace(), FactRepair, 'Repair the assertion.')

    @patch('pipeline.models.Client')
    def test_separate_format_schema_does_not_consume_output_budget(self, client):
        trace = MemoryTrace()
        schema = create_model('Answer', __base__=Record,
            answer=(str, Field(description='A' * setting('model', 'context_tokens'))))
        client.return_value.chat.return_value = SimpleNamespace(model_dump=lambda **kw:
            dict(message=dict(content=json.dumps({'answer': 'A'})), done_reason='stop'))
        models = Models(trace, 'configured', 'configured', None)
        models.ask('planner', 'Describe A.', {'text': 'A'}, schema, 'plan')
        call = client.return_value.chat.call_args.kwargs
        self.assertEqual(call['format'], schema.model_json_schema())
        self.assertEqual(call['options']['num_predict'], setting('model', 'max_output_tokens'))
        budget = request_budget('Describe A.', {'text': 'A'}, schema, models.options)
        self.assertFalse(budget['schema_in_prompt'])
        self.assertEqual(budget['total_tokens'], budget['prompt_tokens'] + budget['safety_tokens']
                         + budget['reserved_output_tokens'])
        self.assertGreater(budget['schema_tokens'], 0)
        small = create_model('Small', __base__=Record, answer=(str, ...))
        self.assertEqual(list(budgeted_pages(['A', 'B'], models, schema=schema)),
                         list(budgeted_pages(['A', 'B'], models, schema=small)))

    def run_connected_repair(self, reject_connection=False):
        trace = MemoryTrace()
        seen = []
        seed = dict(id='seed', concept='a', definition='A', kind='entity', chunk_id='chunk',
                    paragraph_id='paragraph', gaps=[dict(id='gap', question='How does A relate to C?',
                    source_chunk_ids=['chunk'])])
        def ask(role, instruction, payload, schema, entity_id, validator=None, **kwargs):
            if role == 'proposer':
                self.assertIn('A has B; B does C', instruction)
                value = dict(gap_analysis='An explanation is missing.', facts=[fact('B changes C.')], reason='A gap.')
            elif role == 'background_proposal_repair':
                self.assertEqual(payload['essential']['connectivity']['seed'], 'a')
                self.assertEqual(payload['essential']['connectivity']['unconnected_concepts'], ['b', 'c'])
                value = dict(reason='Add the justified connection.', corrected_fact=fact('B changes C.'),
                             connecting_facts=[fact('A has B.')])
            else:
                self.fail(role)
            result = schema.model_validate(value)
            if validator: validator(result)
            return result
        model = SimpleNamespace(ask=ask)
        concepts = SimpleNamespace(entries={name: concept(name) for name in 'abc'},
                                   resolve_background=lambda mention, context, identifier: mention['name'])
        relations = RelationRegistry(model, trace)
        facts = FactIndex(relations)
        def construct(models, role, instruction, items, schema, entity_id, shared=None, **kwargs):
            self.assertEqual(role, 'background_link_constructor')
            self.assertEqual(shared['seed']['concept'], 'a')
            self.assertEqual([c['name'] for c in shared['existing_concepts']], ['a'])
            self.assertIn('MAIN clause', instruction)
            return {row['id']: dict(source=concept('a' if row['intended_fact']=='A has B.' else 'b'),
                        target=concept('b' if row['intended_fact']=='A has B.' else 'c'),
                        relation='has_part', relation_definition=relations.entries['has_part']['definition'],
                        conditions=None, modality=None, argument_qualifiers=[]) for row in items}
        def novel(rows, *args):
            seen.extend(('novelty', row['id']) for row in rows)
            return {row['id']: dict(status='new') for row in rows}
        def review(rows, *args):
            for row in rows:
                seen.append(('review', row['id']))
                row['accepted'] = not (reject_connection and row.get('repair_kind')=='connection')
                row['decision_reason'] = 'Reviewed.'
                row['review_status'] = 'completed' if row['accepted'] else 'rejected'
        def counterexamples(rows, *args):
            seen.extend(('counterexample', row['id']) for row in rows)
        with patch('pipeline.debate.ask_keyed', side_effect=construct), \
             patch('pipeline.debate.correct_polarity', side_effect=lambda link,*a:link), \
             patch('pipeline.debate.check_representation', return_value=True), \
             patch('pipeline.debate.check_novelty_many', side_effect=novel), \
             patch('pipeline.debate.check_novelty', return_value={'status':'new'}), \
             patch('pipeline.debate.review_background_many', side_effect=review), \
             patch('pipeline.debate.check_background_counterexamples', side_effect=counterexamples):
            result = debate([seed], [dict(id='chunk',text='A relates to C.')],
                            dict(overview='A',topics=[]), concepts, relations, facts, model, trace)
        return result, facts, seen

    def test_corrected_fact_and_connection_each_pass_all_admission_stages(self):
        result, facts, seen = self.run_connected_repair()
        self.assertFalse(result['candidates'][0]['accepted'])
        self.assertEqual(len(facts.rows), 2)
        for row in facts.rows:
            for stage in ('novelty','review','counterexample'):
                self.assertIn((stage,row['id']), seen)
        self.assertEqual(result['candidates'][0]['repair_candidate_ids'],
                         [row['id'] for row in result['candidates'][1:]])

    def test_rejected_connection_does_not_admit_its_supporting_fact(self):
        result, facts, seen = self.run_connected_repair(reject_connection=True)
        self.assertFalse(facts.rows)
        self.assertFalse(any(row['accepted'] for row in result['candidates']))
        self.assertEqual(result['candidates'][1]['rejection_stage'], 'connectivity')


if __name__ == '__main__':
    unittest.main()
