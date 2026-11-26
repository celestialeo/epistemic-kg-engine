"""Domain-independent regression fixtures for explanation construction and repair."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.debate import (ExplanationGraph, ExplanationRepair, explanation_links,
                             debate, explanation_neighborhood, PlannedFact, validate_planned_explanation,
                             explanation_skeleton, explanation_schema, materialize_explanation)
from pipeline.registry import RelationRegistry, FactIndex
from pipeline.repair_budget import RepairContext, repair_candidates
from pipeline.models import ModelResponseError


class Trace:
    def __init__(self):
        self.saved, self.events = {}, []
    def save(self, path, value):
        self.saved[path] = copy.deepcopy(value)
    def emit(self, event, **data):
        self.events.append((event, copy.deepcopy(data)))


def node(name):
    return dict(name=name, definition=name, kind='entity')


def fact(sentence):
    return dict(intended_fact=sentence, confidence=1, reason=sentence,
                added_knowledge=sentence, gap_ids=['gap'],
                source_concept='a' if sentence == 'A has B.' else 'b',
                target_concept='b' if sentence == 'A has B.' else 'c')


def graph(rows):
    return dict(nodes=[dict(node(x), node_id=x) for x in 'abc'], links=[
        dict(fact_id=row['id'], source_id='a' if row['intended_fact']=='A has B.' else 'b',
             target_id='b' if row['intended_fact']=='A has B.' else 'c',
             relation='has_part', relation_definition='SOURCE has TARGET as a part.',
             conditions=None, modality=None, argument_qualifiers=[]) for row in rows])


class ExplanationGroupTests(unittest.TestCase):
    def test_fixed_topology_prevents_missing_nodes_and_changed_endpoints(self):
        rows = [dict(id='one', **fact('A has B.')), dict(id='two', **fact('B has C.'))]
        skeleton = explanation_skeleton(rows)
        self.assertEqual(len(skeleton['nodes']), 3)
        self.assertEqual(skeleton['links']['one']['target_id'], skeleton['links']['two']['source_id'])
        schema = explanation_schema(skeleton)
        value = dict(nodes={key: dict(definition=name, kind='entity') for key, name in skeleton['nodes'].items()},
                     links={key: dict(relation='has_part', relation_definition='SOURCE has TARGET as a part.',
                         conditions=None, modality=None, argument_qualifiers=[]) for key in skeleton['links']})
        assembled = materialize_explanation(schema.model_validate(value), skeleton)
        self.assertEqual(explanation_links(assembled, rows)['one']['target']['name'], 'b')
        for mutation in ('missing_node', 'changed_endpoint', 'hidden_name'):
            bad = copy.deepcopy(value)
            if mutation == 'missing_node': del bad['nodes']['node_0002']
            if mutation == 'changed_endpoint': bad['links']['one']['target_id'] = 'node_0003'
            if mutation == 'hidden_name': bad['nodes']['node_0002']['name'] = 'different'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                schema.model_validate(bad)

    def test_shared_intermediate_is_a_single_declaration(self):
        rows = [dict(id='one', **fact('A has B.')), dict(id='two', **fact('B has C.'))]
        links = explanation_links(ExplanationGraph.model_validate(graph(rows)), rows)
        self.assertEqual(links['one']['target'], links['two']['source'])

    def test_invalid_references_duplicates_and_hidden_claims_fail(self):
        rows = [dict(id='one', **fact('A has B.')), dict(id='two', **fact('B has C.'))]
        for kind in ('dangling', 'duplicate_node', 'duplicate_name', 'extra_fact', 'missing_fact'):
            with self.subTest(kind=kind):
                value = graph(rows)
                if kind == 'dangling': value['links'][0]['source_id'] = 'missing'
                if kind == 'duplicate_node': value['nodes'].append(value['nodes'][0])
                if kind == 'duplicate_name': value['nodes'].append(dict(node('a'), node_id='another'))
                if kind == 'extra_fact': value['links'].append(dict(value['links'][0], fact_id='invented'))
                if kind == 'missing_fact': value['links'].pop()
                with self.assertRaises(ValueError):
                    explanation_links(ExplanationGraph.model_validate(value), rows)

    def test_unused_declarations_cannot_enter_the_graph_or_connect_links(self):
        rows = [dict(id='one', **fact('B has C.'))]
        links = explanation_links(ExplanationGraph.model_validate(graph(rows)), rows)
        endpoints = {link[side]['name'] for link in links.values() for side in ('source', 'target')}
        self.assertEqual(endpoints, {'b', 'c'})
        self.assertNotIn('a', endpoints)

    def test_contract_must_declare_endpoint_roles_instead_of_repeating_a_fact(self):
        rows = [dict(id='one', **fact('B has C.'))]
        value = graph(rows)
        value['links'][0]['relation_definition'] = 'B has C.'
        with self.assertRaises(ValueError):
            explanation_links(ExplanationGraph.model_validate(value), rows)

    def test_planning_requires_an_explicit_bridge(self):
        seed = dict(id='seed', concept='a')
        unsupported = PlannedFact(**fact('B has C.'))
        with self.assertRaisesRegex(ValueError, 'disconnected'):
            validate_planned_explanation([unsupported], seed, [])
        validate_planned_explanation([PlannedFact(**fact('A has B.')), unsupported], seed, [])
        validate_planned_explanation([unsupported], seed,
                                     [dict(id='known', source='a', target='b')])

    def test_plan_cannot_name_a_related_process_instead_of_the_asserted_object(self):
        value = PlannedFact(**(fact('A has B.') | dict(target_concept='production of B')))
        with self.assertRaisesRegex(ValueError, 'explicitly name its planned target'):
            validate_planned_explanation([value], dict(id='seed', concept='a'), [])
        value.intended_fact = 'A supports production of B.'
        validate_planned_explanation([value], dict(id='seed', concept='a'), [])
        self.assertEqual(list(PlannedFact.model_fields)[:2], ['source_concept', 'target_concept'])

    def test_plan_does_not_treat_changing_a_property_as_the_property(self):
        value = PlannedFact(**(fact('A has B.') | dict(intended_fact='Reducing A changes B.')))
        with self.assertRaisesRegex(ValueError, 'Begin intended_fact'):
            validate_planned_explanation([value], dict(id='seed', concept='a'), [])

    def test_leading_article_does_not_change_a_planned_subject(self):
        for prefix in ('The ', 'A ', 'An ', ''):
            with self.subTest(prefix=prefix):
                value = PlannedFact(**(fact('A has B.') | dict(source_concept='instrument', target_concept='quantity',
                    intended_fact=prefix+'instrument measures quantity.')))
                validate_planned_explanation([value], dict(id='seed', concept='instrument'), [])
        value = PlannedFact(**(fact('A has B.') | dict(intended_fact='The reduction of A changes B.')))
        with self.assertRaisesRegex(ValueError, 'Begin intended_fact'):
            validate_planned_explanation([value], dict(id='seed', concept='a'), [])

    def test_constructor_cannot_move_a_planned_bridge_into_qualifiers(self):
        rows = [dict(id='one', **fact('A has B.'))]
        value = graph(rows)
        value['links'][0]['target_id'] = 'c'
        value['links'][0]['argument_qualifiers'] = ['using B']
        with self.assertRaisesRegex(ValueError, 'planned target'):
            explanation_links(ExplanationGraph.model_validate(value), rows)

    def run_group(self, reject_bridge=False, invalid_bridge=False, accepted_member=False, reject_support=False,
                  known_bridge=False, malformed_member=False, disconnected_plan=False, malformed_repair=None):
        trace, seen, repair_rounds = Trace(), [], []
        seed = dict(id='seed', concept='a', definition='A', kind='entity', chunk_id='chunk',
                    paragraph_id='paragraph', gaps=[dict(id='gap', question='How does A relate to C?',
                    source_chunk_ids=['chunk'])])
        def ask(role, instruction, payload, schema, entity_id, validator=None, **kwargs):
            if role == 'proposer':
                value = dict(gap_analysis='Missing explanation.',
                             facts=([fact('B has C.')] if known_bridge or disconnected_plan else [fact('A has B.'), fact('B has C.')]), reason='Gap.')
                if malformed_member:
                    value['facts'][1]['source_concept'] = 'a different participant'
            elif role == 'background_proposal_repair':
                repair_rounds.append(entity_id)
                essential = payload['essential']
                if not accepted_member and not known_bridge and len(repair_rounds) == 1:
                    self.assertIn('connectivity', [member['rejection_stage'] for member in essential['explanation_members']])
                self.assertEqual(essential['connectivity']['seed'], 'a')
                self.assertEqual(essential['connectivity']['attachment_concepts'], ['a', 'b'] if known_bridge else ['a'])
                value = dict(reason='Supply a justified bridge.', corrected_facts=[fact('B has C.'), fact('A has B.')])
                if malformed_repair:
                    value['corrected_facts'][0 if malformed_repair == 'support' else 1]['source_concept'] = 'unasserted participant'
            elif role == 'background_link_constructor':
                fixed = payload['fixed_topology']
                value = dict(nodes={key: dict(definition=name, kind='entity') for key, name in fixed['nodes'].items()},
                    links={row['id']: dict(relation='has_part', relation_definition='SOURCE has TARGET as a part.',
                        conditions=None, modality=None, argument_qualifiers=[]) for row in payload['facts']})
            elif role == 'relation_match_verifier':
                value = dict(exact_meaning=True, same_direction=True, compatible_types=True, reason='Same use.')
            else:
                self.fail(role)
            result = schema.model_validate(value)
            if validator: validator(result)
            return result
        models = SimpleNamespace(ask=ask)
        concepts = SimpleNamespace(entries={x: node(x) for x in 'abc'},
            resolve_background=lambda mention, context, identifier: mention['name'])
        relations = RelationRegistry(models, trace)
        facts = FactIndex(relations)
        if known_bridge:
            facts.add(dict(id='known', source='a', target='b', relation='has_part', origin='document',
                           accepted=True, conditions=None, modality=None, argument_qualifiers=[]))
        def representation(row, *args):
            seen.append(('representation', row['id']))
            original_failure = not row['repair_attempt'] and row['intended_fact'] == ('B has C.' if accepted_member or known_bridge else 'A has B.')
            if original_failure or (invalid_bridge and row['intended_fact'] == 'A has B.'):
                row['representation_check'] = dict(reason='Invalid bridge representation.')
                return False
            return True
        def novel(rows, *args):
            seen.extend(('novelty', row['id']) for row in rows)
            return {r['id']: dict(status='duplicate', reason='Already represented by known', evidence_ids=['known'])
                    if known_bridge and r['intended_fact']=='A has B.' else dict(status='new') for r in rows}
        def review(rows, *args):
            for row in rows:
                seen.append(('review', row['id']))
                rejected = row['repair_attempt'] and ((reject_bridge and row['intended_fact']=='A has B.')
                            or (reject_support and row['intended_fact']=='B has C.'))
                row.update(accepted=not rejected,
                           decision_reason='Checked.', review_status='completed')
        with patch('pipeline.debate.correct_polarity', side_effect=lambda link,*a:link), \
             patch('pipeline.debate.check_representation', side_effect=representation), \
             patch('pipeline.debate.check_novelty_many', side_effect=novel), \
             patch('pipeline.debate.check_novelty', return_value={'status':'new'}), \
             patch('pipeline.debate.review_background_many', side_effect=review), \
             patch('pipeline.debate.check_background_counterexamples', side_effect=lambda rows,*a:
                   seen.extend(('counterexample', r['id']) for r in rows)):
            result = debate([seed], [dict(id='chunk', text='A relates to C.')],
                dict(overview='A', topics=[]), concepts, relations, facts, models, trace)
        return result, facts, seen

    def test_group_repair_validates_every_replacement_and_bridge(self):
        result, facts, seen = self.run_group()
        self.assertEqual(len(facts.rows), 2)
        self.assertFalse(result['candidates'][0]['accepted'])
        self.assertEqual(result['candidates'][0]['repair_candidate_ids'], [r['id'] for r in facts.rows])
        for row in facts.rows:
            for gate in ('representation', 'novelty', 'review', 'counterexample'):
                self.assertIn((gate, row['id']), seen)

    def test_failed_bridge_never_admits_disconnected_companion(self):
        for kwargs in (dict(reject_bridge=True), dict(invalid_bridge=True)):
            with self.subTest(**kwargs):
                result, facts, _ = self.run_group(**kwargs)
                self.assertEqual(facts.rows, [])
                self.assertFalse(any(r['accepted'] for r in result['candidates']))

    def test_malformed_plan_member_does_not_discard_valid_companion_or_prevent_repair(self):
        result, facts, seen = self.run_group(accepted_member=True, malformed_member=True)
        invalid = result['candidates'][1]
        self.assertEqual(invalid['rejection_stage'], 'planning')
        self.assertNotIn(('representation', invalid['id']), seen)
        self.assertFalse(invalid['accepted'])
        self.assertEqual(result['candidates'][0]['review_status'], 'superseded')
        self.assertEqual(len(facts.rows), 2)

    def test_missing_planned_bridge_reaches_whole_group_repair(self):
        result, facts, seen = self.run_group(disconnected_plan=True)
        self.assertEqual(result['candidates'][0]['rejection_stage'], 'connectivity')
        self.assertFalse(result['candidates'][0]['accepted'])
        self.assertEqual({r['intended_fact'] for r in facts.rows}, {'A has B.', 'B has C.'})
        self.assertTrue(all(r['gates']['connected_to_seed'] for r in facts.rows))

    def test_repair_identity_checks_exclude_invalid_members_and_their_paths(self):
        for invalid_part, count in (('support', 1), ('bridge', 0)):
            with self.subTest(invalid_part=invalid_part):
                result, facts, seen = self.run_group(malformed_repair=invalid_part)
                invalid = next(r for r in result['candidates'] if r['repair_attempt']
                               and r['source_concept']=='unasserted participant')
                self.assertFalse(invalid['accepted'])
                self.assertEqual(invalid['rejection_stage'], 'planning')
                self.assertNotIn(('representation', invalid['id']), seen)
                self.assertEqual(len(facts.rows), count)
                self.assertTrue(all(r['gates']['connected_to_seed'] for r in facts.rows))

    def test_complete_group_repair_revalidates_and_supersedes_accepted_members(self):
        result, facts, seen = self.run_group(accepted_member=True)
        original = result['candidates'][0]
        self.assertEqual(original['review_status'], 'superseded')
        self.assertFalse(original['accepted'])
        self.assertEqual(len(facts.rows), 2)
        self.assertNotIn(original['id'], {r['id'] for r in facts.rows})
        for row in facts.rows:
            self.assertIn(original['id'], row['repair_of_ids'])
            for gate in ('representation', 'novelty', 'review', 'counterexample'):
                self.assertIn((gate, row['id']), seen)

    def test_incomplete_replacement_retains_previous_accepted_group(self):
        result, facts, seen = self.run_group(accepted_member=True, reject_support=True)
        original = result['candidates'][0]
        self.assertTrue(original['accepted'])
        self.assertEqual([r['id'] for r in facts.rows], [original['id']])
        self.assertFalse(any(r['accepted'] for r in result['candidates'] if r['repair_attempt']))

    def test_failed_optional_extension_keeps_valid_connected_repair_without_supersession(self):
        result, facts, seen = self.run_group(reject_support=True)
        self.assertEqual(len(facts.rows), 1)
        accepted = facts.rows[0]
        self.assertEqual(accepted['intended_fact'], 'A has B.')
        self.assertTrue(accepted['repair_attempt'])
        self.assertTrue(accepted['gates']['connected_to_seed'])
        for gate in ('representation', 'novelty', 'review', 'counterexample'):
            self.assertIn((gate, accepted['id']), seen)
        self.assertFalse(any(r['accepted'] for r in result['candidates'] if r['intended_fact']=='B has C.'))

    def test_known_bridge_is_reused_without_admitting_a_duplicate(self):
        result, facts, seen = self.run_group(known_bridge=True)
        self.assertEqual(len(facts.rows), 2)
        self.assertEqual(facts.rows[0]['id'], 'known')
        self.assertEqual(facts.rows[1]['intended_fact'], 'B has C.')
        duplicate = next(r for r in result['candidates'] if r['intended_fact']=='A has B.')
        self.assertFalse(duplicate['accepted'])
        self.assertEqual(duplicate['rejection_stage'], 'novelty')

    def test_same_predicate_text_is_verified_again_for_each_occurrence(self):
        trace, calls = Trace(), []
        def ask(role, instruction, payload, schema, entity_id, **kwargs):
            calls.append((role, payload))
            if entity_id == 'second': raise ModelResponseError('Incompatible context')
            return schema.model_validate(dict(exact_meaning=True, same_direction=True,
                compatible_types=True, reason='Equivalent in this occurrence.'))
        registry = RelationRegistry(SimpleNamespace(ask=ask), trace)
        before = copy.deepcopy(registry.entries['has_part'])
        registry.resolve_background('has_part', before['definition'], 'a', 'b', {'conditions':'under C'}, 'first')
        with self.assertRaises(ModelResponseError):
            registry.resolve_background('has_part', before['definition'], 'a', 'b', {'conditions':'under D'}, 'second')
        self.assertEqual(len(calls), 2)
        self.assertEqual(registry.entries['has_part'], before)
        self.assertEqual(len(registry.decisions), 1)

    def test_group_repair_cannot_invent_a_different_question(self):
        row = dict(id='failed', gap_ids=['gap'], gaps=[dict(id='gap', source_chunk_ids=['chunk'])],
                   decision_reason='Rejected.', source='b', target='c')
        def ask(role, instruction, payload, schema, entity_id, validator, **kwargs):
            result = schema.model_validate(dict(reason='Repair', corrected_facts=[dict(fact('A has B.'), gap_ids=['other'])]))
            validator(result)
        with self.assertRaises(ValueError):
            repair_candidates([row], dict(id='seed', concept='a'), {}, [dict(id='chunk',text='A')], [], [],
                SimpleNamespace(ask=ask), Trace(), ExplanationRepair, 'Repair')

    def test_all_member_feedback_evidence_and_qualifiers_survive_budget_reduction(self):
        gap = dict(id='gap', source_chunk_ids=['chunk'])
        first = dict(id='first', gap_ids=['gap'], gaps=[gap], decision_reason='Rejected.',
                     source='b', target='c', argument_qualifiers=['with D'])
        second = dict(first, id='second', decision_reason='Compare remote.',
                      novelty=dict(evidence_ids=['remote'], checked_references=['optional scan']),
                      counterexample_check=dict(counterexample='A distinct case.', sound_as_stated=False))
        group = dict(first, id='group', explanation_members=[first, second])
        plan = RepairContext(group, dict(id='seed', concept='a'), {},
            [dict(id='chunk', text='A'), dict(id='remote', text='Complete remote evidence.')], [], [first, second])
        for _, payload in plan.variants:
            essential = payload['essential']
            self.assertEqual({r['id'] for r in essential['source_evidence']}, {'chunk', 'remote'})
            self.assertEqual(essential['explanation_members'][1]['argument_qualifiers'], ['with D'])
            review = essential['reviewer_feedback']['explanation_members']['second']
            self.assertIn('counterexample_check', review)
            self.assertNotIn('checked_references', review['novelty'])


if __name__ == '__main__':
    unittest.main()
