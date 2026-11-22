"""Normal runs publish admission decisions without the optional graph refiner."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.cli import main
from pipeline.explorer import load_snapshot
from pipeline.registry import ConceptRegistry, RelationRegistry, FactIndex
from pipeline.run_results import summarize


class NoInference:
    def __init__(self, *args, **kwargs):
        self.details = {}
        self.calls = self.retries = self.cache_hits = 0

    def preflight(self):
        pass

    def ask(self, *args, **kwargs):
        raise AssertionError('Unexpected additional model review')


class DebateGraphPublicationTests(unittest.TestCase):
    def test_full_and_background_paths_keep_only_admitted_facts_without_refinement(self):
        # Toy input tests orchestration, not model accuracy or a new live topic.
        text = 'A pump moves water.'
        extraction = dict(chunk_id='chunk_001', concepts=['pump', 'water'], claims=[],
                          confidence=1, unit_kind='fact', status='completed', relations=[dict(
            id='document_fact', source='pump', target='water', relation='moves',
            relation_definition='SOURCE moves TARGET.', accepted=True, evidence=text,
            evidence_start=0, evidence_end=len(text), verification_basis='source_evidence')])
        candidates = [dict(id='accepted', source='pump', target='pressure', relation='produces',
                          relation_definition='SOURCE produces TARGET.', chunk_id='chunk_001',
                          accepted=True, score=1, decision_reason='Admission fixture', review_status='accepted'),
                      dict(id='rejected', source='pump', target='heat', relation='produces',
                          accepted=False, review_status='rejected')]
        result = dict(candidates=candidates)
        outline = dict(topics=['liquid transfer'])
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            source = root/'unseen_topic.txt'
            source.write_text(text, encoding='utf-8')
            stack.enter_context(patch('pipeline.models.Models', NoInference))
            refiner = stack.enter_context(patch('pipeline.graph_quality.refine_graph',
                                                side_effect=AssertionError('Extra review must not run')))
            stack.enter_context(patch('pipeline.extraction.extract', return_value=[copy.deepcopy(extraction)]))
            stack.enter_context(patch('pipeline.seeds.build_outline', return_value=outline))
            stack.enter_context(patch.object(ConceptRegistry, 'reconcile'))
            document_review = stack.enter_context(patch('pipeline.debate.review_extractions', return_value=[]))
            # This test isolates publication; source-audit semantics have their
            # own tests and must not invoke inference through NoInference.
            stack.enter_context(patch('pipeline.qualifiers.complete_arguments'))
            stack.enter_context(patch('pipeline.source_recovery.recover_source', side_effect=lambda *args: args[-1]))
            stack.enter_context(patch('pipeline.gaps.collect_seeds', return_value=[]))
            debate = stack.enter_context(patch('pipeline.debate.debate', return_value=result))
            evaluation = stack.enter_context(patch('pipeline.evaluation.evaluate', return_value=dict(
                status='completed', final_score=None, results=[dict(reconstruction=text)])))
            stack.enter_context(patch('pipeline.report.statistics_for', return_value={}))
            stack.enter_context(patch('pipeline.report.render_report', return_value=('<html></html>', 'Report')))
            code = main(['--input', str(source), '--output-root', str(root/'full'), '--no-open', '--no-explorer'])
            self.assertEqual(code, 0)
            document_review.assert_called_once()
            debate.assert_called_once()
            evaluation.assert_called_once()
            run = next((root/'full'/'custom').iterdir())
            self.assert_published(run)

            from pipeline.replay_background import main as replay
            def load(source, models, trace):
                concepts, relations = ConceptRegistry(models, trace), RelationRegistry(models, trace)
                return ([dict(id='chunk_001', text=text)], [copy.deepcopy(extraction)], outline,
                        concepts, relations, FactIndex(relations))
            stack.enter_context(patch('pipeline.replay_background.Models', NoInference))
            stack.enter_context(patch('pipeline.replay_background.load_document', side_effect=load))
            stack.enter_context(patch('pipeline.replay_background.collect_seeds', return_value=[]))
            replay_debate = stack.enter_context(patch('pipeline.replay_background.debate', return_value=result))
            replay([str(run), '--output-root', str(root/'replays')])
            replay_debate.assert_called_once()
            replay_run = next((root/'replays').iterdir())
            self.assert_published(replay_run)
            self.assertTrue(json.loads((replay_run/'manifest.json').read_text())['source_unchanged'])
            refiner.assert_not_called()

    def assert_published(self, directory):
        snapshot = load_snapshot(directory)
        self.assertEqual(snapshot.manifest['status'], 'completed')
        self.assertFalse(snapshot.manifest['graph_quality_required'])
        self.assertEqual(snapshot.manifest['graph_quality_status'], 'not_run')
        self.assertEqual(snapshot.manifest['graph_acceptance_policy'], 'document_review_and_background_debate')
        self.assertNotIn('quality', snapshot.graph)
        self.assertEqual({e['candidate_id'] for e in snapshot.graph['edges']}, {'document_fact', 'accepted'})
        self.assertEqual(sum(e['origin']=='background' for e in snapshot.graph['edges']), 1)
        self.assertFalse((directory/'artifacts/graph_quality.json').exists())
        self.assertTrue((directory/'knowledge_graph.html').is_file())
        self.assertEqual(summarize(snapshot)['graph_quality_status'], 'not_run')


if __name__ == '__main__':
    unittest.main()
