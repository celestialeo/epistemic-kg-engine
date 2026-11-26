"""Offline regressions for relative 'that', reference resolution and source scope."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from pipeline.extraction import (Endpoint, Extraction, grounded_records,
                                 reference_name, resolve_endpoint)
from tests.test_explanation_groups import Trace


PASSAGE = ('For example, fine-tuning a foundation LLM that has ten billion parameters '
           'produces a fine-tuned LLM that also has ten billion parameters.')
NEXT_SENTENCE = 'Fine-tuned LLMs usually have a very large number of parameters.'


def endpoint(name, **extra):
    return Endpoint(name=name, definition='The concept described in the source.',
                    kind='entity', **extra)


class ReferenceClauseTests(unittest.TestCase):
    def test_clear_descriptive_clauses_across_subjects(self):
        for name in ('a process that produces heat', 'a cell that contains fluid',
                     'a treaty that establishes borders', 'a device that has a switch',
                     'a material that can absorb water', 'a process that does not release heat',
                     'a process that also produces heat', 'a record that was preserved intact'):
            with self.subTest(name=name):
                self.assertFalse(reference_name(name))

    def test_demonstratives_and_ambiguous_forms_still_need_resolution(self):
        for name in ('that', 'that process', 'that process produces heat',
                     'the outcome of that process', 'the results from that experiment',
                     'an outcome like that produces concern', 'a process and that system',
                     'a process that', 'a process that has', 'a process that altered outcomes',
                     'a process that some people describe', 'a process that unknown properties',
                     'a process, that produces heat'):
            with self.subTest(name=name):
                self.assertTrue(reference_name(name))

    def test_descriptive_clause_does_not_hide_other_references(self):
        for name in ('that process that produces heat', 'the outcome of that process that has a name',
                     'a process that changes its surroundings', 'a process that produces that heat',
                     'a process that changes their properties', 'a process that affects those cells',
                     'a process that changes itself'):
            with self.subTest(name=name):
                self.assertTrue(reference_name(name))

    def test_failing_passage_names_no_longer_trigger_spurious_resolution(self):
        # Recorded extractor response from the failed run, not a new model call.
        fixture = Path(__file__).parent / 'fixtures' / 'relative_clause_extraction.json'
        extraction = Extraction.model_validate(json.loads(fixture.read_text(encoding='utf-8')))
        unit = dict(id='sentence', start=0, end=len(PASSAGE), text=PASSAGE)
        model = SimpleNamespace(ask=Mock(side_effect=AssertionError('Unexpected model call')))
        good, failed = grounded_records(extraction, unit, unit, model,
                                        SimpleNamespace(entries={}), Trace())
        self.assertEqual(failed, [])
        self.assertEqual(len(good['claims']), 1)
        self.assertEqual(len(good['relations']), 1)
        for collection in good.values():
            for _, _, row in collection:
                self.assertEqual(PASSAGE[row['evidence_start']:row['evidence_end']], row['evidence'])
        mentions = [*extraction.concepts, extraction.relations[0].source, extraction.relations[0].target]
        for mention in mentions:
            with self.subTest(name=mention.name):
                self.assertIn(mention.name, PASSAGE)
                result = resolve_endpoint(mention, {}, 'source', unit, unit,
                    SimpleNamespace(entries={}), model, Trace(), 'record', {})
                self.assertEqual(result.name, mention.name)
                self.assertEqual(result.definition, mention.definition)
                self.assertEqual(result.kind, mention.kind)
        model.ask.assert_not_called()

    def test_explicit_hint_still_resolves_and_descriptive_answer_passes_validator(self):
        name = 'fine-tuned LLM that also has ten billion parameters'
        unit = dict(id='sentence', start=0, end=len(PASSAGE), text=PASSAGE)
        def ask(role, instruction, payload, schema, identifier, validator=None):
            self.assertEqual(role, 'concept_reference_resolver')
            result = schema(concept=endpoint(name).model_dump(exclude={'reference_phrase'}),
                            reason='The full description identifies the referent.')
            validator(result)
            return result
        model = SimpleNamespace(ask=Mock(side_effect=ask))
        result = resolve_endpoint(endpoint(name, reference_phrase=name), {}, 'target', unit, unit,
            SimpleNamespace(entries={}), model, Trace(), 'record', {})
        self.assertEqual(result.name, name)
        model.ask.assert_called_once()

    def test_ambiguous_reference_reaches_resolver_and_stays_unresolved(self):
        for name in ('that process', 'the outcome of that process'):
            with self.subTest(name=name):
                text = name + ' matters.'
                unit = dict(id='sentence', start=0, end=len(text), text=text)
                def ask(role, instruction, payload, schema, identifier, validator=None):
                    self.assertEqual(role, 'concept_reference_resolver')
                    return schema(concept=None, reason='No antecedent is supplied.')
                model = SimpleNamespace(ask=Mock(side_effect=ask))
                self.assertIsNone(resolve_endpoint(endpoint(name), {}, 'source', unit, unit,
                    SimpleNamespace(entries={}), model, Trace(), 'record', {}))
                model.ask.assert_called_once()

    def test_resolver_cannot_return_a_still_unresolved_name(self):
        name = 'the outcome of that process'
        text = name + ' matters.'
        unit = dict(id='sentence', start=0, end=len(text), text=text)
        def ask(role, instruction, payload, schema, identifier, validator=None):
            result = schema(concept=endpoint(name).model_dump(exclude={'reference_phrase'}),
                            reason='Unresolved fixture.')
            validator(result)
            return result
        with self.assertRaisesRegex(ValueError, 'remaining pronouns'):
            resolve_endpoint(endpoint(name), {}, 'source', unit, unit, SimpleNamespace(entries={}),
                             SimpleNamespace(ask=ask), Trace(), 'record', {})

    def test_previous_sentence_and_modified_quotes_remain_rejected(self):
        text = PASSAGE + '\n\n' + NEXT_SENTENCE
        unit = dict(id='sentence', start=len(PASSAGE) + 2, end=len(text), text=NEXT_SENTENCE)
        for quote in (PASSAGE, NEXT_SENTENCE.replace('usually', 'always')):
            with self.subTest(quote=quote):
                result = Extraction(unit_kind='core_statement', concepts=[], relations=[],
                    claims=[dict(text=NEXT_SENTENCE, evidence=NEXT_SENTENCE),
                            dict(text=quote, evidence=quote)], confidence=1, reason='Fixture.')
                def ask(role, instruction, payload, schema, identifier, validator=None):
                    self.assertEqual(role, 'extractor_quote_repair')
                    return schema(records=[dict(collection='claims', index=1, record=None,
                                                reason='Unsupported in the current sentence.')])
                good, failed = grounded_records(result, unit, dict(start=0, text=text),
                    SimpleNamespace(ask=ask), SimpleNamespace(entries={}), Trace())
                self.assertEqual(len(good['claims']), 1)
                self.assertEqual(good['claims'][0][2]['evidence'], NEXT_SENTENCE)
                self.assertEqual(good['claims'][0][2]['evidence_start'], unit['start'])
                self.assertEqual(len(failed), 1)


if __name__ == '__main__':
    unittest.main()
