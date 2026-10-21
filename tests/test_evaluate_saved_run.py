"""A saved-run evaluation adds results without rerunning or altering its graph."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.evaluate_saved_run import Models, evaluate_saved_run


class SavedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "artifacts").mkdir()
        values = {
            "manifest.json": dict(run_id="original", status="completed_with_issues", duration_seconds=120,
                                  config=dict(model="fixture"), artifacts={}),
            "statistics.json": dict(models=dict(calls=20), fidelity={}),
            "artifacts/chunks.json": [dict(id="chunk_001", order=0, text="Original.")],
            "artifacts/graph.json": dict(nodes=[], edges=[]),
            "artifacts/paragraphs.json": [],
            "artifacts/debate.json": dict(candidates=[]),
        }
        for name, value in values.items():
            (self.directory / name).write_text(json.dumps(value), encoding="utf-8")
        for name, value in {"index.html": "Prior report", "report.md": "Prior summary",
                            "input.txt": "Original.", "events.jsonl": "Original events\n"}.items():
            (self.directory / name).write_text(value, encoding="utf-8")
        self.original = {p.relative_to(self.directory).as_posix(): p.read_bytes()
                         for p in self.directory.rglob("*") if p.is_file()}
        self.result = dict(status="completed", final_score=87.5, metric_version="fixture",
                           summary={}, interpretation="Fixture score", results=[dict(reconstruction="Rebuilt.")])

    def test_publishes_score_and_text_while_preserving_original_graph_and_history(self):
        with patch("pipeline.evaluate_saved_run.Models") as model, \
             patch("pipeline.evaluate_saved_run.evaluate", return_value=self.result) as evaluate, \
             patch("pipeline.evaluate_saved_run.render_report", return_value=("<h2>Final graph reconstruction</h2>", "Report")):
            model.return_value.details = {}
            model.return_value.model = "fixture"
            for field in ("calls", "retries", "cache_hits", "prompt_tokens", "output_tokens"):
                setattr(model.return_value, field, 0)
            result = evaluate_saved_run(self.directory)
        self.assertEqual(result["final_score"], 87.5)
        self.assertEqual(evaluate.call_count, 1)
        self.assertEqual((self.directory / "reconstruction.txt").read_text(), "Rebuilt.\n")
        for name in ("input.txt", "artifacts/graph.json", "artifacts/chunks.json", "events.jsonl"):
            self.assertEqual((self.directory / name).read_bytes(), self.original[name])
        manifest = json.loads((self.directory / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "completed_with_issues")
        self.assertEqual(manifest["duration_seconds"], 120)
        self.assertEqual(manifest["evaluation"]["final_score"], 87.5)
        stats = json.loads((self.directory / "statistics.json").read_text())
        self.assertEqual(stats["models"]["calls"], 20)
        backup = self.directory / manifest["evaluation"]["trace_directory"] / "before/index.html"
        self.assertEqual(backup.read_bytes(), self.original["index.html"])

    def test_service_failure_keeps_all_previous_results_intact(self):
        with patch("pipeline.evaluate_saved_run.Models") as model:
            model.return_value.preflight.side_effect = RuntimeError("Unavailable")
            with self.assertRaisesRegex(RuntimeError, "Unavailable"):
                evaluate_saved_run(self.directory)
        for name, raw in self.original.items():
            self.assertEqual((self.directory / name).read_bytes(), raw)
        self.assertFalse((self.directory / "reconstruction.txt").exists())

    def test_larger_budget_only_changes_document_alignment_and_restores_options(self):
        from ollama import ChatResponse
        from pipeline.evaluation import ClaimAlignment
        from pipeline.trace import Trace
        trace = Trace(self.directory / "model_test", "model_test")
        self.addCleanup(trace.close)
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(
                message=dict(role="assistant", content='{"matches":[]}'), done_reason="stop")
            model = Models(trace, "fixture", "unused", "http://localhost")
            for role, identifier in (("evaluation_claims", "evaluation:document:original"),
                                     ("evaluation_alignment", "chunk_001:alignment"),
                                     ("evaluation_alignment", "evaluation:document:alignment")):
                model.ask(role, "", {}, ClaimAlignment, identifier)
            seen = [call.kwargs["options"] for call in client.return_value.chat.call_args_list]
        self.assertEqual([(o["num_ctx"], o["num_predict"]) for o in seen],
                         [(8192, 4096), (8192, 4096), (16384, 8192)])
        self.assertEqual(model.options["num_ctx"], 8192)
        self.assertEqual(model.options["num_predict"], 4096)
        self.assertEqual(model.cache_hits, 0)  # Same role/prompt still needs a different alignment budget.


if __name__ == "__main__":
    unittest.main()
