"""No live inference: regressions for the endpoint-cap failure and local recovery."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ollama import ChatResponse

from pipeline.cli import main
from pipeline.extraction import Extraction, EndpointRepair, complete_endpoint, Endpoint, extract
from pipeline.ingest import split_document
from pipeline.models import Models, ModelResponseError, OutputLimitError
from pipeline.registry import ConceptRegistry, RelationRegistry

from pipeline.trace import Trace


def concept(name, **changes):
    return dict(dict(name=name, definition="The concept " + name, kind="entity"), **changes)


def extraction(text, relations=None, concepts=None):
    return dict(unit_kind="core_statement", concepts=concepts or [],
                claims=[dict(text=text, evidence=text)], relations=relations or [], confidence=.9, reason="Fixture")


class FixtureModel:
    def __init__(self, respond):
        self.respond, self.requests = respond, []

    def ask(self, role, instruction, payload, schema, entity_id, validator=None):
        self.requests.append(dict(role=role, payload=payload, entity_id=entity_id))
        if role == "concept_resolver":
            value = dict(key=None, exact_meaning=False, same_direction=False, reason="Distinct concept")
        else:
            value = self.respond(role, payload)
        result = schema.model_validate(value)
        if validator:
            validator(result)
        return result


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "trace", "test")
        self.addCleanup(self.trace.close)

    def run_extraction(self, text, respond, max_words=10000):
        model = FixtureModel(respond)
        concepts, relations = ConceptRegistry(model, self.trace), RelationRegistry(model, self.trace)
        paragraphs, chunks = split_document(text, max_words, self.trace)
        result = extract(chunks, paragraphs, model, self.trace, concepts, relations)
        return result, model, concepts

    def relation(self, source, target, text):
        return dict(source=source, target=target, relation="associated_with",
            relation_definition=RelationRegistry(None, self.trace).entries["associated_with"]["definition"],
            evidence=text)

    def test_more_than_twelve_endpoints_without_separate_concept_list(self):
        names = ["water cycle", "ocean", "lake", "river", "soil", "living organism", "groundwater",
                 "glacier", "atmosphere", "reservoir", "evaporation", "precipitation", "runoff",
                 "process", "water"]
        text = "These concepts are related: " + ", ".join(names) + "."
        relations = [self.relation(concept(names[0]), concept(n), text) for n in names[1:]]
        result, model, concepts = self.run_extraction(text, lambda role, p: extraction(text, relations))
        self.assertEqual(result[0]["status"], "complete")
        self.assertEqual(len(result[0]["relation_proposals"]), 14)
        self.assertEqual(set(result[0]["concepts"]), set(names))
        self.assertEqual(set(concepts.entries), set(names))
        self.assertEqual(sum(r["role"] == "extractor" for r in model.requests), 1)
        self.assertTrue(all(p["source_mention"]["definition"] for p in result[0]["relation_proposals"]))
        schema = Extraction.model_json_schema()
        self.assertTrue(all("maxItems" not in schema["properties"][k] for k in ("concepts", "claims", "relations")))

    def test_required_definitions_remove_need_for_live_metadata_repairs(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            Endpoint(name="rivers", kind="entity")
        text = "Runoff is associated with rivers."
        row = self.relation(concept("runoff"), concept("rivers"), text)
        def respond(role, p):
            if role == "extractor":
                return extraction(text, [row])
            self.fail("Unexpected model call: " + role)
        result, model, concepts = self.run_extraction(text, respond)
        self.assertEqual(result[0]["status"], "complete")
        self.assertEqual(len(result[0]["relation_proposals"]), 1)
        self.assertEqual(sum(r["role"] == "extractor" for r in model.requests), 1)
        self.assertEqual(sum(r["role"] == "concept_endpoint_repair" for r in model.requests), 0)
        self.assertIn("rivers", concepts.entries)

    def test_unresolved_record_preserves_other_records_and_following_chunks(self):
        first, second = "Runoff and rivers interact.", "Water and soil interact."
        valid = self.relation(concept("runoff"), concept("rivers"), first)
        invalid = self.relation(concept("runoff"), concept("unclear"), "Invented evidence.")
        def respond(role, p):
            if role == "extractor":
                return extraction(p["CURRENT_CHUNK"], [valid, invalid] if p["CURRENT_CHUNK"] == first else [
                    self.relation(concept("water"), concept("soil"), second)])
            return dict(concept=None, reason="Intended endpoint is ambiguous")
        result, _, concepts = self.run_extraction(first + "\n\n" + second, respond)
        self.assertEqual([r["status"] for r in result], ["incomplete", "complete"])
        self.assertEqual([len(r["relation_proposals"]) for r in result], [1, 1])
        self.assertNotIn("unclear", concepts.entries)
        issues = json.loads((self.trace.directory / "artifacts/extraction_issues.json").read_text())
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["record"]["target"]["name"], "unclear")

    def test_legacy_repair_schema_failure_returns_unresolved(self):
        def respond(role, p):
            raise ModelResponseError("Repair failed schema validation")
        endpoint = Endpoint.model_construct(name="rivers", definition=None, kind="entity")
        result = complete_endpoint(endpoint, {}, "target", "Rivers flow.", FixtureModel(respond), self.trace, "legacy")
        self.assertIsNone(result)

    def test_repair_cannot_change_name_or_already_valid_meaning(self):
        for changes in ({"name": "ocean"}, {"kind": "process"}):
            original = Endpoint.model_construct(name="rivers", definition=None, kind="entity")
            def respond(role, p):
                repaired = concept("rivers", definition="Original meaning")
                repaired.update(changes)
                return dict(concept=repaired, reason="Bad repair")
            model = FixtureModel(respond)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                complete_endpoint(original, {}, "target", "Rivers flow.", model, self.trace, "repair")

    def test_truncation_splits_sentences_and_preserves_offsets_and_parent_id(self):
        text = "Runoff enters rivers.\r\nRivers reach oceans."
        def respond(role, p):
            current = p["CURRENT_CHUNK"]
            if current == text:
                raise OutputLimitError("Truncated fixture")
            return extraction(current, [self.relation(concept("runoff"), concept("rivers"), current)])
        result, model, _ = self.run_extraction(text, respond)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "complete")
        self.assertEqual("".join(u["text"] for u in result[0]["units"]), text)
        self.assertEqual(self.trace.counts["extraction.unit_split"], 1)
        self.assertEqual(sum(r["role"] == "extractor" for r in model.requests), 3)
        for row in result[0]["claims"] + result[0]["relation_proposals"]:
            self.assertEqual(text[row["evidence_start"]:row["evidence_end"]], row["evidence"])
        self.assertTrue(all(r["chunk_id"] == result[0]["chunk_id"] for r in result[0]["relation_proposals"]))

    def test_unsplittable_truncation_terminates_and_marks_incomplete(self):
        def respond(role, p):
            raise OutputLimitError("Truncated")
        result, model, _ = self.run_extraction("Water", respond)
        self.assertEqual(result[0]["status"], "incomplete")
        self.assertEqual(len(model.requests), 1)
        self.assertIn("no smaller", result[0]["issues"][0]["reason"])

    def test_single_long_sentence_splits_at_words_with_finite_progress(self):
        def respond(role, p):
            if len(p["CURRENT_CHUNK"].split()) > 1:
                raise OutputLimitError("Truncated")
            return extraction(p["CURRENT_CHUNK"])
        result, _, _ = self.run_extraction("one two three four", respond)
        self.assertEqual(result[0]["status"], "complete")
        self.assertEqual("".join(u["text"] for u in result[0]["units"]), "one two three four")
        self.assertEqual(len(result[0]["units"]), 4)

    def test_service_error_is_not_silently_downgraded_to_incomplete_record(self):
        def respond(role, p):
            raise RuntimeError("Ollama unavailable")
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            self.run_extraction("Runoff flows.", respond)

    def test_models_exposes_output_limit_once_without_retry_or_validation(self):
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(
                message=dict(role="assistant", content=json.dumps(extraction("Water flows."))),
                done=True, done_reason="length")
            model = Models(self.trace, "fixture", "fixture", "http://localhost")
            with self.assertRaises(OutputLimitError):
                model.ask("extractor", "fixture", {}, Extraction, "chunk_001")
            self.assertEqual(client.return_value.chat.call_count, 1)
            self.assertEqual(model.retries, 0)
            self.assertEqual(self.trace.counts["validation.completed"], 0)

    def test_incomplete_mocked_workflow_produces_report_and_nonzero_exit(self):
        class FakeModels:
            calls = retries = prompt_tokens = output_tokens = cache_hits = 0
            details = {}
            def __init__(self, trace, model, embedding_model, host, **kwargs):
                self.model, self.embedding_model = model, embedding_model
            def preflight(self):
                pass
            def ask(self, role, instruction, payload, schema, entity, validator=None):
                if role == "segment_summarizer":
                    value = dict(summary="Water", topics=["water"])
                elif role == "chapter_summarizer":
                    value = dict(overview="Water", topics=["water"])
                elif role == "extractor":
                    raise ModelResponseError("Unusable fixture output")
                else:
                    raise AssertionError("No model review/evaluation should run without extracted content: " + role)
                return schema.model_validate(value)
        source = Path(self.temp.name) / "input.txt"
        source.write_text("Water flows.", encoding="utf-8")
        out = Path(self.temp.name) / "partial"
        with patch("pipeline.models.Models", FakeModels):
            code = main(["--input", str(source), "--output-root", str(out), "--no-open"])
        self.assertEqual(code, 2)
        run = next((out / "custom").iterdir())
        manifest = json.loads((run / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "completed_with_issues")
        self.assertEqual(manifest["incomplete_extraction_chunks"], ["chunk_001"])
        self.assertIn("Incomplete extraction", (run / "index.html").read_text(encoding="utf-8"))
        evaluation = json.loads((run / "artifacts/evaluation.json").read_text())
        self.assertIsNone(evaluation["summary"]["semantic_cosine"]["mean"])


if __name__ == "__main__":
    unittest.main()
