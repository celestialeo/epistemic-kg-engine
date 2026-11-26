"""Focused, offline checks for bounded search, antecedent context, and repair progress."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.debate import debate, explanation_progress, repair_made_progress
from pipeline.extraction import Endpoint, evidence_context, resolve_endpoint, extract
from pipeline.models import request_budget, ModelResponseError
from pipeline.registry import ConceptRegistry, RelationRegistry, FactIndex
from pipeline.settings import SETTINGS, validate
from tests.test_explanation_groups import Trace, node


def ordered_shortlist(query, entries, limit, **kwargs):
    rows = list(entries)
    return rows[:limit] if limit else rows


class AdaptiveIdentityTests(unittest.TestCase):
    def concept_search(self, *, certain=False, reject=False, target='item19'):
        calls, checks = [], []
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            if role == 'concept_alias_resolver':
                names = [r['name'] for r in payload['existing_concepts']]
                calls.append(names)
                selected = names[0] if reject else target if target in names else None
                value = dict(canonical_name=selected, reason='Identity decision.', search_uncertain=not certain)
            else:
                self.assertEqual(role, 'concept_alias_verifier')
                checks.append(payload['existing_concept']['name'])
                value = dict(same_concept=not reject, same_scope=not reject, reason='Independent scope check.')
            result = schema.model_validate(value)
            if validator: validator(result)
            return result
        models = SimpleNamespace(ask=ask, options={'num_ctx': 8192, 'num_predict': 4096})
        available = {f'item{i:02d}': node(f'item{i:02d}') for i in range(40)}
        registry = ConceptRegistry(models, Trace())
        with patch('pipeline.retrieval.shortlist', side_effect=ordered_shortlist):
            result = registry._semantic_match(node('new name'), available, 'Source context.', 'occurrence')
        self.assertEqual(models.options, {'num_ctx': 8192, 'num_predict': 4096})
        return result, calls, checks

    def test_uncertain_search_expands_beyond_initial_sixteen_and_verifies_match(self):
        result, calls, checks = self.concept_search()
        self.assertEqual(result, 'item19')
        self.assertEqual([len(c) for c in calls], [16, 16])
        self.assertFalse(set(calls[0]) & set(calls[1]))
        self.assertEqual(checks, ['item19'])

    def test_clear_match_or_conclusive_distinction_does_not_expand(self):
        for args, expected in (({'target': 'item03'}, 'item03'), ({'certain': True}, None)):
            with self.subTest(args=args):
                result, calls, _ = self.concept_search(**args)
                self.assertEqual(result, expected)
                self.assertEqual(len(calls), 1)

    def test_failed_verification_expands_but_never_merges_or_retries_old_candidates(self):
        result, calls, checks = self.concept_search(reject=True, certain=True)
        self.assertIsNone(result)
        self.assertEqual([len(c) for c in calls], [16, 16, 8])
        self.assertEqual(len({name for page in calls for name in page}), 40)
        self.assertEqual(checks, ['item00', 'item16', 'item32'])

    def test_relation_search_expands_without_changing_contracts(self):
        calls = []
        def ask(role, instruction, payload, schema, entity_id, **kwargs):
            calls.append(role)
            if role == 'relation_resolver':
                names = [r['key'] for r in payload['available']]
                key = 'predicate19' if 'predicate19' in names else None
                value = dict(key=key, exact_meaning=bool(key), same_direction=bool(key),
                             search_uncertain=key is None, reason='Search result.')
            else:
                self.assertEqual(role, 'relation_match_verifier')
                value = dict(exact_meaning=True, same_direction=True, compatible_types=True, reason='Verified.')
            return schema.model_validate(value)
        registry = RelationRegistry(SimpleNamespace(ask=ask), Trace())
        registry.entries = {f'predicate{i}': dict(key=f'predicate{i}', definition='SOURCE relates to TARGET.',
                            inverse=None, symmetric=False) for i in range(20)}
        before = copy.deepcopy(registry.entries)
        with patch('pipeline.retrieval.shortlist', side_effect=ordered_shortlist):
            result = registry.resolve('different_label', 'SOURCE relates to TARGET.', 'a', 'b', {}, 'edge')
        self.assertEqual(result, 'predicate19')
        self.assertEqual(calls, ['relation_resolver', 'relation_resolver', 'relation_match_verifier'])
        self.assertEqual(registry.entries, before)


class AdaptiveReferenceTests(unittest.TestCase):
    def resolve(self, earlier, *, resolved_immediately=False, always_ambiguous=False):
        current = 'Its seal remains intact.'
        text = earlier + ' ' + current + ' A future owner must not be used.'
        start = len(earlier) + 1
        unit = dict(id='unit', start=start, end=start + len(current), text=current)
        paragraph = dict(id='paragraph', start=0, end=len(text), text=text)
        context = evidence_context(unit, paragraph)
        context['reference_paragraphs'] = [paragraph]
        trace, calls = Trace(), []
        options = {'num_ctx': 8192, 'num_predict': 4096}
        def ask(role, instruction, payload, schema, identifier, validator=None):
            self.assertEqual(role, 'concept_reference_resolver')
            self.assertTrue(request_budget(instruction, payload, schema, options)['fits'])
            calls.append(copy.deepcopy(payload))
            clear = not always_ambiguous and (resolved_immediately or 'Beacon archive' in payload['REFERENCE_CONTEXT'])
            result = schema.model_validate(dict(concept=node('seal of Beacon archive') if clear else None,
                                                reason='Antecedent evidence checked.'))
            if validator: validator(result)
            return result
        model = SimpleNamespace(ask=ask, options=options.copy())
        result = resolve_endpoint(Endpoint(**node('its seal')), {}, 'source', unit, context,
                                  SimpleNamespace(entries={}), model, trace, 'reference', {})
        self.assertEqual(model.options, options)
        return result, calls, trace, context, text

    def test_ambiguous_reference_adds_relevant_older_context_with_provenance(self):
        earlier = 'The Beacon archive has a seal. Rain fell. A clock rang. Visitors arrived. Lamps were lit.'
        result, calls, trace, context, text = self.resolve(earlier)
        self.assertEqual(result.name, 'seal of Beacon archive')
        self.assertEqual(calls[0]['REFERENCE_CONTEXT'], 'A clock rang. Visitors arrived. Lamps were lit.')
        self.assertNotIn('Beacon archive', calls[0]['REFERENCE_CONTEXT'])
        self.assertIn('Beacon archive', calls[-1]['REFERENCE_CONTEXT'])
        self.assertNotIn('future owner', calls[-1]['REFERENCE_CONTEXT'])
        self.assertTrue(any(event == 'extraction.reference_context_expanded' for event, _ in trace.events))
        for span in context['resolved_reference_spans']:
            self.assertEqual(text[span['start']:span['end']], span['text'])

    def test_resolved_reference_uses_only_initial_window(self):
        _, calls, trace, _, _ = self.resolve('The Beacon archive has a seal. Rain fell. A clock rang. Visitors arrived. Lamps were lit.',
                                            resolved_immediately=True)
        self.assertEqual(len(calls), 1)
        self.assertFalse(any(event == 'extraction.reference_context_expanded' for event, _ in trace.events))

    def test_oversized_context_is_not_truncated_or_sent_over_budget(self):
        result, calls, _, _, _ = self.resolve('An archive ' + 'described ' * 5000 + 'a seal. A clock rang. Visitors arrived. Lamps were lit.',
                                             always_ambiguous=True)
        self.assertIsNone(result)
        self.assertEqual(len(calls), 1)

    def test_ambiguity_stays_unresolved_after_exhausting_context(self):
        result, calls, _, _, _ = self.resolve('An archive has a seal. Another archive has a seal. A clock rang. Visitors arrived. Lamps were lit.',
                                             always_ambiguous=True)
        self.assertIsNone(result)
        self.assertGreater(len(calls), 1)

    def test_reference_expansion_can_reach_an_earlier_paragraph(self):
        first = dict(id='first', start=0, text='The Beacon archive has a seal.')
        middle = 'A clock rang. Visitors arrived. Lamps were lit.'
        current = 'Its seal remains intact.'
        second = dict(id='second', start=len(first['text']) + 2, text=middle + ' ' + current)
        unit = dict(id='unit', start=second['start'] + len(middle) + 1,
                    end=second['start'] + len(second['text']), text=current)
        context = evidence_context(unit, second)
        context['reference_paragraphs'] = [first, second]
        calls = []
        def ask(role, instruction, payload, schema, identifier, validator=None):
            calls.append(payload)
            return schema.model_validate(dict(concept=node('seal of Beacon archive')
                if 'Beacon archive' in payload['REFERENCE_CONTEXT'] else None, reason='Checked.'))
        result = resolve_endpoint(Endpoint(**node('its seal')), {}, 'source', unit, context,
            SimpleNamespace(entries={}), SimpleNamespace(ask=ask), Trace(), 'reference', {})
        self.assertEqual(result.name, 'seal of Beacon archive')
        self.assertEqual(len(calls), 2)
        self.assertEqual(context['resolved_reference_spans'][0]['start'], 0)

    def test_expanded_antecedent_evidence_reaches_source_review_without_changing_quote(self):
        first = dict(id='first', start=0, text='The Beacon archive has a seal.')
        middle, current = 'A clock rang. Visitors arrived. Lamps were lit.', 'Its seal has a stamp.'
        second = dict(id='second', start=len(first['text']) + 2, text=middle + ' ' + current)
        chunk = dict(id='chunk', paragraph_id='second', start=second['start'] + len(middle) + 1,
                     end=second['start'] + len(second['text']), text=current)
        def ask(role, instruction, payload, schema, identifier, validator=None, **kwargs):
            if role == 'extractor':
                value = dict(unit_kind='core_statement', concepts=[], claims=[], confidence=1, reason='Source.',
                    relations=[dict(source=node('its seal'), target=node('stamp'), relation='has_part',
                                    relation_definition='SOURCE has TARGET as a part.', evidence=current)])
            elif role == 'concept_reference_resolver':
                value = dict(concept=node('seal of Beacon archive')
                    if 'Beacon archive' in payload['REFERENCE_CONTEXT'] else None, reason='Antecedent checked.')
            else:
                self.assertEqual(role, 'relation_match_verifier')
                value = dict(exact_meaning=True, same_direction=True, compatible_types=True, reason='Verified.')
            result = schema.model_validate(value)
            if validator: validator(result)
            return result
        model, trace = SimpleNamespace(ask=ask), Trace()
        concepts = SimpleNamespace(entries={}, resolve=lambda endpoint, *args: endpoint.name.casefold())
        rows = extract([chunk], [first, second], model, trace, concepts, RelationRegistry(model, trace))
        row = rows[0]['relation_proposals'][0]
        self.assertEqual(row['evidence'], current)
        self.assertEqual(row['evidence_start'], chunk['start'])
        self.assertIn(first['text'], row['evidence_context'])
        self.assertEqual(row['reference_context_spans'][0], dict(text=first['text'], start=0, end=len(first['text'])))


def planned(source, target):
    sentence = f'{source.upper()} has {target.upper()}.'
    return dict(intended_fact=sentence, source_concept=source, target_concept=target,
                confidence=1, reason=sentence, added_knowledge=sentence, gap_ids=['gap'])


class ProgressiveRepairTests(unittest.TestCase):
    def run_repairs(self, maximum=3, mode='progress', generation_error=False):
        trace, checked, repair_calls = Trace(), [], []
        original = [planned('a', 'b'), planned('b', 'c'), planned('c', 'd')]
        if mode == 'repeated':
            original = [planned('a', 'b'), planned('b', 'c'), planned('a', 'd')]
        seed = dict(id='seed', concept='a', definition='A', kind='entity', chunk_id='chunk',
                    paragraph_id='paragraph', gaps=[dict(id='gap', question='How are these related?', source_chunk_ids=['chunk'])])
        def ask(role, instruction, payload, schema, entity_id, validator=None, **kwargs):
            if role == 'proposer':
                value = dict(gap_analysis='Missing connections.', facts=original, reason='A connected explanation.')
            elif role == 'background_proposal_repair':
                repair_calls.append(copy.deepcopy(payload))
                if generation_error and len(repair_calls) == 2:
                    raise ModelResponseError('No validated replacement response')
                values = original + ([planned('a', 'e')] if mode == 'repeated' and len(repair_calls) > 1 else [])
                value = dict(corrected_facts=values, reason='Repair failed links without weakening checks.')
            elif role == 'background_link_constructor':
                fixed = payload['fixed_topology']
                value = dict(nodes={key: dict(definition=name, kind='entity') for key, name in fixed['nodes'].items()},
                    links={row['id']: dict(relation='has_part', relation_definition='SOURCE has TARGET as a part.',
                        conditions=None, modality=None, argument_qualifiers=[]) for row in payload['facts']})
            elif role == 'relation_match_verifier':
                value = dict(exact_meaning=True, same_direction=True, compatible_types=True, reason='Verified.')
            else:
                self.fail(role)
            result = schema.model_validate(value)
            if validator: validator(result)
            return result
        models = SimpleNamespace(ask=ask)
        relations = RelationRegistry(models, trace)
        facts = FactIndex(relations)
        concepts = SimpleNamespace(entries={x: node(x) for x in 'abcde'},
                                   resolve_background=lambda mention, context, identifier: mention['name'])
        def representation(row, *args):
            checked.append(('representation', row['id']))
            attempt = row['repair_attempt']
            if mode == 'repeated':
                valid = row['source_concept'] == 'a' and (attempt > 0 or row['target_concept'] == 'b')
            else:
                index = [('a', 'b'), ('b', 'c'), ('c', 'd')].index((row['source_concept'], row['target_concept']))
                valid = attempt > index and mode != 'no_progress' and not (mode == 'regress' and attempt > 1)
            if not valid: row['representation_check'] = dict(reason='Required representation check failed.')
            return valid
        def novelty(rows, *args):
            checked.extend(('novelty', row['id']) for row in rows)
            return {row['id']: dict(status='new') for row in rows}
        def review(rows, *args):
            for row in rows:
                checked.append(('review', row['id']))
                row.update(accepted=True, review_status='completed', decision_reason='Validated.')
        with patch.dict(SETTINGS['review'], explanation_repair_max_attempts=maximum), \
             patch('pipeline.debate.correct_polarity', side_effect=lambda link, *args: link), \
             patch('pipeline.debate.check_representation', side_effect=representation), \
             patch('pipeline.debate.check_novelty_many', side_effect=novelty), \
             patch('pipeline.debate.check_novelty', return_value={'status': 'new'}), \
             patch('pipeline.debate.review_background_many', side_effect=review), \
             patch('pipeline.debate.check_background_counterexamples', side_effect=lambda rows, *args:
                   checked.extend(('counterexample', row['id']) for row in rows)):
            result = debate([seed], [dict(id='chunk', text='A has related parts.')],
                dict(overview='Parts', topics=[]), concepts, relations, facts, models, trace)
        return result, facts, trace, checked, repair_calls

    def test_three_progressive_rounds_revalidate_every_link_and_publish_only_final_group(self):
        result, facts, trace, checked, calls = self.run_repairs()
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(facts.rows), 3)
        self.assertTrue(all(row['repair_attempt'] == 3 for row in facts.rows))
        self.assertEqual({r['id'] for r in facts.rows}, {r['id'] for r in result['candidates'] if r['accepted']})
        for row in facts.rows:
            self.assertTrue(row['gates']['connected_to_seed'])
            for gate in ('representation', 'novelty', 'review', 'counterexample'):
                self.assertIn((gate, row['id']), checked)
        self.assertEqual({r['id'] for r in calls[1]['essential']['explanation_members']},
                         {r['id'] for r in result['candidates'] if r['repair_attempt'] == 1})

    def test_no_progress_stops_after_first_attempt(self):
        _, facts, trace, _, calls = self.run_repairs(mode='no_progress')
        self.assertEqual(len(calls), 1)
        self.assertEqual(facts.rows, [])
        stops = [data['stop_reason'] for event, data in trace.events if event == 'debate.group_repair_progress']
        self.assertEqual(stops, ['repeated_failure'])

    def test_maximum_bounds_even_improving_repairs(self):
        result, facts, trace, _, calls = self.run_repairs(maximum=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(facts.rows), 2)
        self.assertTrue(all(r['gates']['connected_to_seed'] for r in facts.rows))
        self.assertFalse(any(r['accepted'] for r in result['candidates'] if r['target_concept'] == 'd'))
        self.assertEqual([data for event, data in trace.events if event == 'debate.group_repair_progress'][-1]['stop_reason'], 'max_attempts')

    def test_repeated_failures_stop_even_when_other_links_improve_and_protect_original(self):
        result, facts, trace, _, calls = self.run_repairs(mode='repeated')
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(facts.rows), 1)
        self.assertEqual(facts.rows[0]['repair_attempt'], 0)
        self.assertFalse(any(r['accepted'] for r in result['candidates'] if r['repair_attempt']))
        self.assertEqual([data for event, data in trace.events if event == 'debate.group_repair_progress'][-1]['stop_reason'], 'repeated_failure')

    def test_later_regression_or_generation_failure_retains_best_validated_subset(self):
        for args in ({'mode': 'regress'}, {'generation_error': True}):
            with self.subTest(args=args):
                result, facts, _, _, calls = self.run_repairs(**args)
                self.assertEqual(len(calls), 2)
                self.assertEqual(len(facts.rows), 1)
                self.assertEqual(facts.rows[0]['repair_attempt'], 1)
                self.assertEqual(sum(r['accepted'] for r in result['candidates']), 1)

    def test_duplicate_rows_and_cosmetic_edits_do_not_count_as_progress(self):
        row = dict(planned('a', 'b'), source='a', target='b', relation='has_part', accepted=True,
                   representation_valid=True, gates={'connected_to_seed': True})
        before = explanation_progress([row], ['gap'])
        after = explanation_progress([row, dict(row, id='different', reason='New prose')], ['gap'])
        self.assertFalse(repair_made_progress(before, after))

    def test_repair_maximum_is_a_validated_positive_integer(self):
        for bad in (0, -1, 1.5, True):
            settings = copy.deepcopy(SETTINGS)
            settings['review']['explanation_repair_max_attempts'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate(settings)


if __name__ == '__main__':
    unittest.main()
