"""Regression coverage for notebook packaging and explicit execution modes."""
import contextlib
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request

from pipeline.submission import execute, load_saved, offline_checks, results_table, stop_server
import _submission_runtime as runtime


class SubmissionTests(unittest.TestCase):
    def test_all_embedded_modules_compile_and_import(self):
        for name in runtime.sources:
            with self.subTest(module=name):
                module = importlib.import_module(name)
                self.assertEqual(module.__loader__, runtime.loader)

    def test_offline_and_embedded_ingestion_do_not_call_models(self):
        with patch("pipeline.models.Client", side_effect=AssertionError("Unexpected inference")):
            self.assertTrue(offline_checks()["offsets_preserved"])
            result = execute("ingest")
        self.assertGreater(len(result["chunks"]), 0)
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, "root", Path(directory)):
            self.assertEqual(runtime.input_bytes(Path(directory) / "data/ai_test.txt"),
                             runtime.assets["data/ai_test.txt"].encode())

    def test_full_mode_dispatch_and_partial_exit_code(self):
        with patch("pipeline.cli.main", return_value=2) as main:
            result = execute("full", pipeline_args=["--chapter", "ai-test", "--resume", "saved"])
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(main.call_args.args[0], ["--chapter", "ai-test", "--resume", "saved", "--no-open", "--no-explorer"])

    def test_supported_stage_dispatch(self):
        with patch("pipeline.replay_background.main") as background:
            execute("background", saved_run="saved", stage_args=["--reuse-seeds"])
            background.assert_called_once_with(["saved", "--reuse-seeds"])
        with patch("pipeline.evaluate_saved_run.main", return_value=0) as evaluate:
            self.assertEqual(execute("evaluate", saved_run="saved", stage_args=["--resume-evaluation", "cache"])["exit_code"], 0)
            evaluate.assert_called_once_with(["saved", "--resume-evaluation", "cache"])

    def test_full_orchestration_and_resume_write_notebook_provenance(self):
        # Exercise real orchestration/file publication with synthetic stage boundaries.
        # This establishes packaging compatibility, not language-model correctness.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.txt"
            source.write_text("Synthetic orchestration input.", encoding="utf-8")
            with patch("pipeline.models.Models") as model, \
                 patch("pipeline.extraction.extract", return_value=[]), \
                 patch("pipeline.seeds.build_outline", return_value={"topics": []}), \
                 patch("pipeline.debate.review_extractions", return_value=[]), \
                 patch("pipeline.debate.debate", return_value={"candidates": []}), \
                 patch("pipeline.graph_view.build_graph", return_value=dict(run_id="fixture", nodes=[], edges=[])), \
                 patch("pipeline.evaluation.evaluate", return_value=dict(status="completed", final_score=100., results=[])), \
                 patch("pipeline.report.statistics_for", return_value={}), \
                 patch("pipeline.report.render_report", return_value=("<html>Synthetic</html>", "Synthetic test")), \
                 contextlib.redirect_stdout(io.StringIO()):
                model.return_value.details = {}
                args = ["--input", str(source), "--output-root", str(root / "runs")]
                self.assertEqual(execute("full", pipeline_args=args)["exit_code"], 0)
                first = next((root / "runs/custom").iterdir())
                self.assertEqual(execute("full", pipeline_args=[*args, "--resume", str(first)])["exit_code"], 0)
                model.return_value.load_cache.assert_called_once_with(first)
            runs = list((root / "runs/custom").iterdir())
            self.assertEqual(len(runs), 2)
            for run in runs:
                saved = load_saved(run)
                self.assertEqual(saved["artifacts"]["manifest.json"]["status"], "completed")
                self.assertEqual(saved["warnings"], [])
                hashes = saved["artifacts"]["artifacts/environment.json"]["code_sha256"]
                self.assertEqual(hashes["pipeline/cli.py"], runtime.source_hashes()["pipeline/cli.py"])

    def test_background_replay_orchestration_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            self.write_run(source)
            manifest = json.loads((source / "manifest.json").read_text())
            manifest["config"].update(embedding_model="unused", context_tokens=8192, max_output_tokens=4096)
            (source / "manifest.json").write_text(json.dumps(manifest))
            (source / "input.txt").write_text("Synthetic input.")
            values = dict(chunks=[], paragraphs=[], extractions=[], chapter_outline={"topics": []},
                          concepts={"concepts": []}, concept_reconciliation={"redirects": {}},
                          relations={"relations": []}, seeds={"selected": []})
            for name, value in values.items():
                (source / "artifacts" / (name + ".json")).write_text(json.dumps(value))
            original = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
            with patch("pipeline.replay_background.Models") as model, \
                 patch("pipeline.replay_background.debate", return_value={"candidates": []}), \
                 contextlib.redirect_stdout(io.StringIO()):
                model.return_value.calls = model.return_value.retries = 0
                execute("background", saved_run=source, stage_args=["--reuse-seeds", "--output-root", str(root / "replay")])
            run = next((root / "replay").iterdir())
            replay = json.loads((run / "manifest.json").read_text())
            self.assertTrue(replay["source_unchanged"])
            self.assertEqual(replay["status"], "completed")
            self.assertTrue((run / "knowledge_graph.html").is_file())
            self.assertEqual(original, {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()})

    def test_invalid_selection_fails_before_model_work(self):
        for mode in ("background", "evaluate", "render", "graph"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "requires SAVED_RUN"):
                execute(mode)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            execute("extraction")

    def write_run(self, directory):
        (directory / "artifacts").mkdir(parents=True)
        graph = json.dumps(dict(run_id="fixture", nodes=[], edges=[]))
        (directory / "artifacts/graph.json").write_text(graph)
        manifest = dict(run_id="fixture", status="completed", started_at="2026-01-01T00:00:00+00:00",
                        config=dict(chapter="synthetic", model="unused"),
                        artifacts={"artifacts/graph.json": {"sha256": hashlib.sha256(graph.encode()).hexdigest()}})
        (directory / "manifest.json").write_text(json.dumps(manifest))

    def test_saved_intermediates_keep_missing_scores_and_check_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write_run(path)
            saved = load_saved(path)
            self.assertEqual(saved["hashes_checked"], 1)
            self.assertEqual(saved["warnings"], [])
            self.assertIn("artifacts/evaluation.json", saved["missing"])
            self.assertIn("None", results_table(saved))
            (path / "artifacts/graph.json").write_text('{"nodes":[], "edges":[]}')
            self.assertIn("Hash mismatch: artifacts/graph.json", load_saved(path)["warnings"])

    def test_static_render_and_live_graph_server_never_extract(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write_run(path)
            original = (path / "artifacts/graph.json").read_bytes()
            with patch("pipeline.extraction.extract", side_effect=AssertionError("Extraction rerun")), \
                 patch("pipeline.models.Client", side_effect=AssertionError("Model created on viewer startup")):
                with patch("IPython.display.display") as display:
                    self.assertFalse(execute("render", saved_run=path)["inference"])
                    self.assertIn("iframe", display.call_args.args[0].data)
                try:
                    result = execute("graph", saved_run=path)
                    with urllib.request.urlopen(result["url"], timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b"html", response.read().lower())
                    for asset in ("explorer.js", "explorer.css", "quiz.js"):
                        with urllib.request.urlopen(result["url"] + "/" + asset, timeout=5) as response:
                            self.assertEqual(response.status, 200)
                finally:
                    stop_server()
            self.assertEqual((path / "artifacts/graph.json").read_bytes(), original)

    def test_professor_and_interact_server_start_without_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "runs/topic/run"
            self.write_run(run)
            with patch("pipeline.extraction.extract", side_effect=AssertionError("Extraction rerun")), \
                 patch("pipeline.models.Client", side_effect=AssertionError("Unexpected inference")):
                for mode in ("professor", "interact"):
                    try:
                        result = execute(mode, saved_run=run, runs_root=root / "runs", database=root / "students.sqlite3")
                        with urllib.request.urlopen(result["url"], timeout=5) as response:
                            self.assertEqual(response.status, 200)
                    finally:
                        stop_server()


if __name__ == "__main__":
    unittest.main()
