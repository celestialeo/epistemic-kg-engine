import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.debate import index_complete
from pipeline.extraction import Extraction, extract
from pipeline.registry import ConceptRegistry, RelationRegistry
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
        text = (Path(__file__).resolve().parents[1] / "data/sample.txt").read_text(encoding="utf-8")
        paragraphs, chunks = split_document(text, 85, self.trace)
        self.assertEqual(len(paragraphs), 3)
        self.assertTrue(450 <= len(text.split()) <= 650)
        self.assertGreater(len(chunks), 3)

    def test_exact_evidence_gate(self):
        text = "A neuron transmits signals."
        paragraphs, chunks = split_document(text, 85, self.trace)
        result = Extraction(unit_kind="definition", concepts=[
            {"name": "Neuron", "definition": "Excitable cell", "kind": "entity"},
            {"name": "memory", "definition": "Retention of experience", "kind": "abstract"}],
            claims=[{"text": text, "evidence": text}],
            relations=[{"source": {"name": "neuron", "definition": "Excitable cell", "kind": "entity"},
                        "relation": "causes", "relation_definition": "Produces",
                        "target": {"name": "memory", "definition": "Retention of experience", "kind": "abstract"},
                        "evidence": "invented evidence"}],
            confidence=.8, reason="Source describes a neuron")
        model = SimpleNamespace(ask=lambda *args, **kwargs: result)
        values = extract(chunks, paragraphs, model, self.trace,
                         ConceptRegistry(model, self.trace), RelationRegistry(model, self.trace))
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

    def test_missing_candidate_review_fails(self):
        with self.assertRaises(ValueError):
            index_complete([], [{"id": "candidate_001"}], self.trace, "critic")

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

    def test_all_language_roles_use_selected_model_and_traced_settings(self):
        from pipeline.evaluation import Reconstruction
        from ollama import ChatResponse
        roles = ("extractor", "proposer", "analogy_reviewer", "critic",
                 "proposer_rebuttal", "judge", "reconstructor")
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(
                message={"role": "assistant", "content": '{"text":"valid","reason":"test"}'},
                done=True, done_reason="stop")
            model = Models(self.trace, "qwen3.5:9b", "nomic-embed-text", "http://localhost",
                           timeout=900, think=True, context_tokens=16384, max_output_tokens=8192)
            for role in roles:
                model.ask(role, "test", {}, Reconstruction, "chunk_001")
            client.assert_called_once_with(host="http://localhost", timeout=900)
            requests = [e["data"] for e in self.events() if e["event"] == "model.request"]
            self.assertEqual([r["role"] for r in requests], list(roles))
            for call, recorded in zip(client.return_value.chat.call_args_list, requests):
                self.assertEqual(call.kwargs["model"], "qwen3.5:9b")
                self.assertIs(call.kwargs["think"], True)
                self.assertEqual(call.kwargs["think"], recorded["think"])
                self.assertEqual(call.kwargs["options"], recorded["options"])
                self.assertEqual(call.kwargs["options"]["num_ctx"], 16384)
                self.assertEqual(call.kwargs["options"]["num_predict"], 8192)

    def test_cache_distinguishes_thinking_and_historical_server_default(self):
        request = dict(model="qwen3.5:9b", role="judge", prompt="test", schema={}, options={})
        historical = Models.cache_key("model.request", request)
        direct = Models.cache_key("model.request", {**request, "think": False})
        thinking = Models.cache_key("model.request", {**request, "think": True})
        self.assertEqual(len({historical, direct, thinking}), 3)

    def test_output_limit_rejects_even_valid_json_and_preserves_response(self):
        from pipeline.evaluation import Reconstruction
        from ollama import ChatResponse
        content = '{"text":"looks complete","reason":"test"}'
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(
                message={"role": "assistant", "content": content}, done=True, done_reason="length")
            model = Models(self.trace, "qwen3.5:9b", "nomic-embed-text", "http://localhost")
            with self.assertRaisesRegex(RuntimeError, "increase --max-output-tokens"):
                model.ask("judge", "test", {}, Reconstruction, "candidate_001")
            self.assertIs(client.return_value.chat.call_args.kwargs["think"], False)
        responses = [e["data"]["response"] for e in self.events() if e["event"] == "model.response"]
        self.assertEqual(len(responses), 1)
        self.assertTrue(all(r["message"]["content"] == content for r in responses))
        self.assertEqual(self.trace.counts["validation.completed"], 0)

    def test_invalid_model_budgets_fail_before_creating_a_run(self):
        from pipeline.cli import main
        for flags in (["--context-tokens", "0"], ["--max-output-tokens", "0"],
                      ["--model-timeout", "0"], ["--max-output-tokens", "8192"]):
            with self.subTest(flags=flags), self.assertRaises(SystemExit) as raised:
                main(flags)
            self.assertEqual(raised.exception.code, 2)

    def test_failed_run_has_manifest_and_error_trace(self):
        from pipeline.cli import main
        code = main(["--input", str(Path(self.temp.name)/"missing.txt"), "--output-root", str(Path(self.temp.name)/"failed"), "--no-open"])
        self.assertEqual(code, 1)
        manifest_path = next((Path(self.temp.name)/"failed").glob("*/*/manifest.json"))
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
            def __init__(self, trace, model, embedding_model, host, **kwargs):
                self.model, self.embedding_model = model, embedding_model
                self.settings = kwargs
            def preflight(self):
                pass
            def embed(self, text, entity):
                return [1., 2., 3.]
            def ask(self, role, instruction, payload, schema, entity, validator=None):
                if role == "extractor":
                    text = payload["CURRENT_CHUNK"]
                    name = "neuron" if "A neuron" in text else "neurons"
                    value = {"unit_kind": "definition", "concepts": [{"name": name, "definition": "Excitable cell", "kind": "entity"}],
                             "claims": [{"text": text, "evidence": text}],
                             "relations": [], "confidence": .9, "reason": "Fixture"}
                elif role == "segment_summarizer":
                    value = {"summary": "Neuronal signals", "topics": ["neuron"]}
                elif role == "chapter_summarizer":
                    value = {"overview": "Neuronal signals", "topics": ["neuron"]}
                elif role == "concept_resolver":
                    value = {"key": "neuron", "exact_meaning": True, "same_direction": True, "reason": "Plural"}
                elif role == "concept_match_verifier":
                    value = {"exact_meaning": True, "same_direction": True, "compatible_types": True, "reason": "Plural"}
                elif role == "seed_selector":
                    value = {c["id"]: {"importance": .9, "relevance": .9,
                             "decision": "eligible", "chapter_topic": "neuron",
                             "background_question": "How does a neuron transmit a signal?",
                             "expansion_value": .9, "reason": "Main subject"} for c in payload["items"]}
                elif role == "proposer":
                    value = {"proposals": [], "reason": "No useful background additions"}
                elif role == "reconstructor":
                    value = {"text": " ".join(payload["claims"]), "reason": "Fixture"}
                else:
                    raise AssertionError(role)
                result = schema.model_validate(value)
                if validator:
                    validator(result)
                return result
        fixture = Path(self.temp.name) / "input.txt"
        fixture.write_text("A neuron is excitable.\n\nNeurons transmit signals.\n\nSynapses connect neurons.", encoding="utf-8")
        destination = Path(self.temp.name) / "complete"
        with patch("pipeline.models.Models", FakeModels):
            code = main(["--input", str(fixture), "--output-root", str(destination), "--no-open"])
        self.assertEqual(code, 0)
        run = next(p for p in (destination / "custom").iterdir() if p.is_dir())
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["config"]["model"], "qwen3.5:9b")
        self.assertIs(manifest["config"]["think"], False)
        self.assertIn("started_at_utc", manifest)
        import hashlib
        for name, info in manifest["artifacts"].items():
            self.assertEqual(hashlib.sha256((run / name).read_bytes()).hexdigest(), info["sha256"])
        import re
        for link in re.findall('href="([^"]+)"', (run / "index.html").read_text(encoding="utf-8")):
            self.assertTrue((run / link).exists(), link)
        stats = json.loads((run / "statistics.json").read_text())
        self.assertEqual(stats["models"]["generation"], "qwen3.5:9b")
        self.assertEqual(stats["models"]["embedding"], "nomic-embed-text")
        self.assertEqual(stats["input"]["chunks"], 3)
        self.assertEqual(stats["debate"]["proposed"], 0)
        self.assertAlmostEqual(stats["fidelity"]["semantic_cosine"]["mean"], 1.)


if __name__ == "__main__":
    unittest.main()
