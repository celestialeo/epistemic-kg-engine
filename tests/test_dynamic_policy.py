"""Input-sized work, explicit settings, preserved provenance, and review independence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.settings import SETTINGS, load_settings, budgeted_pages, automatic_chunk_words, render_asset
from pipeline.graph_quality import resolve_graph_context, reference_obligations
from pipeline.graph_view import concept_id
from pipeline.seeds import SegmentSummary
from pipeline.assessment import AssessmentCriterion


class DynamicPolicyTests(unittest.TestCase):
    def test_background_challenge_retains_entity_senses_and_qualifications(self):
        from pipeline.graph_quality import Fact, background_assertion
        fact = Fact(source=dict(label='cell', definition='A compartment in a battery.'),
                    relation='supplies', definition='SOURCE supplies TARGET.',
                    target=dict(label='current', definition='Flow of electric charge.'),
                    conditions='when connected', modality='can', evidence=None)
        assertion = background_assertion(fact)
        self.assertEqual(assertion['source_definition'], fact.source.definition)
        self.assertEqual(assertion['target_definition'], fact.target.definition)
        self.assertEqual(assertion['conditions'], 'when connected')
        self.assertEqual(assertion['modality'], 'can')

    def test_partial_configuration_preserves_defaults_and_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            path.write_text(json.dumps({'ui': {'input_chars': 77}}))
            self.assertEqual(load_settings(path)['ui']['input_chars'], 77)
            path.write_text(json.dumps({'workload': {'invented_quota': 2}}))
            with self.assertRaisesRegex(ValueError, 'Unknown setting'):
                load_settings(path)

    def test_invalid_budgets_and_weights_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            for invalid in ({'model': {'max_output_tokens': SETTINGS['model']['context_tokens']}},
                            {'assessment_weights': {'related': 1.2}},
                            {'workload': {'batch_size': 0}}, {'review': {'repair_attempts': 0}}):
                path.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    load_settings(path)

    def test_batch_pages_scale_with_item_size_and_never_discard_tail_items(self):
        class Model:
            options = dict(num_ctx=4096, num_predict=1024)
            batch_size = None
        small = [dict(id=str(i), text='x') for i in range(37)]
        large = [dict(id=str(i), text='x'*900) for i in range(37)]
        small_pages = list(budgeted_pages(small, Model()))
        large_pages = list(budgeted_pages(large, Model()))
        self.assertGreater(len(large_pages), len(small_pages))
        self.assertEqual([x for page in large_pages for x in page], large)
        self.assertEqual([x for page in small_pages for x in page], small)

    def test_explicit_batch_override_is_a_page_limit_not_a_content_quota(self):
        rows = [dict(id=str(i)) for i in range(9)]
        pages = list(budgeted_pages(rows, size=2))
        self.assertTrue(all(len(page) <= 2 for page in pages))
        self.assertEqual([row for page in pages for row in page], rows)

    def test_chunk_sizing_uses_source_density_and_operating_budget(self):
        short = 'A short passage.'
        self.assertEqual(automatic_chunk_words(short), len(short.split()))
        source = 'word '*20000
        small = automatic_chunk_words(source, 4096, 1024)
        large = automatic_chunk_words(source, 8192, 1024)
        self.assertGreater(large, small)
        self.assertLess(large, len(source.split()))

    def test_topic_and_assessment_lists_have_no_arbitrary_count_ceiling(self):
        self.assertNotIn('maxItems', SegmentSummary.model_json_schema()['properties']['topics'])
        self.assertNotIn('maxItems', AssessmentCriterion.model_json_schema()['properties']['criteria'])

    def test_ui_and_api_use_the_same_override_and_weights_are_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'settings.json'
            path.write_text(json.dumps({'ui': {'input_chars': 77},
                'evaluation_weights': {'claim_fidelity_f1': 2, 'idea_order_agreement': 0,
                                       'rouge_l_f1': 0, 'length_similarity': 0}}))
            code = """import json
from pipeline.explorer import Query
from pipeline.settings import render_asset
from pipeline.evaluation import METRIC_WEIGHTS
print(json.dumps(dict(weights=METRIC_WEIGHTS, ui='maxlength=\"77\"' in render_asset('pipeline/professor.html'),
                     maximum=Query.model_json_schema()['properties']['text']['maxLength'])))
