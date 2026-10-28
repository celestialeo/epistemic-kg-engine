"""Regular chapter runs always reconstruct and evaluate, including partial failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.cli import main
from pipeline.models import ModelResponseError


class PipelineEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_case(self, failure=None):
        calls, settings = [], {}

        class FixtureModels:
            calls = retries = prompt_tokens = output_tokens = cache_hits = 0
            details = {}

            def __init__(self, trace, model, embedding_model, host, **kwargs):
                self.model, self.embedding_model, self.trace = model, embedding_model, trace
                settings.update(kwargs)

            def preflight(self):
                pass

            def ask(self, role, instruction, payload, schema, entity_id, validator=None):
                calls.append((role, entity_id, self.trace.stage))
                if (role, entity_id) == failure:
                    raise ModelResponseError("Fixture evaluation failure after recovery")
                if role == "extractor":
                    text = payload["CURRENT_SENTENCE"]
                    value = dict(unit_kind="core_statement", concepts=[], relations=[],
                                 claims=[dict(text=text, evidence=text)], confidence=.9, reason="Fixture")
                elif role == "segment_summarizer":
                    value = dict(summary="Water", topics=["water"])
                elif role == "chapter_summarizer":
                    value = dict(overview="Water", topics=["water"])
                elif role == "reconstructor":
                    if set(payload) != {"concepts", "relations"}:
                        raise AssertionError("Reconstruction must receive only structured graph facts")
                    value = dict(text="Water moves.", reason="Reconstructed from document relation")
                elif role == "evaluation_claims":
                    value = dict(claims=[dict(text=payload["text"], evidence=payload["text"])])
                elif role == "evaluation_alignment":
                    value = dict(matches=[dict(original_index=0, reconstructed_index=0, reason="Same assertion")])
                else:
                    raise AssertionError(role)
                answer = schema.model_validate(value)
                if validator:
                    validator(answer)
                return answer

        source = self.root / "chapter.txt"
        source.write_text("Water moves.", encoding="utf-8")
        destination = self.root / "runs"
        # Supply a final graph at this stage boundary; extraction and relation
        # review are exercised separately. Source prose must never reach the model.
        graph = dict(nodes=[dict(id="water", label="water", kind="concept"),
                            dict(id="movement", label="movement", kind="event")],
                     edges=[dict(source="water", target="movement", label="participates_in",
                                 origin="document", chunk_id="chunk_001")],
                     provenance=dict(text="PRIVATE source prose"))
        with patch("pipeline.cli.CHAPTERS", {"water-cycle-simplified": source}), \
             patch("pipeline.models.Models", FixtureModels), \
             patch("pipeline.graph_view.build_graph", return_value=graph):
            code = main(["--chapter", "water-cycle-simplified", "--output-root", str(destination), "--no-open", "--no-explorer"])
        directory = next((destination / "water-cycle-simplified").iterdir())
        return code, directory, calls, settings

    def test_default_chapter_command_runs_evaluation_and_reports_global_score(self):
        code, directory, calls, settings = self.run_case()
        self.assertEqual(code, 0)
        self.assertIn(("reconstructor", "chunk_001", "evaluation"), calls)
        self.assertIn(("evaluation_alignment", "evaluation:document:alignment", "evaluation"), calls)
        self.assertEqual(settings["document_context_tokens"], 16384)
        self.assertEqual(settings["document_output_tokens"], 8192)
        self.assertEqual((directory / "reconstruction.txt").read_text(), "Water moves.\n")
        evaluation = json.loads((directory / "artifacts/evaluation.json").read_text())
        self.assertEqual(evaluation["final_score"], 100)
        report = (directory / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="reconstruction.txt"', report)
        self.assertIn('href="artifacts/evaluation.json"', report)

    def test_failed_document_alignment_preserves_chunks_and_does_not_substitute_their_mean(self):
        code, directory, _, _ = self.run_case(("evaluation_alignment", "evaluation:document:alignment"))
        self.assertEqual(code, 2)
        evaluation = json.loads((directory / "artifacts/evaluation.json").read_text())
        self.assertEqual(evaluation["summary"]["final_score"]["mean"], 100)
        self.assertIsNone(evaluation["final_score"])
        self.assertEqual(evaluation["status"], "incomplete")
        self.assertEqual((directory / "reconstruction.txt").read_text(), "Water moves.\n")
        self.assertTrue((directory / "artifacts/graph.json").exists())
        self.assertIn("Evaluation incomplete", (directory / "index.html").read_text(encoding="utf-8"))
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "completed_with_issues")
        self.assertEqual(manifest["evaluation_status"], "incomplete")
        self.assertIsNone(manifest["reconstruction_score"])
        self.assertEqual(manifest["unresolved_items"][0]["step"], "evaluation")

    def test_failed_reconstruction_is_reported_and_not_given_a_score(self):
        code, directory, _, _ = self.run_case(("reconstructor", "chunk_001"))
        self.assertEqual(code, 2)
        evaluation = json.loads((directory / "artifacts/evaluation.json").read_text())
        self.assertEqual(evaluation["results"][0]["status"], "unresolved")
        self.assertIsNone(evaluation["results"][0]["final_score"])
        stats = json.loads((directory / "statistics.json").read_text())
        self.assertEqual(stats["evaluation_status"], "incomplete")
        self.assertIsNone(stats["reconstruction_score"])
        self.assertTrue((directory / "index.html").exists())


if __name__ == "__main__":
    unittest.main()
