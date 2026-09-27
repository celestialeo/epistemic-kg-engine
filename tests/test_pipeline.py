import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.debate import debate, index_complete, weights_for
from pipeline.extraction import Extraction, extract
from pipeline.graph_view import build_graph, render_graph
from pipeline.ingest import split_document
from pipeline.models import Models
from pipeline.trace import Trace


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "run", "test")
        self.addCleanup(self.trace.close)

    def events(self):
        return [json.loads(line) for line in (self.trace.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_run_name_uses_local_date_when_utc_is_next_day(self):
        from datetime import datetime, timedelta, timezone
        from pipeline.cli import make_run_id
        local = datetime(2026, 9, 24, 2, 55, 9, tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=-4)))
        self.assertRegex(make_run_id(local), r"^run_20260923_225509_UTC-0400_[0-9a-f]{8}$")

    def test_lossless_order_and_offsets(self):
        text = "  First idea grows. More details follow.\r\n\r\nSecond idea connects to the first one in a long sentence.\n\n最後の段落 is here!\n"
        paragraphs, chunks = split_document(text, 5, self.trace)
        self.assertEqual(len(paragraphs), 3)
        self.assertEqual(" ".join(text.split()), " ".join(" ".join(c["text"] for c in chunks).split()))
        for index, chunk in enumerate(chunks):
            self.assertEqual(text[chunk["start"]:chunk["end"]], chunk["text"])
            self.assertLessEqual(chunk["word_count"], 5)
            self.assertEqual(chunk["previous_id"], chunks[index-1]["id"] if index else None)
        self.assertEqual([c["start"] for c in chunks], sorted(c["start"] for c in chunks))

    def test_paragraphs_never_merged_and_whitespace(self):
        for text in ("A.\n\nB.\n\nC.", "A.\r\n \t\r\nB.\r\n\r\nC."):
            paragraphs, chunks = split_document(text, 100, self.trace)
            self.assertEqual(len(paragraphs), 3)
            self.assertEqual(len(chunks), 3)

    def test_invalid_input(self):
        for text, limit in ((" ", 10), ("Text", 0)):
            with self.assertRaises(ValueError):
                split_document(text, limit, self.trace)

    def test_sample_is_three_paragraphs_about_one_page(self):
        text = (Path(__file__).resolve().parents[1] / "data/input.txt").read_text(encoding="utf-8")
        paragraphs, chunks = split_document(text, 85, self.trace)
        self.assertEqual(len(paragraphs), 3)
        self.assertTrue(450 <= len(text.split()) <= 650)
        self.assertGreater(len(chunks), 3)

    def test_exact_evidence_gate(self):
        text = "A neuron transmits signals."
        paragraphs, chunks = split_document(text, 85, self.trace)
        result = Extraction(unit_kind="definition", concepts=["Neuron"],
            claims=[{"text": text, "evidence": text}],
            relations=[{"source": "neuron", "relation": "causes", "target": "memory", "evidence": "invented evidence"}],
            confidence=.8, reason="Source describes a neuron")
        model = SimpleNamespace(ask=lambda *args: result)
        values = extract(chunks, paragraphs, model, self.trace)
        self.assertEqual(values[0]["relations"], [])
        self.assertEqual(values[0]["concepts"], ["neuron"])
        self.assertEqual(self.trace.counts["extraction.record_rejected"], 1)

    def test_graph_can_be_replayed_exactly_from_events(self):
        text = "A neuron transmits signals."
        paragraphs, chunks = split_document(text, 85, self.trace)
        extraction = {"chunk_id": chunks[0]["id"], "concepts": ["neuron"],
                      "claims": [{"text": text, "evidence": text}], "relations": [],
                      "confidence": .8, "unit_kind": "definition"}
        candidate = {"id": "candidate_001", "source": "neuron", "target": "excitable cell", "accepted": True,
                     "relation": "is_a", "chunk_id": chunks[0]["id"], "score": .8, "tier": "parent", "decision_reason": "Test"}
        graph = build_graph(text, paragraphs, chunks, [extraction], {"candidates": [candidate]}, self.trace)
        replay_nodes, replay_edges = {}, {}
        for e in self.events():
            if e["event"] in {"graph.node_added", "graph.node_updated"}:
                replay_nodes[e["entity_id"]] = e["data"]["node"]
            elif e["event"] == "graph.edge_added":
                replay_edges[e["entity_id"]] = e["data"]["edge"]
        self.assertEqual(list(replay_nodes.values()), graph["nodes"])
        self.assertEqual(list(replay_edges.values()), graph["edges"])
        self.assertTrue(all(e["source"] in replay_nodes and e["target"] in replay_nodes for e in graph["edges"]))
        self.assertEqual(next(n for n in graph["nodes"] if n["label"] == "neuron")["origin"], "both")

    def test_html_escape(self):
        graph = {"run_id": "</script><script>alert(1)</script>", "nodes": [], "edges": []}
        page = render_graph(graph)
        self.assertNotIn(graph["run_id"], page)
        payload = page.split('<script type="application/json" id="graph-data">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload), graph)

    def test_withdrawal_overrides_judge_and_score(self):
        def ask(role, instruction, payload, schema, entity, validator=None):
            if role == "proposer":
                value = {"proposals": [{"target": "excitable cell", "tier": "parent", "relation": "is_a", "confidence": 1, "reason": "Test"}], "reason": "Test"}
            elif role == "proposer_rebuttal":
                value = {"candidate_001": {"candidate_id": "candidate_001", "position": "withdraw", "reason": "Not useful"}}
            else:
                row = {"candidate_id": "candidate_001", "domain_relevance": 1, "hierarchical_plausibility": 1, "prerequisite_value": 1, "reason": "Test"}
                if role == "judge":
                    row["accept"] = True
                value = {"candidate_001": row}
            result = schema.model_validate(value)
            if validator:
                validator(result)
            return result
        seed = {"id": "seed_001", "concept": "neuron", "chunk_id": "chunk_001", "paragraph_id": "paragraph_001", "context": "Test"}
        result = debate([seed], SimpleNamespace(ask=ask), self.trace)
        self.assertFalse(result["candidates"][0]["accepted"])
        self.assertEqual(self.trace.counts["debate.decision"], 1)

    def test_missing_candidate_review_fails(self):
        with self.assertRaises(ValueError):
            index_complete([], [{"id": "candidate_001"}], self.trace, "critic")

    def test_weights_are_normalized_with_degenerate_fallback(self):
        for matrix in ([], [[0, 0, 0, 0]] * 2, [[.2, .4, .6, .8], [.8, .7, .5, .4]]):
            weights = weights_for(matrix)
            self.assertAlmostEqual(sum(weights), 1)
            self.assertTrue(all(v >= 0 for v in weights))

    def test_parse_failure_retry_preserves_both_raw_responses(self):
        class Raw:
            prompt_eval_count = eval_count = 1
            def __init__(self, content):
                self.message = SimpleNamespace(content=content)
            def model_dump(self, **kwargs):
                return {"message": {"content": self.message.content}}
        from pipeline.evaluation import Reconstruction
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.side_effect = [Raw("invalid json"), Raw('{"text":"valid", "reason":"test"}')]
            model = Models(self.trace, "test", "test", "http://localhost")
            result = model.ask("test", "test", {}, Reconstruction, "chunk_001")
        self.assertEqual(result.text, "valid")
        self.assertEqual(self.trace.counts["model.response"], 2)
        self.assertEqual(self.trace.counts["model.retry"], 1)
        events = self.events()
        self.assertEqual([e["sequence"] for e in events], list(range(1, len(events)+1)))
        ids = {e["event_id"] for e in events}
        self.assertTrue(all(not e["parent_id"] or e["parent_id"] in ids for e in events))

    def test_semantic_validation_retries_duplicate_debate_ids(self):
        from pipeline.debate import Response
        from pydantic import create_model
        Rebuttal = create_model("Rebuttal", responses=(list[Response], ...))
        class Raw:
            def __init__(self, data):
                self.data = data
            def model_dump(self, **kwargs):
                return {"message": {"content": json.dumps(self.data)}}
        row = {"candidate_id": "candidate_001", "position": "defend", "reason": "Test"}
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.side_effect = [Raw({"responses": [row, row]}), Raw({"responses": [row]})]
            model = Models(self.trace, "test", "test", "http://localhost")
            result = model.ask("rebuttal", "test", {}, Rebuttal, "seed_001",
                validator=lambda r: index_complete(r.responses, [{"id": "candidate_001"}], self.trace, "rebuttal"))
        self.assertEqual(len(result.responses), 1)
        self.assertEqual(self.trace.counts["validation.failed"], 1)
        self.assertEqual(model.retries, 1)

    def test_resume_revalidates_cached_output_without_network_call(self):
        from pipeline.evaluation import Reconstruction
        class Raw:
            def model_dump(self, **kwargs):
                return {"message": {"content": '{"text":"saved", "reason":"test"}'}, "eval_count": 5}
        details = {"installed_models": {"models": [{"model": "test", "digest": "fixed-digest"}]}}
        self.trace.save("artifacts/environment.json", {"model_details": details})
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = Raw()
            model = Models(self.trace, "test", "test", "http://localhost")
            model.ask("test", "test", {}, Reconstruction, "chunk_001")
        resumed_trace = Trace(Path(self.temp.name)/"resumed", "resumed")
        self.addCleanup(resumed_trace.close)
        with patch("pipeline.models.Client") as client:
            model = Models(resumed_trace, "test", "test", "http://localhost")
            model.details = details
            model.load_cache(self.trace.directory)
            result = model.ask("test", "test", {}, Reconstruction, "chunk_001")
            client.return_value.chat.assert_not_called()
        self.assertEqual(result.text, "saved")
        self.assertEqual(model.cache_hits, 1)
        self.assertEqual(model.calls, 0)
        self.assertEqual(model.output_tokens, 0)
        self.assertEqual(resumed_trace.counts["validation.completed"], 1)

    def test_failed_run_has_manifest_and_error_trace(self):
        from pipeline.cli import main
        code = main(["--input", str(Path(self.temp.name)/"missing.txt"), "--output-root", str(Path(self.temp.name)/"failed"), "--no-open"])
        self.assertEqual(code, 1)
        manifest_path = next((Path(self.temp.name)/"failed").glob("*/manifest.json"))
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["status"], "failed")
        events = [json.loads(line) for line in manifest_path.with_name("events.jsonl").read_text().splitlines()]
        self.assertIn("run.failed", [e["event"] for e in events])
        self.assertEqual(events[-1]["event"], "run.closed")

    def test_complete_workflow_artifacts_and_report_links(self):
        from pipeline.cli import main
        class FakeModels:
            model = embedding_model = "fixture"
            calls = retries = prompt_tokens = output_tokens = cache_hits = 0
            details = {}
            def __init__(self, *args):
                pass
            def preflight(self):
                pass
            def embed(self, text, entity):
                return [1., 2., 3.]
            def ask(self, role, instruction, payload, schema, entity):
                if role == "extractor":
                    text = payload["CURRENT_CHUNK"]
                    value = {"unit_kind": "definition", "concepts": ["neuron"], "claims": [{"text": text, "evidence": text}],
                             "relations": [], "confidence": .9, "reason": "Fixture"}
                elif role == "proposer":
                    value = {"proposals": [], "reason": "No useful background additions"}
                elif role == "reconstructor":
                    value = {"text": " ".join(payload["claims"]), "reason": "Fixture"}
                else:
                    raise AssertionError(role)
                return schema.model_validate(value)
        fixture = Path(self.temp.name) / "input.txt"
        fixture.write_text("A neuron is excitable.\n\nNeurons transmit signals.\n\nSynapses connect neurons.", encoding="utf-8")
        destination = Path(self.temp.name) / "complete"
        with patch("pipeline.models.Models", FakeModels):
            code = main(["--input", str(fixture), "--output-root", str(destination), "--no-open"])
        self.assertEqual(code, 0)
        run = next(p for p in destination.iterdir() if p.is_dir())
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "completed")
        self.assertIn("started_at_utc", manifest)
        import hashlib
        for name, info in manifest["artifacts"].items():
            self.assertEqual(hashlib.sha256((run / name).read_bytes()).hexdigest(), info["sha256"])
        import re
        for link in re.findall('href="([^"]+)"', (run / "index.html").read_text(encoding="utf-8")):
            self.assertTrue((run / link).exists(), link)
        stats = json.loads((run / "statistics.json").read_text())
        self.assertEqual(stats["input"]["chunks"], 3)
        self.assertEqual(stats["debate"]["proposed"], 0)
        self.assertAlmostEqual(stats["fidelity"]["semantic_cosine"]["mean"], 1.)


if __name__ == "__main__":
    unittest.main()
