import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.beforevsafter import comparisons, main, resolve_comparison, write_dashboard


class BeforeAfterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "outputs/runs"
        self.source = self.runs / "run-1"
        self.out = self.source / "factscore/pilot-1"
        self.out.mkdir(parents=True)
        self.data = {"source_run": "run-1", "status": "complete", "pilot": True, "evaluated_chunks": 2,
                     "edge_limit": 2, "created_at": "2026-09-20", "background": {"baseline_edges": 2, "retained_edges": 0, "removed_edges": 2},
                     "evidence_mode": "input_document_only", "metrics": {}}
        (self.out / "comparison.json").write_text(json.dumps(self.data))
        (self.source / "manifest.json").write_text(json.dumps({"run_id": "run-1", "status": "complete"}))
        for filename in ["baseline/fidelity.html", "factscore/fidelity.html", "report.html",
                         "baseline/background_approved.json", "factscore/background_approved.json"]:
            path = self.out / filename
            path.parent.mkdir(exist_ok=True)
            path.write_text("{}")

    def test_discovery_resolves_comparison_and_run_and_ignores_interrupted(self):
        self.assertEqual(resolve_comparison(None, self.runs)[0], self.out)
        self.assertEqual(resolve_comparison("run-1", self.runs)[0], self.out)
        self.assertEqual(resolve_comparison(str(self.source), self.runs)[0], self.out)
        self.assertEqual(resolve_comparison(str(self.out), self.runs)[0], self.out)
        bad = self.source / "factscore/newer"
        bad.mkdir()
        (bad / "comparison.json").write_text(json.dumps({**self.data, "status": "interrupted"}))
        self.assertEqual(len(comparisons(self.runs)), 1)

    def test_dashboard_has_both_reports_and_full_graph_link_and_escapes_labels(self):
        attack = "<script>alert(1)</script>"
        with patch("pipeline.factscore_experiment.write_comparison_graph"):
            page = write_dashboard(self.out, {**self.data, "source_run": attack}).read_text(encoding="utf-8")
        self.assertNotIn(attack, page)
        self.assertIn("PILOT", page)
        self.assertIn('src="graph_comparison.html#all"', page)
        self.assertIn('src="baseline/fidelity.html"', page)
        self.assertIn('src="factscore/fidelity.html"', page)
        self.assertIn("Statistics and what changed", page)

    def test_default_view_does_not_run_models(self):
        with patch("pipeline.beforevsafter.ROOT", self.root), \
             patch("pipeline.factscore_experiment.write_comparison_graph"), \
             patch("pipeline.cli.main", side_effect=AssertionError("Must not run pipeline")):
            self.assertEqual(main(["--no-open"]), 0)
        self.assertTrue((self.out / "beforevsafter.html").exists())

    def test_full_run_passes_no_pilot_limits_and_opens_only_new_experiment(self):
        def run(arguments):
            self.assertIn("--compare-factscore", arguments)
            self.assertNotIn("--factscore-limit", arguments)
            self.assertNotIn("--factscore-edge-limit", arguments)
            after = self.source / "factscore/full-1"
            after.mkdir()
            (after / "comparison.json").write_text(json.dumps({**self.data, "pilot": False, "created_at": "2026-09-21"}))
            return 0
        with patch("pipeline.beforevsafter.ROOT", self.root), patch("pipeline.cli.main", side_effect=run), \
             patch("pipeline.beforevsafter.write_dashboard", return_value=self.out / "beforevsafter.html") as writer:
            self.assertEqual(main(["--run", "run-1", "--no-open"]), 0)
            self.assertEqual(writer.call_args.args[0].name, "full-1")

    def test_failed_run_does_not_open_old_pilot(self):
        with patch("pipeline.beforevsafter.ROOT", self.root), patch("pipeline.cli.main", return_value=1), \
             patch("pipeline.beforevsafter.write_dashboard") as writer:
            self.assertEqual(main(["--run", "run-1", "--no-open"]), 1)
            writer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
