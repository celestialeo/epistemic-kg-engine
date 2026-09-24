import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.factscore import (CachedModels, PassageIndex, atomic_claims, check_background,
                               check_claim, evaluate_reconstruction, load_references, precision, save_json)
from pipeline.factscore_experiment import background_hints, run_comparison, validate_source
from pipeline.factscore_report import compare_results, paired_statistics
from pipeline.cli import main, update_comparison_links


class AnswerModel:
    def __init__(self, answer):
        self.answer = answer
        self.prompt = None

    def json_call(self, prompt, validate):
        self.prompt = prompt
        validate(self.answer)
        return self.answer


class FixtureModels:
    """Deterministic controlled experiment; never presented as real model results."""
    def json_call(self, prompt, validate):
        if prompt.startswith("Extract ALL"):
            text = json.loads(prompt.split("TEXT:\n", 1)[1])
            claims = [p.strip() + "." for p in text.split(".") if p.strip()]
            result = {"claims": claims, "no_factual_content": not claims}
        else:
            payload = json.loads(prompt.split("\n", 1)[1])
            claim = payload["claim"]
            supported = "planet" not in claim and any("cell" in p["text"] for p in payload["evidence"])
            p = payload["evidence"][0]
            result = {"status": "supported" if supported else "not_supported", "reason": "Fixture decision",
                      "citations": [{"id": p["id"], "quote": p["text"]}] if supported else []}
        validate(result)
        return result

    def generate(self, prompt):
        return "A neuron is a cell." + (" A neuron is a planet." if "IS_A planet" in prompt else "")

    def embed(self, text):
        return [float(text.count("cell")), float(text.count("planet")), 1.0]


