"""Offline regressions for item recovery, restricted background, and evidence spans."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ollama import ChatResponse
from pydantic import ValidationError

from pipeline.batching import ask_keyed
from pipeline.debate import BACKGROUND_RELATIONS, Expansion, Novelty, Proposal, debate, review_background_many
from pipeline.evaluation import Reconstruction
from pipeline.extraction import extract
from pipeline.health import finish_item
from pipeline.ingest import split_document
from pipeline.models import Models, ModelResponseError
from pipeline.registry import RelationRegistry, FactIndex
from pipeline.trace import Trace


class ItemRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "run", "fixture")
        self.addCleanup(self.trace.close)

    def test_background_schema_allows_dynamic_relations(self):
        value = dict(target=dict(name="cell", definition="A living unit", kind="entity"),
            relation="is_a", relation_definition="A subtype", confidence=.9, reason="Background")
        for relation in BACKGROUND_RELATIONS:
            Proposal.model_validate(dict(value, relation=relation))
        for relation in ("causes", "enables", "affects_rate_of", "acts_on"):
            with self.subTest(relation=relation):
                Proposal.model_validate(dict(value, relation=relation))
        with self.assertRaises(ValidationError):
            Proposal.model_validate(dict(value, relation=""))
        self.assertNotIn("event_objects", Proposal.model_json_schema()["properties"])

    def test_causal_relation_does_not_require_invented_companion(self):
        from pipeline.extraction import Extraction, validate_events
        from pipeline.events import kind_error
        value = Extraction.model_validate(dict(unit_kind="core_statement", concepts=[], claims=[],
            confidence=.9, reason="Explicit cause", relations=[dict(
                source=dict(name="heating", definition="Supplying heat", kind="process"),
                relation="causes", relation_definition="SOURCE produces TARGET",
                target=dict(name="expansion", definition="Increase in volume", kind="process"),
                evidence="Heating causes expansion.")]))
        validate_events(value)
        self.assertIsNone(kind_error("causes", "process", "process"))
        self.assertIsNotNone(kind_error("causes", "process", "substance"))

    def test_background_proposal_can_name_an_incoming_source(self):
        value = Proposal.model_validate(dict(
            source=dict(name="vegetation", definition="Plant cover", kind="entity"),
            target=dict(name="infiltration", definition="Water entry into soil", kind="process"),
            relation="affects_rate_of", relation_definition="SOURCE influences the rate of TARGET",
            confidence=.9, reason="Incoming relation to infiltration seed"))
        self.assertEqual(value.source.name, "vegetation")
        self.assertEqual(value.target.name, "infiltration")

    def test_obsolete_field_is_removed_and_logged_at_any_depth(self):
        value = dict(proposals=[dict(target=dict(name="cell", definition="Living unit", kind="entity",
            event_objects=["unused"]), relation="is_a", relation_definition="A subtype",
            confidence=.9, reason="Background", event_objects=["unused"])],
            reason="One proposal", event_objects=[])
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(message=dict(role="assistant", content=json.dumps(value)))
            model = Models(self.trace, "fixture", "fixture", "http://localhost")
            answer = model.ask("proposer", "fixture", {}, Expansion, "seed")
        self.assertEqual(len(answer.proposals), 1)
        self.assertEqual(self.trace.counts["model.unused_field_dropped"], 3)
        self.assertEqual(model.retries, 0)

    def test_two_retries_then_success_count_as_one_healthy_item(self):
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.side_effect = [
                ChatResponse(message=dict(role="assistant", content="invalid")),
                ChatResponse(message=dict(role="assistant", content="invalid")),
                ChatResponse(message=dict(role="assistant", content='{"text":"Valid", "reason":"Fixture"}'))]
            model = Models(self.trace, "fixture", "fixture", "http://localhost")
            model.ask("reconstructor", "fixture", {}, Reconstruction, "chunk")
            finish_item(self.trace, "evaluation", "chunk")
            finish_item(self.trace, "evaluation", "chunk")
        self.assertEqual(model.retries, 2)
        self.assertEqual(len(self.trace.health.history["evaluation"]), 1)
        self.assertTrue(self.trace.health.history["evaluation"][0]["passed"])
        self.assertNotIn("model_response:reconstructor", self.trace.health.history)

    def test_failed_batch_isolates_only_bad_item(self):
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            if any(item["id"] == "bad" for item in payload["items"]):
                raise ModelResponseError("Retries exhausted")
            return schema.model_validate({item["id"]: dict(status="new", evidence_ids=[], reason="Checked")
                                          for item in payload["items"]})
        errors = {}
        result = ask_keyed(SimpleNamespace(ask=ask), "novelty_checker", "Check",
            [dict(id=name) for name in ("first", "bad", "last")], Novelty, "batch",
            on_error=lambda item, exc: errors.update({item["id"]: str(exc)}))
        self.assertEqual(set(result), {"first", "last"})
        self.assertEqual(set(errors), {"bad"})

    def test_failed_proposer_seed_does_not_stop_next_seed(self):
        calls = []
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            calls.append(entity_id)
            self.assertEqual(set(payload["available_relations"]), BACKGROUND_RELATIONS)
            if entity_id == "seed_1":
                raise ModelResponseError("Retries exhausted")
            return schema.model_validate(dict(proposals=[], reason="No useful addition"))
        model = SimpleNamespace(ask=ask)
        relations = RelationRegistry(model, self.trace)
        seeds = [dict(id=f"seed_{i}", concept=name, definition=name, kind="entity",
            chunk_id="chunk", paragraph_id="p") for i, name in enumerate(("aquifer", "soil"), 1)]
        result = debate(seeds, [dict(id="chunk", text="Source")], dict(overview="Water", topics=["water"]),
            SimpleNamespace(entries={}, chapter_names=[]), relations, FactIndex(relations), model, self.trace)
        self.assertEqual(calls, ["seed_1", "seed_2"])
        self.assertEqual(result["transcripts"][0]["status"], "unresolved")
        self.assertEqual(result["transcripts"][1]["proposal"]["proposals"], [])
        self.assertEqual([r["passed"] for r in self.trace.health.history["background_proposal"]], [False, True])
        self.assertTrue((self.trace.directory / "artifacts/unresolved_items.json").exists())

    def test_unreachable_service_remains_fatal(self):
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.side_effect = ConnectionError("Unreachable")
            model = Models(self.trace, "fixture", "fixture", "http://localhost")
            with self.assertRaisesRegex(RuntimeError, "Model service failed"):
                model.ask("proposer", "fixture", {}, Expansion, "seed")
            self.assertEqual(client.return_value.chat.call_count, 1)

    def test_bad_critic_item_does_not_discard_valid_batch_peer(self):
        from test_semantics import FixtureModel, reviewer
        def respond(role, payload):
            if role == "critic" and any(item["id"] == "bad" for item in payload["items"]):
                raise ModelResponseError("Invalid critic response after retries")
            return reviewer(role, payload)
        model = FixtureModel(respond)
        rows = [dict(id=name, source="neuron", target="cell", relation="is_a",
            relation_definition="SOURCE is a kind of TARGET", origin="background",
            reason="Useful background", chunk_id="chunk", accepted=False) for name in ("good", "bad")]
        concepts = SimpleNamespace(entries={name: dict(name=name, definition=name, kind="entity")
                                            for name in ("neuron", "cell")}, chapter_names=[])
        review_background_many(rows, {"chunk": dict(text="Neurons transmit signals.")},
            dict(overview="Neurons", topics=["neurons"]), concepts, model, self.trace)
        self.assertTrue(rows[0]["accepted"])
        self.assertFalse(rows[1]["accepted"])
        self.assertEqual(rows[1]["review_status"], "unresolved")
        later = [payload for role, _, payload in model.requests if role in ("proposer_rebuttal", "judge")]
        self.assertTrue(all([item["id"] for item in payload["items"]] == ["good"] for payload in later))

    def test_two_sentence_evidence_crosses_chunk_boundary_with_exact_offsets(self):
        text = "Water moves deeper. This movement is percolation. Clouds are visible."
        quote = "Water moves deeper. This movement is percolation."
        paragraphs, chunks = split_document(text, 4, self.trace)
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            current = payload["CURRENT_CHUNK"]
            claims = [dict(text=current, evidence=current)]
            if current == "Water moves deeper.":
                self.assertIn(quote, payload["EVIDENCE_CONTEXT"])
                claims += [dict(text="This movement is percolation.", evidence=quote),
                           dict(text="Clouds are visible.", evidence="Clouds are visible.")]
            value = schema.model_validate(dict(unit_kind="core_statement", concepts=[],
                claims=claims, relations=[], confidence=.9, reason="Fixture"))
            if validator:
                validator(value)
            return value
        model = SimpleNamespace(ask=ask)
        rows = extract(chunks, paragraphs, model, self.trace, SimpleNamespace(entries={}), RelationRegistry(model, self.trace))
        evidence = next(c for c in rows[0]["claims"] if c["evidence"] == quote)
        self.assertEqual(text[evidence["evidence_start"]:evidence["evidence_end"]], quote)
        self.assertGreater(evidence["evidence_end"], chunks[0]["end"])
        self.assertFalse(any(c["evidence"] == "Clouds are visible." for c in rows[0]["claims"]))


if __name__ == "__main__":
    unittest.main()
