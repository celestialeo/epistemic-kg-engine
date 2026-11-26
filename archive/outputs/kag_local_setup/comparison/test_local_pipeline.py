"""Integration checks with native KAG components and prohibited network access."""
import copy
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from comparison import native
from comparison.baseline.trace import Trace
from comparison.baseline.evaluation import evaluate, reconstruction_context
from comparison.projection import graph_projection

ROOT = Path(__file__).resolve().parents[1]
TEXT = "The sun heats water."


class FixtureEvaluator:
    def ask(self, role, instruction, data, schema, entity_id, validator=None):
        if role == "reconstructor":
            assert "text" not in data
            assert "content" not in json.dumps(data)
            result = schema(text=TEXT, reason="Fixture reconstruction from the heat relation")
        elif role == "evaluation_claims":
            result = schema(claims=[dict(text=TEXT, evidence=data["text"])])
        elif role == "evaluation_alignment":
            result = schema(matches=[dict(original_index=0, reconstructed_index=0, reason="Same fact")])
        else:
            raise AssertionError(role)
        if validator:
            validator(result)
        return result


class LocalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.cwd = Path.cwd()
        self.temp = tempfile.TemporaryDirectory(prefix="kag-local-test-")
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "run", "fixture")
        self.addCleanup(self.trace.close)
        self.addCleanup(os.chdir, self.cwd)
        self.built = {}
        self.network = patch("socket.socket.connect", side_effect=AssertionError("Network access prohibited"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(lambda: native.close_components(self.built))
        self.config = json.loads((ROOT / "comparison/config.json").read_text(encoding="utf-8"))
        self.config["model"] = "test-fixture"
        self.native_config = native.prepare(self.config, ROOT, self.trace)
        logging.getLogger().setLevel(logging.WARNING)
        self.built, self.observer = native.components(self.native_config, self.trace)

    def tearDown(self):
        os.chdir(self.cwd)
        self.network.stop()
        self.trace.close()
        native.close_components(self.built)

    def test_complete_graph_reconstruction_and_scoring_without_backend(self):
        path = Path(self.temp.name) / "water.txt"
        path.write_text(TEXT, encoding="utf-8")
        native_chunks, chunks = native.read_chunks(self.built, path, TEXT, self.trace)
        replies = [
            [{"name": "sun", "category": "NaturalScience", "description": "SOURCE DESCRIPTION MUST NOT LEAK"},
             {"name": "water", "category": "NaturalScience"}],
            {}, [["sun", "heats", "water", ""]],
        ]
        with patch.object(self.built["extractor"].llm, "invoke", side_effect=copy.deepcopy(replies)), \
             patch.object(self.built["vectorizer"].vectorize_model, "vectorize",
                          side_effect=lambda texts: [[0.25] * 768 for _ in texts]):
            snapshots = native.construct(self.built, self.observer, native_chunks, chunks, self.trace)
        graph, issues = graph_projection(snapshots, chunks, TEXT, "fixture", self.trace)
        self.assertEqual([], issues)
        context = reconstruction_context(graph, chunks[0]["id"])
        self.assertEqual(1, len(context["relations"]))
        self.assertEqual("heats", context["relations"][0]["relation"])
        self.assertNotIn("SOURCE DESCRIPTION", json.dumps(context))
        evaluation = evaluate(chunks, graph, FixtureEvaluator(), self.trace)
        self.assertEqual("completed", evaluation["status"])
        self.assertEqual(100, evaluation["final_score"])
        self.assertTrue((self.trace.directory / "artifacts/kag/writes/graph_00001.json").exists())
        self.assertTrue(any(n["properties"].get("_name_vector") for n in snapshots[0]["graph"]["resultNodes"]))
        events = [json.loads(line) for line in (self.trace.directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(list(range(1, len(events) + 1)), [row["sequence"] for row in events])
        self.assertTrue(any(row["event"] == "graph.snapshot_written" for row in events))

    def test_entire_simplified_input_covered_in_order(self):
        path = ROOT / self.config["input"]
        text = path.read_text(encoding="utf-8-sig")
        _, chunks = native.read_chunks(self.built, path, text, self.trace)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(text.split(), " ".join(chunk["text"] for chunk in chunks).split())
        for chunk in chunks:
            self.assertEqual(chunk["text"], text[chunk["start"]:chunk["end"]])

    def test_schema_binding_is_restored(self):
        from knext.schema.client import SchemaClient
        from kag.builder.component.extractor import knowledge_unit_extractor
        self.assertIs(SchemaClient, knowledge_unit_extractor.SchemaClient)
        self.assertIn("KnowledgeUnit", self.built["extractor"].schema)
        self.assertIn("NaturalScience", self.built["extractor"].schema)
        self.assertIsNone(self.built["post_processor"]._search_client)

    def test_writer_failure_propagates(self):
        from kag.builder.model.sub_graph import SubGraph
        graph = SubGraph([], [])
        graph.add_node("water", "water", "Others")
        with patch.object(self.trace, "save", side_effect=OSError("Disk full")):
            with self.assertRaises(OSError):
                native.invoke(self.built["writer"], graph, "writer", self.trace, "chunk_001")

    def test_rejects_core_entity_object_that_crashed_live_kag(self):
        from comparison.local_generation import validate_parsed
        with self.assertRaises(ValueError):
            validate_parsed("knowledge_units", {"Heat": {
                "content": TEXT, "knowledgetype": "Factual Knowledge",
                "core_entities": {"Sun": "Star", "Water": "Substance"}}})
        validate_parsed("knowledge_units", {"Heat": {
            "content": TEXT, "knowledgetype": "Factual Knowledge", "core_entities": "Sun, Water"}})

    def test_native_prompts_parsers_and_transport_format(self):
        from unittest.mock import Mock
        from ollama import ChatResponse
        from comparison.observation import Observer
        from comparison.local_generation import SCHEMAS
        extractor = self.built["extractor"]
        response = {"Heating": {"Content": TEXT, "Knowledge Type": "Factual Knowledge",
                    "Domain Ontology": "Physics -> Heat", "Core Entities": "Sun, Water",
                    "Related Query": [], "Extended Knowledge Points": []}}
        client = Mock()
        client.chat.return_value = ChatResponse(model="fixture", message={"role": "assistant",
            "content": json.dumps(response)}, done=True, done_reason="stop", eval_count=20, prompt_eval_count=100)
        extractor.llm.client = self.observer.sync_client(client)
        result = extractor.knowledge_unit_extra(TEXT, [])
        self.assertEqual("Sun, Water", result["Heating"]["core_entities"])
        arguments = client.chat.call_args.kwargs
        self.assertEqual(SCHEMAS["knowledge_units"], arguments["format"])
        self.assertFalse(arguments["think"])
        self.assertEqual(8192, arguments["options"]["num_ctx"])
        self.assertEqual(extractor.kn_prompt.build_prompt({"input": TEXT, "named_entities": []}),
                         arguments["messages"][1]["content"])

    def test_embedding_batches_share_a_live_event_loop(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        vectorizer = self.built["vectorizer"].vectorize_model
        # Windows creates a loopback socket pair when an event loop starts.
        # Permit only loop initialization, then block connections during embeddings.
        self.network.stop()
        try:
            vectorizer._local_runner.get_loop()
        finally:
            self.network.start()
        loops = []

        async def embedding(**kwargs):
            loops.append(asyncio.get_running_loop())
            self.assertFalse(loops[0].is_closed())
            self.assertIs(loops[0], loops[-1])
            return SimpleNamespace(embedding=[0.25] * 768)

        with patch.object(vectorizer.aclient, "embeddings", new=AsyncMock(side_effect=embedding)):
            self.assertEqual([[0.25] * 768], vectorizer.vectorize(["water"]))
            self.assertEqual([[0.25] * 768], vectorizer.vectorize(["sun"]))
        self.assertEqual(2, len(loops))


if __name__ == "__main__":
    unittest.main()