class FactScoreTests(unittest.TestCase):
    def test_exact_citations_required_for_support_and_contradiction(self):
        evidence = [{"id": "p1", "text": "A neuron is a cell."}]
        for status in ("supported", "contradicted"):
            for citation in ([], [{"id": "missing", "quote": "cell"}], [{"id": "p1", "quote": "invented"}]):
                with self.subTest(status=status, citation=citation), self.assertRaises(ValueError):
                    check_claim("Claim", evidence, AnswerModel({"status": status, "citations": citation, "reason": "why"}))
        result = check_claim("A neuron is a cell.", evidence, AnswerModel({
            "status": "supported", "citations": [{"id": "p1", "quote": "A neuron is a cell."}], "reason": "Entailed"}))
        self.assertEqual(result["retrieved_ids"], ["p1"])

    def test_missing_evidence_is_not_falsehood_or_a_model_call(self):
        result = check_claim("Anything", [], object())
        self.assertEqual(result["status"], "not_supported")
        self.assertIsNone(precision([]))

    def test_atomic_claims_validate_and_deduplicate(self):
        self.assertEqual(atomic_claims("text", AnswerModel({"claims": ["Claim.", "Claim."]})), ["Claim."])
        with self.assertRaises(ValueError):
            atomic_claims("text", AnswerModel({"claims": []}))
        with self.assertRaises(ValueError):
            atomic_claims("text", AnswerModel({"claims": "text"}))

    def test_precision_and_coverage_have_different_denominators(self):
        models = FixtureModels()
        result = evaluate_reconstruction("A neuron is a cell.", "A neuron is a cell. A neuron is a planet.",
                                         ["A neuron is a cell."], models)
        self.assertEqual(result["source_precision"], .5)
        self.assertEqual(result["source_coverage"], 1)
        self.assertAlmostEqual(result["source_f1"], 2 / 3)

    def test_empty_generation_is_not_perfect(self):
        result = evaluate_reconstruction("A neuron is a cell.", "", ["A neuron is a cell."], FixtureModels())
        self.assertIsNone(result["source_precision"])
        self.assertEqual(result["source_coverage"], 0)
        self.assertEqual(result["source_f1"], 0)

    def test_relation_is_checked_even_with_supported_justification(self):
        index = PassageIndex([{"id": "p", "text": "A neuron is a cell."}])
        edge = {"source_concept": "neuron", "target_concept": "planet", "relation_type": "is_a",
                "justification": "A neuron is a cell."}
        result = check_background(edge, index, FixtureModels())
        self.assertFalse(result["evidence_accepted"])
        self.assertEqual(result["factscore"], .5)

    def test_bm25_ranks_evidence_and_limits_results(self):
        index = PassageIndex([{"id": "b", "text": "cell neuron"}, {"id": "a", "text": "cell neuron"},
                              {"id": "z", "text": "ocean water"}])
        self.assertEqual(index.search("neuron", 1)[0]["id"], "a")
        self.assertEqual(index.search("unmatched"), [])

    def test_references_preserve_attribution_and_reject_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "references.json"
            save_json(path, {"passages": [{"id": "p", "text": "Source", "source": "Book p. 5"}]})
            self.assertEqual(load_references(path)[0]["source"], "Book p. 5")
            save_json(path, {"chunks": [{"chunk_id": "same", "text": "a"}, {"chunk_id": "same", "text": "b"}]})
            with self.assertRaises(ValueError):
                load_references(path)

    def test_background_retrieval_keeps_baseline_scope_ranking_and_limits(self):
        edges = [{"source_concept": "neuron", "target_concept": target, "relation_type": relation,
                  "eigenvalue_weighted_score": score, "justification": ""}
                 for target, relation, score in [("cell", "is_a", .8), ("axon", "has_part", .9),
                                                  ("other neuron", "sibling_of", 1), ("cell", "is_a", .7)]]
        rows, lines = background_hints(edges, ["neuron"], "definition", per_concept=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target_concept"], "axon")
        self.assertIn("0.90", lines[0])
        rows, _ = background_hints(edges, ["neuron"], "definition")
        self.assertEqual(rows[1]["confidence"], .7)
        self.assertEqual(background_hints(edges, ["neuron"], "metadata"), ([], []))

    def test_fidelity_cards_escape_model_supplied_hints(self):
        from src.report_fidelity import render_card
        attack = '<img src=x onerror="alert(1)">'
        card = render_card({"chunk_id": attack, "unit_kind": attack, "concepts": [attack],
                            "relation_lines": [attack], "scores": {}}, .7)
        self.assertNotIn(attack, card)
        self.assertIn("&lt;img", card)

    def test_statistics_pair_ids_exclude_bypass_errors_and_undefined(self):
        def row(cid, score, **kw):
            return {"chunk_id": cid, "scores": {"source_precision": score}, **kw}
        a = [row("1", .5), row("2", 0), row("3", 1, bypass_llm=True), row("4", None)]
        b = [row("4", 1), row("3", 1, bypass_llm=True), row("2", 1), row("1", 1)]
        result = compare_results(a, b)["source_precision"]
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["delta"], .75)
        self.assertEqual(result["excluded_or_undefined"], 2)
        self.assertEqual(result, compare_results(a, b)["source_precision"])

    def test_statistics_degenerate_samples_are_explicit(self):
        self.assertIsNone(paired_statistics([])["delta"])
        self.assertIsNone(paired_statistics([(.5, 1)])["ci95"])
        same = paired_statistics([(1, 1), (1, 1)])
        self.assertEqual(same["ci95"], [0, 0])
        self.assertEqual(same["t_p"], 1)
        self.assertIsNone(paired_statistics([(0, 1), (0, 1)])["t_p"])

    def test_cache_reuses_successes_and_isolates_models(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.json"
            m = CachedModels("gen", "judge", "embed", path)
            self.assertEqual(m._cached("test", "p", lambda: "ok"), "ok")
            self.assertEqual(m._cached("test", "p", lambda: self.fail("Cache miss")), "ok")
            other = CachedModels("gen", "other", "embed", path)
            self.assertEqual(other._cached("test", "p", lambda: "new"), "new")


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.source.mkdir()
        self.out = self.source / "factscore" / "comparison"
        text = "A neuron is a cell."
        rows = [{"chunk_id": "1", "text": text}, {"chunk_id": "2", "text": text}]
        fixtures = {"chunks": {"chunks": rows}, "concepts": {"concepts": [{"id": "neuron"}]},
                    "extractions": {"extractions": [{**r, "llm": {"concepts": ["neuron"]}} for r in rows]},
                    "mentions": {"mentions": [{"from_chunk_id": r["chunk_id"], "to_concept": "neuron"} for r in rows]},
                    "relations": {"relations": []},
                    "background_approved": {"approved_edges": [
                        {"source_concept": "neuron", "target_concept": target, "relation_type": "is_a",
                         "justification": "A neuron is a " + target + ".", "eigenvalue_weighted_score": .8}
                        for target in ["cell", "planet"]]},
                    "document": {"results": [{"chunk_id": r["chunk_id"], "original": text, "concepts": ["neuron"],
                                                 "unit_kind": "definition", "scores": {"threshold": .7}} for r in rows]},
                    "manifest": {"run_id": "fixture", "model": "fixture", "embedding_model": "fixture", "status": "complete"}}
        for name, value in fixtures.items():
            save_json(self.source / (name + ".json"), value)
        (self.source / "index.html").write_text("<html>Original results</html>", encoding="utf-8")

    def test_full_experiment_preserves_baseline_and_reports_changes(self):
        before = {p.name: p.read_bytes() for p in self.source.glob("*.json")}
        result = run_comparison(self.source, self.out, models=FixtureModels(), progress=lambda _: None)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["background"]["retained_edges"], 1)
        self.assertEqual(result["metrics"]["source_precision"]["delta"], .5)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.glob("*.json")})
        for file in ["report.html", "report.md", "comparison.json", "graph_comparison.html", "references.json",
                     "baseline/graph.json", "factscore/graph.json", "baseline/fidelity.html", "factscore/fidelity.html"]:
            self.assertTrue((self.out / file).exists(), file)
        baseline = json.loads((self.out / "baseline/graph.json").read_text())
        after = json.loads((self.out / "factscore/graph.json").read_text())
        self.assertEqual(sum(e["origin"] == "background" for e in baseline["edges"]), 2)
        self.assertEqual(sum(e["origin"] == "background" for e in after["edges"]), 1)
        update_comparison_links(self.source)
        update_comparison_links(self.source)
        page = (self.source / "index.html").read_text()
        self.assertEqual(page.count("FACTSCORE START"), 1)
        self.assertIn("graph_comparison.html", page)

    def test_checker_errors_mark_partial_and_do_not_become_false_claims(self):
        with patch("pipeline.factscore_experiment.check_background", side_effect=RuntimeError("Judge unavailable")):
            data = run_comparison(self.source, self.out, models=FixtureModels(), progress=lambda _: None)
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["background"]["errors"], 2)
        self.assertIsNone(data["background"]["precision"])

    def test_pilot_limits_apply_to_both_graphs_and_are_reported(self):
        data = run_comparison(self.source, self.out, models=FixtureModels(), progress=lambda _: None,
                              limit=1, edge_limit=1)
        self.assertTrue(data["pilot"])
        self.assertEqual(data["evaluated_chunks"], 1)
        self.assertEqual(data["background"]["baseline_edges"], 1)
        for arm in ("baseline", "factscore"):
            chunks = json.loads((self.out / arm / "chunks.json").read_text())["chunks"]
            self.assertEqual([r["chunk_id"] for r in chunks], ["1"])
        self.assertIn("PILOT SAMPLE", (self.out / "report.md").read_text())

    def test_external_reference_mode_keeps_supplied_sources(self):
        reference = self.source / "external.json"
        save_json(reference, {"passages": [{"id": "book-1", "text": "A neuron is a cell.", "source": "Reference book p. 1"}]})
        data = run_comparison(self.source, self.out, references=reference, models=FixtureModels(), progress=lambda _: None)
        self.assertEqual(data["evidence_mode"], "external_reference_collection")
        evidence = json.loads((self.out / "references.json").read_text())
        self.assertEqual(evidence["passages"][0]["source"], "Reference book p. 1")

    def test_all_source_claim_failures_still_write_auditable_reports(self):
        with patch("pipeline.factscore_experiment.atomic_claims", side_effect=RuntimeError("Claim error")):
            data = run_comparison(self.source, self.out, models=FixtureModels(), progress=lambda _: None)
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data["metrics"]["source_precision"]["n"], 0)
        self.assertTrue((self.out / "report.html").exists())

    def test_source_validation_rejects_mismatched_text(self):
        path = self.source / "document.json"
        data = json.loads(path.read_text())
        data["results"][0]["original"] = "Different source"
        save_json(path, data)
        with self.assertRaises(ValueError):
            validate_source(self.source)

    def test_resume_preserves_settings_and_rejects_changed_evidence(self):
        run_comparison(self.source, self.out, models=FixtureModels(), progress=lambda _: None)
        path = self.out / "manifest.json"
        saved = json.loads(path.read_text())
        saved["status"] = "interrupted"
        save_json(path, saved)
        result = run_comparison(self.source, self.out, models=FixtureModels(), progress=lambda _: None, resume=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["attempt_history"][0]["status"], "interrupted")
        with self.assertRaisesRegex(ValueError, "not a running or complete"):
            run_comparison(self.source, self.out, models=FixtureModels(), resume=True)
        result["status"] = "interrupted"
        save_json(path, result)
        save_json(self.out / "references.json", {"passages": [{"id": "tampered", "text": "Changed"}]})
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            run_comparison(self.source, self.out, models=FixtureModels(), resume=True)

    def test_saved_comparison_dry_run_needs_no_services_and_writes_nothing(self):
        with patch("pipeline.factscore_experiment.get_model_details", side_effect=AssertionError("No services")):
            self.assertEqual(main(["--compare-factscore", str(self.source), "--dry-run"]), 0)
        self.assertFalse(self.out.parent.exists())

    def test_new_baseline_stays_complete_when_comparison_fails(self):
        new_run = Path(self.temp.name) / "new-run"
        with patch("pipeline.cli.check_dependencies"), patch("pipeline.cli.load_environment"), \
             patch("pipeline.cli.preflight"), patch("pipeline.cli.present"), \
             patch("pipeline.cli.build_plan", return_value=[]), \
             patch("pipeline.cli.compare_factscore_run", side_effect=RuntimeError("Verifier unavailable")), \
             patch.dict(os.environ, {"NEO4J_DB": "neo4j"}):
            result = main(["--new", "--factscore", "--input", str(self.source / "chunks.json"),
                           "--output-dir", str(new_run), "--no-open"])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads((new_run / "manifest.json").read_text())["status"], "complete")

    def test_comparison_html_escapes_script_delimiters(self):
        manifest = self.source / "manifest.json"
        data = json.loads(manifest.read_text())
        attack = "</script><script>alert(1)</script>"
        data["run_id"] = attack
        save_json(manifest, data)
        run_comparison(self.source, self.out, models=FixtureModels(), progress=lambda _: None)
        page = (self.out / "graph_comparison.html").read_text(encoding="utf-8")
        self.assertNotIn(attack, page)
        payload = page.split('id="comparison-data">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)["run_id"], attack)
        self.assertNotIn(attack, (self.out / "report.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
