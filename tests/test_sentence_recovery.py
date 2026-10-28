"""Sentence context, reference and quote-retry regressions without live inference."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.extraction import INSTRUCTION, Extraction, Endpoint, reference_name, resolve_endpoint
from pipeline.health import HealthFailure
from pipeline.models import ModelResponseError, OutputLimitError
from pipeline.registry import ConceptRegistry, RelationRegistry
from pipeline.trace import Trace
import test_extraction_recovery as fixtures


class SentenceRecoveryTests(unittest.TestCase):
    run_extraction = fixtures.RecoveryTests.run_extraction
    relation = fixtures.RecoveryTests.relation

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "run", "fixture")
        self.addCleanup(self.trace.close)

    def test_payload_contains_only_current_and_previous_sentence(self):
        sentences = ["ConceptA interacts with ConceptB.", "ProcessP occurs nearby.",
                     "ConceptC contains ConceptD.", "PropertyQ changes slowly."]
        _, model, _ = self.run_extraction(" ".join(sentences[:3]) + "\n\n" + sentences[3],
            lambda role, p: fixtures.extraction(p["CURRENT_SENTENCE"]))
        requests = [r["payload"] for r in model.requests if r["role"] == "extractor"]
        for index, payload in enumerate(requests):
            self.assertEqual(set(payload), {"CURRENT_SENTENCE", "PREVIOUS_SENTENCE", "available_relations"})
            self.assertEqual(payload["CURRENT_SENTENCE"].strip(), sentences[index])
            self.assertEqual(payload["PREVIOUS_SENTENCE"], sentences[index - 1] if index else "")

    def test_next_sentence_is_included_for_an_adjacent_name(self):
        first = "ConceptA has openings."
        naming = "These openings are called ConceptB."
        last = "ConceptC contains ConceptD."
        _, model, _ = self.run_extraction(first + " " + naming + " " + last,
            lambda role, p: fixtures.extraction(p["CURRENT_SENTENCE"]), max_words=5)
        requests = [r["payload"] for r in model.requests if r["role"] == "extractor"]
        self.assertEqual(requests[0]["NEXT_SENTENCE"], naming)
        self.assertNotIn("NEXT_SENTENCE", requests[1])
        self.assertEqual(requests[1]["PREVIOUS_SENTENCE"], first)
        self.assertEqual(requests[2]["PREVIOUS_SENTENCE"], naming)

    def test_extraction_examples_are_abstract_including_schema_descriptions(self):
        prompt = INSTRUCTION + json.dumps(Extraction.model_json_schema())
        for domain_term in ("water", "transpiration", "evaporation", "infiltration", "soil", "cell_type"):
            self.assertNotIn(domain_term, prompt.lower())
        for placeholder in ("ConceptA", "ConceptB", "ProcessP", "PropertyQ"):
            self.assertIn(placeholder, INSTRUCTION)
        self.assertIn("Extract only from CURRENT_SENTENCE", INSTRUCTION)

    def test_one_retry_repairs_claim_and_relation_preserving_valid_records(self):
        text = "ConceptA interacts with ConceptB and ConceptC."
        good = self.relation(fixtures.concept("ConceptA"), fixtures.concept("ConceptB"), text)
        bad = self.relation(fixtures.concept("ConceptA"), fixtures.concept("ConceptC"), "Invented quote.")

        def respond(role, payload):
            if role == "extractor":
                value = fixtures.extraction(text, [good, bad])
                value["claims"].append(dict(text="Another assertion", evidence="Abbreviated...quote"))
                return value
            self.assertEqual(role, "extractor_quote_repair")
            failed = payload["failed_records"]
            self.assertEqual([(f["collection"], f["index"]) for f in failed], [("claims", 1), ("relations", 1)])
            self.assertTrue(all("not an exact continuous" in f["reason"] for f in failed))
            return dict(records=[dict(f, record=dict(f["record"], evidence=text), reason="Copied exact source")
                                 for f in reversed(failed)])

        rows, model, _ = self.run_extraction(text, respond)
        row = rows[0]
        self.assertEqual(row["status"], "complete")
        self.assertEqual(len(row["claims"]), 2)
        self.assertEqual(len(row["relation_proposals"]), 2)
        self.assertEqual(row["relation_proposals"][0]["target"], "conceptb")
        self.assertEqual(row["relation_proposals"][1]["target"], "conceptc")
        self.assertEqual(row["issues"], [])
        self.assertEqual([r["role"] for r in model.requests if r["role"].startswith("extractor")],
                         ["extractor", "extractor_quote_repair"])
        for record in row["claims"] + row["relation_proposals"]:
            self.assertEqual(text[record["evidence_start"]:record["evidence_end"]], record["evidence"])
        self.assertEqual(len(self.trace.health.history["extraction_record"]), 4)
        self.assertTrue(all(r["passed"] for r in self.trace.health.history["extraction_record"]))
        self.assertFalse(getattr(self.trace, "unresolved_items", []))

    def test_retry_still_rejects_neighbor_only_quote_and_continues(self):
        before, current, after = "ConceptA occurs.", "ConceptB occurs.", "ConceptC occurs."

        def respond(role, payload):
            if role == "extractor_quote_repair":
                self.assertIn("does not overlap CURRENT_SENTENCE", payload["failed_records"][0]["reason"])
                return dict(records=[dict(f, reason="Unchanged quote") for f in payload["failed_records"]])
            text = payload["CURRENT_SENTENCE"].strip()
            value = fixtures.extraction(text)
            if text == current:
                value["claims"].append(dict(text=before, evidence=before))
            return value

        rows, model, _ = self.run_extraction(" ".join((before, current, after)), respond, max_words=2)
        self.assertEqual([r["status"] for r in rows], ["complete", "incomplete", "complete"])
        self.assertEqual([len(r["claims"]) for r in rows], [1, 1, 1])
        self.assertIn("still invalid after one quote retry", rows[1]["issues"][0]["reason"])
        self.assertEqual(sum(r["role"] == "extractor_quote_repair" for r in model.requests), 1)
        self.assertEqual(len(self.trace.unresolved_items), 1)

    def test_failed_quote_retry_retains_good_records_and_original_reason(self):
        text = "ConceptA interacts with ConceptB."
        bad = self.relation(fixtures.concept("ConceptA"), fixtures.concept("ConceptB"), "Wrong quote")

        def respond(role, payload):
            if role == "extractor_quote_repair":
                raise ModelResponseError("Malformed repair after schema retries")
            return fixtures.extraction(payload["CURRENT_SENTENCE"], [bad])

        rows, _, _ = self.run_extraction(text, respond)
        self.assertEqual(len(rows[0]["claims"]), 1)
        self.assertEqual(rows[0]["relation_proposals"], [])
        self.assertIn("not an exact continuous", rows[0]["issues"][0]["reason"])
        self.assertIn("Malformed repair", rows[0]["issues"][0]["reason"])
        self.assertEqual([r["passed"] for r in self.trace.health.history["extraction_record"]], [True, False])

    def test_output_limit_during_quote_retry_does_not_repeat_or_split(self):
        def respond(role, payload):
            if role == "extractor_quote_repair":
                raise OutputLimitError("Truncated repair")
            return fixtures.extraction("Wrong quote")

        rows, model, _ = self.run_extraction("ConceptA occurs.", respond)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(rows[0]["claims"], [])
        self.assertEqual(len(rows[0]["issues"]), 1)
        self.assertEqual(len(self.trace.unresolved_items), 1)
        self.assertEqual(self.trace.counts["extraction.unit_split"], 0)

    def test_system_failure_during_quote_retry_is_fatal(self):
        def respond(role, payload):
            if role == "extractor_quote_repair":
                raise RuntimeError("Service unavailable")
            return fixtures.extraction("Wrong quote")
        with self.assertRaisesRegex(RuntimeError, "Service unavailable"):
            self.run_extraction("ConceptA occurs.", respond)

    def test_incomplete_chunks_with_minority_bad_records_do_not_stop(self):
        text = "ConceptA interacts with ConceptB."
        good = self.relation(fixtures.concept("ConceptA"), fixtures.concept("ConceptB"), text)
        bad = dict(good, evidence="Wrong quote")

        def respond(role, payload):
            if role == "extractor_quote_repair":
                return dict(records=[dict(f, record=None, reason="Unsupported assertion")
                                     for f in payload["failed_records"]])
            return fixtures.extraction(text, [good, bad])

        rows, _, _ = self.run_extraction("\n\n".join([text] * 6), respond)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["status"] == "incomplete" for r in rows))
        self.assertEqual(len(self.trace.unresolved_items), 6)
        self.assertEqual(sum(step == "extraction_record" for step, _ in self.trace.completed_items), 18)
        self.assertNotIn("extraction_chunk", self.trace.health.history)
        self.assertFalse((self.trace.directory / "artifacts/health.json").exists())

    def test_majority_of_final_records_failing_stops_after_persisting_results(self):
        def respond(role, payload):
            if role == "extractor_quote_repair":
                return dict(records=[dict(f, reason="Still wrong") for f in payload["failed_records"]])
            value = fixtures.extraction(payload["CURRENT_SENTENCE"])
            value["claims"] += [dict(text=f"Claim {i}", evidence=f"Wrong quote {i}") for i in range(5)]
            return value

        with self.assertRaisesRegex(HealthFailure, "extraction_record failed 4/5"):
            self.run_extraction("ConceptA occurs.", respond)
        issues = json.loads((self.trace.directory / "artifacts/extraction_issues.json").read_text())
        saved = json.loads((self.trace.directory / "artifacts/extraction_proposals.json").read_text())
        self.assertEqual(len(issues), 5)
        self.assertEqual(len(saved[0]["claims"]), 1)

    def test_current_sentence_can_name_unregistered_referent_and_self_edge_is_dropped(self):
        first, second = "Plants release vapor.", "This release is transpiration."
        referent = fixtures.concept("transpiration", kind="process")

        def respond(role, payload):
            if role == "concept_reference_resolver":
                self.assertEqual(payload["available_concepts"], [])
                self.assertEqual(payload["CURRENT_SENTENCE"], second)
                return dict(concept=referent, reason="Named in current sentence")
            text = payload["CURRENT_SENTENCE"].strip()
            relations = [] if text == first else [self.relation(
                fixtures.concept("this release", kind="event"), referent, second)]
            return fixtures.extraction(text, relations)

        with patch.object(RelationRegistry, "resolve", side_effect=AssertionError("Self edges need no relation lookup")):
            rows, _, registry = self.run_extraction(first + " " + second, respond)
        self.assertEqual(rows[0]["status"], "complete")
        self.assertEqual(rows[0]["relation_proposals"], [])
        self.assertEqual(set(registry.entries), {"transpiration"})
        self.assertEqual(len(rows[0]["claims"]), 2)

    def test_existing_concepts_named_in_current_sentence_are_available_to_resolver(self):
        referent = fixtures.concept("ProcessP", kind="process")
        seen = []
        def respond(role, payload):
            seen.extend(payload["available_concepts"])
            return dict(concept=referent, reason="Existing concept named here")
        model = fixtures.FixtureModel(respond)
        registry = ConceptRegistry(model, self.trace)
        registry.resolve(referent, "", "seed")
        text = "This process is ProcessP."
        unit = dict(id="sentence", start=0, end=len(text), text=text)
        result = resolve_endpoint(Endpoint(**fixtures.concept("this process")), {}, "source", unit,
                                  unit, registry, model, self.trace, "reference", {})
        self.assertEqual(result.name, "ProcessP")
        self.assertEqual([e["name"] for e in seen], ["processp"])

    def test_genuinely_ambiguous_reference_remains_unresolved(self):
        text = "This process changes."
        def respond(role, payload):
            if role == "concept_reference_resolver":
                return dict(concept=None, reason="No process is identified by the text")
            return fixtures.extraction(text, concepts=[fixtures.concept("this process", kind="process")])
        rows, _, registry = self.run_extraction(text, respond)
        self.assertEqual(rows[0]["status"], "incomplete")
        self.assertEqual(len(rows[0]["issues"]), 1)
        self.assertEqual(registry.entries, {})

    def test_reference_detection_distinguishes_articles_and_embedded_pronouns(self):
        for name in ("The cell membrane", "cell membrane", "the anatomy of the circuit's cells",
                     "theory", "thermal properties", "somatic cells"):
            with self.subTest(name=name):
                self.assertFalse(reference_name(name))
        for name in ("its cells", "the anatomy of its cells", "electrical properties of their membranes",
                     "connections between them", "ways those connections change", "this process", "it"):
            with self.subTest(name=name):
                self.assertTrue(reference_name(name))

    def test_ordinary_article_names_normalize_without_reference_calls_or_evidence_changes(self):
        text = "The cell membrane is associated with the cell interior."
        source = fixtures.concept("The cell membrane", kind="structure")
        target = fixtures.concept("the cell interior", kind="structure")
        relation = self.relation(source, target, text)

        def respond(role, payload):
            self.assertEqual(role, "extractor", "Ordinary names must not trigger reference resolution")
            return fixtures.extraction(text, [relation], concepts=[source, target])

        rows, model, registry = self.run_extraction(text, respond)
        self.assertEqual(rows[0]["status"], "complete")
        self.assertEqual(set(registry.entries), {"cell membrane", "cell interior"})
        proposal = rows[0]["relation_proposals"][0]
        self.assertEqual((proposal["source"], proposal["target"]), ("cell membrane", "cell interior"))
        self.assertEqual(proposal["source_mention"]["definition"], source["definition"])
        self.assertEqual(proposal["surface_source"], "The cell membrane")
        self.assertEqual(proposal["surface_target"], "the cell interior")
        self.assertEqual(text[proposal["evidence_start"]:proposal["evidence_end"]], text)
        self.assertNotIn("concept_reference_resolver", [r["role"] for r in model.requests])

    def test_embedded_references_resolve_with_scope_and_original_evidence_preserved(self):
        first = "A circuit has cells."
        current = ("Understanding a circuit requires several levels of explanation: the anatomy of its cells, "
                   "the electrical properties of their membranes, the connections between them, "
                   "and the ways those connections change.")
        names = {
            "the anatomy of its cells": "the anatomy of the circuit's cells",
            "the electrical properties of their membranes": "electrical properties of the circuit's cell membranes",
            "the connections between them": "connections between the circuit's cells",
            "the ways those connections change": "changes to connections between the circuit's cells",
        }
        mentions = [fixtures.concept(name) for name in names]
        relations = [self.relation(fixtures.concept("circuit"), mention, current) for mention in mentions]

        def respond(role, payload):
            if role == "concept_reference_resolver":
                self.assertEqual(payload["PREVIOUS_SENTENCE"], first)
                self.assertEqual(payload["CURRENT_SENTENCE"], current)
                return dict(concept=fixtures.concept(names[payload["reference_phrase"]]),
                            reason="Replace references with their stated owners without dropping the named property")
            self.assertEqual(role, "extractor")
            if payload["CURRENT_SENTENCE"].strip() == first:
                return fixtures.extraction(first)
            return fixtures.extraction(current, relations, concepts=mentions)

        rows, model, registry = self.run_extraction(first + " " + current, respond)
        self.assertEqual(rows[0]["status"], "complete")
        proposals = rows[0]["relation_proposals"]
        self.assertEqual(len(proposals), 4)
        self.assertEqual({p["target"] for p in proposals}, {n.removeprefix("the ") for n in names.values()})
        self.assertTrue(all(p["evidence"] == current for p in proposals))
        self.assertEqual({p["surface_target"] for p in proposals}, set(names))
        self.assertEqual(sum(r["role"] == "concept_reference_resolver" for r in model.requests), 4)
        self.assertFalse(set(names) & set(registry.entries))

    def test_resolver_rejects_unresolved_pronouns_even_without_leading_article(self):
        text = "A circuit has cells; the anatomy of its cells matters."
        unit = dict(id="sentence", start=0, end=len(text), text=text)
        model = fixtures.FixtureModel(lambda role, p: dict(
            concept=fixtures.concept("anatomy of its cells"), reason="Still unresolved"))
        registry = ConceptRegistry(model, self.trace)
        with self.assertRaisesRegex(ValueError, "remaining pronouns"):
            resolve_endpoint(Endpoint(**fixtures.concept("the anatomy of its cells")), {}, "target", unit,
                             unit, registry, model, self.trace, "reference", {})

    def test_explicit_reference_hint_still_resolves_an_article_name(self):
        before, current = "ProcessP occurs.", "The rate changes."
        unit = dict(id="sentence", start=len(before) + 1, end=len(before) + 1 + len(current), text=current)
        context = dict(start=0, text=before + " " + current)
        model = fixtures.FixtureModel(lambda role, p: dict(
            concept=fixtures.concept("the rate of ProcessP", kind="property"), reason="Rate of the preceding process"))
        registry = ConceptRegistry(model, self.trace)
        result = resolve_endpoint(Endpoint(**fixtures.concept("The rate", reference_phrase="The rate")),
                                  {}, "target", unit, context, registry, model, self.trace, "reference", {})
        self.assertEqual(result.name, "rate of ProcessP")
        self.assertEqual(model.requests[0]["role"], "concept_reference_resolver")


if __name__ == "__main__":
    unittest.main()