"""
            result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ, EKG_SETTINGS=str(path)),
                                    capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
            self.assertEqual(data['maximum'], 77)
            self.assertTrue(data['ui'])
            self.assertEqual(data['weights']['claim_fidelity_f1'], 1)

    def test_wrong_alternative_binding_cannot_replace_source_verified_original(self):
        nodes = [dict(id=concept_id(n), label=n, origin='document') for n in ['vessel','temperature','air']]
        roles = []
        def ask(role, instruction, payload, schema, identifier, validator=None, **kwargs):
            roles.append(role)
            if role == 'graph_entity_context_adjudicator':
                return schema(original_valid=True, alternative_valid=False, reason='The source names the vessel.')
            owner = None
            if payload['focus_entity'] == 'temperature':
                owner = 'air' if role.endswith('_check') else 'vessel'
            result = schema(owned_by=owner, performed_by=None, ambiguous=False,
                            reason='Source attribution for the focused property.')
            if validator:
                validator(result)
            return result
        text = 'The vessel lowers its temperature.'
        result = resolve_graph_context(dict(id='c1', text=text), ask, 1, nodes)
        binding = result['references'][0]
        self.assertEqual(binding['antecedent_node'], concept_id('vessel'))
        self.assertEqual(binding['owned_property_node'], concept_id('temperature'))
        self.assertEqual(binding['evidence'], text)
        self.assertIn('graph_entity_context_adjudicator', roles)
        edge = dict(source=concept_id('air'), target=concept_id('temperature'), participants=[])
        self.assertTrue(reference_obligations(edge, result['references'], {n['id']:n for n in nodes}))

    def test_unresolved_entity_roles_block_instead_of_using_an_unverified_binding(self):
        def ask(role, instruction, payload, schema, identifier, validator=None, **kwargs):
            if role == 'graph_entity_context_adjudicator':
                return schema(original_valid=False, alternative_valid=False, reason='Unresolved attribution')
            result = schema(owned_by='vessel' if role.endswith('_check') else None,
                            performed_by=None, ambiguous=False, reason='Unresolved')
            if validator:
                validator(result)
            return result
        nodes = [dict(id='property', label='temperature', origin='document'),
                 dict(id='owner', label='vessel', origin='background')]
        with self.assertRaisesRegex(ValueError, 'remain unresolved'):
            resolve_graph_context(dict(id='c1',text='A temperature is measured.'), ask, 1, nodes)

    def test_quiz_round_size_comes_from_eligible_facts_and_survives_restore(self):
        from pipeline.quiz import QuizSession
        from pipeline.quiz_examiner import QuizExaminer
        from tests.test_graph_quality import sample
        with patch.dict(SETTINGS['ui'], quiz_round_questions=None), patch.object(QuizExaminer, 'question',
                return_value=dict(text='Explain the relationship.', expected_answer='A source-grounded explanation.',
                                  assessment_spec=[])):
            session = QuizSession(sample(), 'page', SimpleNamespace())
            self.assertEqual(session.LIMIT, len(session._eligible()))
            checkpoint = session.checkpoint()
        with patch.dict(SETTINGS['ui'], quiz_round_questions=17):
            restored = QuizSession.restore(sample(), SimpleNamespace(), checkpoint)
            self.assertEqual(restored.LIMIT, checkpoint['LIMIT'])

    def test_scoring_changes_do_not_recalculate_historical_answer_weights(self):
        from pipeline.student_store import StudentStore, MARKS, now
        with tempfile.TemporaryDirectory() as directory:
            store = StudentStore(Path(directory)/'students.sqlite3')
            student = store.add_student('Example student')
            store.register_run('run', 'topic', 'Topic', SimpleNamespace(directory=Path(directory),
                graph={}, manifest={}, quiz_aliases={}))
            session = dict(id='session', student_id=student['id'], run_id='run', created_at=now(), checkpoint={})
            answer = dict(id='answer', question={}, text='Partial answer', helped=False,
                          result={}, marks={'fact':'related'}, feedback='Partial')
            with patch.dict(MARKS, related=.25):
                store.commit_action(session, answer, 'request', 'signature', {})
            with patch.dict(MARKS, related=.9):
                saved = store.answers()[0]
                self.assertEqual(saved['original_score'], 25)
                self.assertEqual(saved['score'], 25)


if __name__ == '__main__':
    unittest.main()
