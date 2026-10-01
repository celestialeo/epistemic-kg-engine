"""Saved real answers and behavior regressions; never runs live chapter inference."""
import json
from pathlib import Path
import tempfile
from typing import get_args
import unittest
from unittest.mock import patch
from ollama import ChatResponse
from pydantic import ValidationError

from pipeline.compatibility import legacy_endpoint
from pipeline.extraction import Extraction, Endpoint, complete_endpoint
from pipeline.health import HealthFailure, HealthMonitor, finish_item
from pipeline.registry import Concept, ConceptKind, ConceptRegistry, RelationRegistry, FactIndex
from pipeline.models import Models, ModelResponseError, OutputLimitError
from pipeline.batching import ask_keyed
from pipeline.trace import Trace
from pipeline.debate import DocumentVerdict, Novelty, check_novelty_many, review_background_many, review_extractions
from test_semantics import FixtureModel, reviewer, concept


class DemoReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "run", "regression")
        self.addCleanup(self.trace.close)

    def test_live_schemas_share_enum_and_preserve_specific_detail(self):
        for schema in (Concept, Endpoint):
            definition = schema.model_json_schema()
            self.assertEqual(set(definition["properties"]["kind"]["enum"]), set(get_args(ConceptKind)))
            with self.assertRaises(ValidationError):
                schema.model_validate(dict(name="neuron", definition="An excitable cell", kind="cell_type"))
            result = schema.model_validate(dict(name="neuron", definition="An excitable cell",
                                                 kind="entity", kind_detail="cell_type"))
            self.assertEqual(result.kind_detail, "cell_type")

    def test_document_review_cannot_mark_quote_evidence_not_applicable(self):
        verdict = reviewer("extraction_reviewer", dict(candidate=dict(id="c"), quote="Evidence"))["c"]
        verdict["evidence_status"] = "not_applicable"
        with self.assertRaises(ValidationError):
            DocumentVerdict.model_validate(verdict)
        verdict["evidence_status"] = "unsupported"
        self.assertEqual(DocumentVerdict.model_validate(verdict).evidence_status, "unsupported")

    def test_all_real_previous_extractions_replay_without_kind_repairs(self):
        saved = json.loads((Path(__file__).parent / "fixtures/previous_extractions.json").read_text())
        self.assertEqual(len(saved["responses"]), 34)
        seen, migrated = 0, 0
        model = FixtureModel(lambda role, payload: self.fail("Replay must not need a kind repair"))
        for response in saved["responses"]:
            answer = response["answer"]
            original = answer["concepts"] + [r[s] for r in answer["relations"] for s in ("source", "target")]
            for raw in original:
                seen += 1
                value = legacy_endpoint(raw)
                if raw["kind"] not in get_args(ConceptKind):
                    migrated += 1
                    self.assertEqual(value["kind"], "other")
                    self.assertEqual(value["kind_detail"], raw["kind"])
                self.assertEqual(value["definition"], raw["definition"])
                endpoint = Endpoint.model_validate(value)
                result = complete_endpoint(endpoint, {}, "source", "", model, self.trace, response["entity_id"])
                self.assertIsNotNone(result)
            converted = dict(answer, concepts=[legacy_endpoint(c) for c in answer["concepts"]],
                relations=[dict(r, source=legacy_endpoint(r["source"]), target=legacy_endpoint(r["target"]))
                           for r in answer["relations"]])
            Extraction.model_validate(converted)
        self.assertGreater(seen, 400)
        self.assertGreater(migrated, 200)
        self.assertEqual(self.trace.counts["extraction.endpoint_repair_requested"], 0)

    def test_health_stops_majority_failure_and_names_step(self):
        monitor = HealthMonitor(self.trace)
        for valid in (False, True, False, True):
            monitor.record("endpoint_metadata_repair", valid, "cannot resolve")
        with self.assertRaisesRegex(HealthFailure, "endpoint_metadata_repair failed 3/5"):
            monitor.record("endpoint_metadata_repair", False, "cannot resolve")
        detail = json.loads((self.trace.directory / "artifacts/health.json").read_text())
        self.assertEqual(len(detail["recent"]), 5)

    def test_successful_identical_responses_are_revalidated_from_memory(self):
        from pipeline.evaluation import Reconstruction
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(
                message=dict(role="assistant", content='{"text":"same","reason":"same"}'))
            model = Models(self.trace, "fixture", "fixture", "http://localhost")
            validations = []
            for _ in range(2):
                model.ask("test", "same instruction", {}, Reconstruction, "same",
                          validator=lambda r: validations.append(r.text))
            self.assertEqual(client.return_value.chat.call_count, 1)
            self.assertEqual(validations, ["same", "same"])
            self.assertEqual(model.cache_hits, 1)

    def test_failed_responses_are_not_reused_and_majority_failure_stops(self):
        from pipeline.evaluation import Reconstruction
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(message=dict(role="assistant", content="invalid"))
            model = Models(self.trace, "fixture", "fixture", "http://localhost")
            for index in range(5):
                with self.assertRaises(ModelResponseError):
                    model.ask("test", "same", {}, Reconstruction, str(index))
                self.assertFalse(model.cache)
                if index < 4:
                    finish_item(self.trace, "test_items", str(index), "Invalid response")
                else:
                    with self.assertRaisesRegex(HealthFailure, "test_items failed 5/5"):
                        finish_item(self.trace, "test_items", str(index), "Invalid response")
            self.assertEqual(client.return_value.chat.call_count, 15)

    def test_unrelated_concepts_need_no_matching_calls_but_plural_still_does(self):
        def respond(role, p):
            if role == "concept_resolver":
                return dict(key="axon", exact_meaning=True, same_direction=True, reason="Plural")
            return dict(exact_meaning=True, same_direction=True, compatible_types=True, reason="Same meaning")
        model = FixtureModel(respond)
        registry = ConceptRegistry(model, self.trace)
        registry.resolve(concept("axon", "Output process of a neuron"), "", "one")
        registry.resolve(concept("lake", "Standing freshwater body"), "", "two")
        self.assertEqual(model.requests, [])
        canonical = registry.resolve(concept("axons", "Neuronal output processes"), "Neural chapter", "three")
        self.assertEqual(canonical, "axon")
        self.assertEqual([r[0] for r in model.requests], ["concept_resolver", "concept_match_verifier"])
        registry.resolve(concept("axons", "Neuronal output processes"), "Neural chapter", "four")
        self.assertEqual(len(model.requests), 2)

    def test_batched_novelty_preserves_full_chapter_coverage(self):
        def respond(role, p):
            return {item["id"]: dict(status="new", evidence_ids=[], reason="Different facts") for item in p["items"]}
        model = FixtureModel(respond)
        relations = RelationRegistry(model, self.trace)
        rows = [dict(id=f"c_{i}", source=f"s_{i}", target="x", relation="associated_with",
                relation_definition=relations.entries["associated_with"]["definition"], origin="background") for i in range(3)]
        chunks = [dict(id=f"chunk_{i}", text="Source text") for i in range(15)]
        results = check_novelty_many(rows, chunks, FactIndex(relations), model, self.trace)
        self.assertEqual(len(model.requests), 3)  # Three reference batches, not nine per-candidate calls.
        for result in results.values():
            self.assertEqual(result["checked_references"], [c["id"] for c in chunks])

    def test_batched_background_keeps_all_three_roles_and_blind_judge(self):
        model = FixtureModel(reviewer)
        concepts = ConceptRegistry(model, self.trace)
        concepts.entries = {n: concept(n) for n in ("a", "b", "c")}
        rows = [dict(id=f"c_{i}", source="a", target=n, relation="associated_with",
                relation_definition="Associated without causality", origin="background", reason="Proposal",
                chunk_id="chunk") for i, n in enumerate(("b", "c"))]
        review_background_many(rows, {"chunk":dict(text="Related concepts.")},
            dict(overview="Concepts", topics=["concepts"]), concepts, model, self.trace)
        self.assertEqual([r[0] for r in model.requests], ["critic", "proposer_rebuttal", "judge"])
        payload = model.requests[-1][2]
        self.assertNotIn("position", json.dumps(payload))
        self.assertNotIn("domain_relevance", json.dumps(payload))
        self.assertTrue(all(r["accepted"] for r in rows))

    def test_single_extraction_reviewer_cannot_override_failed_gates_in_batch(self):
        def respond(role, payload):
            judgments = reviewer(role, payload)
            # An inconsistent model says accept despite unsupported evidence or
            # a reversed relation. Neither may enter the graph's fact index.
            judgments["c_1"]["evidence_status"] = "unsupported"
            judgments["c_2"]["direction_valid"] = False
            return judgments
        model = FixtureModel(respond)
        concepts = ConceptRegistry(model, self.trace)
        concepts.entries = {n: concept(n) for n in ("neuron", "axon", "membrane", "dendrite")}
        relations = RelationRegistry(model, self.trace)
        facts = FactIndex(relations)
        rows = [dict(id=f"c_{i}", source="neuron", target=name, relation="has_part",
            relation_definition=relations.entries["has_part"]["definition"], origin="document",
            reason="Extracted", chunk_id="chunk", evidence="A neuron has an axon.",
            evidence_start=0, evidence_end=22) for i, name in enumerate(("axon", "membrane", "dendrite"))]
        extractions = [dict(chunk_id="chunk", relations=[], relation_proposals=rows)]
        decisions = review_extractions(extractions, [dict(id="chunk", text="A neuron has an axon.")],
            dict(overview="Neurons", topics=["neurons"]), concepts, facts, model, self.trace)
        self.assertEqual([r[0] for r in model.requests], ["extraction_reviewer"])
        self.assertEqual([r["accepted"] for r in decisions], [True, False, False])
        self.assertEqual([r["id"] for r in facts.rows], ["c_0"])
        self.assertEqual(self.trace.counts["debate.verdict_conflict"], 2)

    def test_truncated_batch_is_split_without_dropping_candidates(self):
        def respond(role, payload):
            if len(payload["items"]) > 2:
                raise OutputLimitError("Simulated output exhaustion")
            return {item["id"]: dict(status="new", evidence_ids=[], reason="Checked")
                    for item in payload["items"]}
        model = FixtureModel(respond)
        items = [dict(id=f"c_{i}") for i in range(5)]
        validated = []
        result = ask_keyed(model, "novelty_checker", "Check all", items, Novelty, "batch",
            validate=lambda item, verdict: validated.append(item["id"]))
        self.assertEqual(set(result), {item["id"] for item in items})
        self.assertEqual(sorted(validated), sorted(result))
        self.assertEqual([len(p["items"]) for _, _, p in model.requests], [4, 2, 2, 1])


if __name__ == "__main__":
    unittest.main()
