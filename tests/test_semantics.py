"""Offline regressions: all model outputs are fixtures, never Ollama calls."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.cli import main
from pipeline.debate import check_novelty, debate, review_candidate, review_extractions
from pipeline.extraction import extract
from pipeline.graph_view import build_graph
from pipeline.ingest import split_document
from pipeline.models import Models
from pipeline.registry import ConceptRegistry, RelationRegistry, FactIndex
from pipeline.seeds import build_outline, select_seeds
from pipeline.trace import Trace


def concept(name, definition=None, kind="structure"):
    return dict(name=name, definition=definition or name, kind=kind)


class FixtureModel:
    def __init__(self, respond):
        self.respond, self.requests = respond, []

    def ask(self, role, instruction, payload, schema, entity_id, validator=None):
        self.requests.append((role, instruction, payload))
        result = schema.model_validate(self.respond(role, payload))
        if validator:
            validator(result)
        return result


def equivalence(valid=True):
    return dict(exact_meaning=valid, same_direction=valid, compatible_types=valid, reason="Fixture equivalence")


def reviewer(role, payload, **overrides):
    if "items" in payload:
        return {item["id"]: reviewer(role, dict(item, chapter=item.get("chapter", payload.get("chapter", {}))),
                                    **overrides)[item["id"]] for item in payload["items"]}
    identifier = payload["candidate"]["id"]
    if role == "proposer_rebuttal":
        return {identifier: dict(candidate_id=identifier, position="withdraw", reason="Unsupported objection")}
    row = dict(candidate_id=identifier, semantics_valid=True, direction_valid=True, types_valid=True,
        no_contradiction=True, certain=True, evidence_status="supported" if payload.get("quote") else "not_applicable",
        domain_relevance=.95, reason="Specific relation checked")
    if payload["candidate"].get("origin") == "background":
        row.update(chapter_related=True, related_topic=payload["chapter"]["topics"][0])
    if role in ("judge", "extraction_reviewer"):
        row.update(accept=True, objections_resolved=True)
    row.update(overrides)
    if role == "extraction_reviewer" or (role == "judge" and payload["candidate"].get("origin") == "document"):
        row.setdefault("rejection_categories", [] if row.get("accept") else ["unsupported_claim"])
    return {identifier: row}


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "run", "fixture")
        self.addCleanup(self.trace.close)

    def registry(self, respond):
        model = FixtureModel(respond)
        return model, ConceptRegistry(model, self.trace), RelationRegistry(model, self.trace)

    def test_contextual_has_a_does_not_become_global_alias(self):
        def respond(role, p):
            if role == "relation_resolver":
                key = "has_part" if p["occurrence"]["target"] == "axon" else "contains"
                return dict(key=key, exact_meaning=True, same_direction=True, reason="Contextual meaning")
            return equivalence()
        model, _, relations = self.registry(respond)
        self.assertEqual(relations.resolve("has-a", "Structural component", "neuron", "axon", "", "one"), "has_part")
        self.assertEqual(relations.resolve("has-a", "Spatial containment", "lake", "water", "", "two"), "contains")
        self.assertEqual(sum(r[0] == "relation_match_verifier" for r in model.requests), 2)
        self.assertNotIn("has-a", relations.entries)

    def test_established_enables_cannot_be_collapsed_into_causes(self):
        model, _, relations = self.registry(lambda role, p: dict(
            key="causes", exact_meaning=True, same_direction=True, reason="Faulty model says similar"))
        self.assertIsNone(relations.resolve("enables", "Permits something", "sunlight", "evaporation", "", "one"))
        self.assertEqual(relations.entries["enables"]["inverse"], None)
        self.assertTrue(all(role == "relation_resolver" for role, _, _ in model.requests))

    def test_inverse_direction_is_not_an_alias(self):
        def respond(role, p):
            if role == "relation_resolver":
                return dict(key="part_of", exact_meaning=True, same_direction=False, reason="Inverse only")
            if role == "relation_definition":
                return dict(key="structurally_includes", definition="TARGET is a structural part of SOURCE",
                            symmetric=False, inverse=None)
            return dict(coherent=True, meaning_preserved=False, direction_preserved=False,
                        symmetry_correct=True, inverse_correct=True, reason="Cannot verify direction")
        _, _, relations = self.registry(respond)
        self.assertIsNone(relations.resolve("includes", "Ambiguous", "neuron", "axon", "", "one"))
        self.assertNotIn("structurally_includes", relations.entries)

    def test_new_relation_is_verified_and_run_local(self):
        def respond(role, p):
            if role == "relation_resolver":
                return dict(key=None, exact_meaning=False, same_direction=False, reason="No equivalent")
            if role == "relation_definition":
                return dict(key="transports_to", definition="SOURCE transports water to TARGET",
                            symmetric=False, inverse=None)
            return dict(coherent=True, meaning_preserved=True, direction_preserved=True,
                        symmetry_correct=True, inverse_correct=True, reason="Precise transport relation")
        model, _, relations = self.registry(respond)
        key = relations.resolve("carries_to", "SOURCE transports water to TARGET", "river", "ocean", "", "one")
        self.assertEqual(key, "transports_to")
        self.assertIn("transports_to", relations.entries)
        self.assertNotIn("transports_to", RelationRegistry(model, self.trace).entries)
        self.assertIn("relation_definition_verifier", [r[0] for r in model.requests])

    def test_plural_identity_merges_without_merging_subtype(self):
        def respond(role, p):
            if role == "concept_resolver":
                same = p["mention"]["name"] == "axons"
                return dict(key="axon" if same else None, exact_meaning=same, same_direction=same, reason="Identity")
            return equivalence()
        _, concepts, _ = self.registry(respond)
        self.assertEqual(concepts.resolve(concept("axon"), "", "one"), "axon")
        self.assertEqual(concepts.resolve(concept("Axons", "Neuronal output processes"), "", "two"), "axon")
        self.assertEqual(concepts.resolve(concept("myelinated axon"), "", "three"), "myelinated axon")
        self.assertEqual(concepts.entries["axon"]["aliases"], ["axon", "axons"])

    def test_inverse_and_symmetric_duplicate_checks_cover_all_facts(self):
        model, _, relations = self.registry(lambda role, p: self.fail("Exact duplicates must not call model"))
        facts = FactIndex(relations)
        facts.add(dict(id="extracted", source="neuron", relation="has_part", target="axon"))
        duplicate = check_novelty(dict(source="axon", relation="part_of", target="neuron"), [], facts, model, self.trace)
        self.assertEqual(duplicate["evidence_ids"], ["extracted"])
        facts.add(dict(id="seed_earlier", source="axon", relation="sibling_of", target="dendrite"))
        self.assertEqual(facts.find(dict(source="dendrite", relation="sibling_of", target="axon"))["id"], "seed_earlier")
        self.assertIsNone(facts.find(dict(source="axon", relation="has_part", target="neuron")))
        self.assertIsNone(facts.find(dict(source="neuron", relation="causes", target="axon")))

    def setup_review(self, respond):
        model, concepts, relations = self.registry(respond)
        concepts.entries = {n: dict(concept(n), aliases=[n]) for n in ("neuron", "axon")}
        row = dict(id="document_relation", source="neuron", target="axon", relation="has_part",
            relation_definition=relations.entries["has_part"]["definition"], origin="document",
            reason="Extracted relation", evidence="A neuron has an axon.", evidence_start=0, evidence_end=22,
            chunk_id="chunk_001", paragraph_id="paragraph_001")
        return model, concepts, relations, row

    def test_exact_quote_with_wrong_relation_is_rejected(self):
        model, concepts, relations, row = self.setup_review(
            lambda role, p: reviewer(role, p, **({"evidence_status": "unsupported"} if role != "proposer_rebuttal" else {})))
        row.update(relation="is_a", relation_definition=relations.entries["is_a"]["definition"])
        chunk = dict(id="chunk_001", text=row["evidence"])
        extractions = [dict(chunk_id="chunk_001", relations=[], relation_proposals=[row])]
        reviews = review_extractions(extractions, [chunk], dict(overview="Neurons", topics=["neuron"]),
                                    concepts, FactIndex(relations), model, self.trace)
        self.assertFalse(reviews[0]["accepted"])
        self.assertFalse(reviews[0]["gates"]["evidence"])
        self.assertEqual(extractions[0]["relations"], [])
        self.assertEqual([r[0] for r in model.requests], ["extraction_reviewer"])

    def test_withdrawal_does_not_veto_independent_judge(self):
        model, concepts, _, row = self.setup_review(reviewer)
        review_candidate(row, dict(text=row["evidence"]), dict(overview="Neurons", topics=["neuron"]),
                         concepts, model, self.trace, 0)
        self.assertEqual(row["rebuttal"]["position"], "withdraw")
        self.assertTrue(row["accepted"])
        judge_payload = next(p for role, _, p in model.requests if role == "judge")
        self.assertNotIn("critic", judge_payload)
        self.assertNotIn("rebuttal", judge_payload)
        self.assertNotIn("position", json.dumps(judge_payload))
        self.assertNotIn("domain_relevance", json.dumps(judge_payload))

    def test_high_relevance_cannot_override_category_error(self):
        model, concepts, _, row = self.setup_review(
            lambda role, p: reviewer(role, p, **({"types_valid": False} if role != "proposer_rebuttal" else {})))
        review_candidate(row, dict(text=row["evidence"]), dict(overview="Neurons", topics=["neuron"]),
                         concepts, model, self.trace, 0)
        self.assertFalse(row["accepted"])
        self.assertGreater(row["score"], .9)
        self.assertEqual(self.trace.counts["debate.verdict_conflict"], 1)

    def test_unstated_background_is_eligible_but_offtopic_is_rejected(self):
        for score, accepted in ((.9, True), (.4, False)):
            model, concepts, _, row = self.setup_review(
                lambda role, p: reviewer(role, p, **({"domain_relevance": score, "chapter_related": accepted,
                    "related_topic": "neuron" if accepted else None} if role != "proposer_rebuttal" else {})))
            row.update(origin="background")
            row.pop("evidence")
            review_candidate(row, dict(text="Neurons transmit signals."), dict(overview="Neurons", topics=["neuron"]),
                             concepts, model, self.trace, .75)
            self.assertEqual(row["accepted"], accepted)
            self.assertEqual(row["verification_basis"], "model_knowledge")
            self.assertTrue(all("Absence from the text is NOT an objection" in instruction
                                for _, instruction, _ in model.requests))

    def test_novelty_scans_later_chapter_segments_and_all_accepted_facts(self):
        def respond(role, p):
            ids = [r["id"] for r in p["references"]]
            conflict = "late_fact" in ids
            return dict(status="contradiction" if conflict else "new",
                        evidence_ids=["late_fact"] if conflict else [], reason="Comparison")
        model, _, relations = self.registry(respond)
        facts = FactIndex(relations)
        facts.add(dict(id="late_fact", source="x", relation="inhibits", target="y", relation_definition="Reduces"))
        chunks = [dict(id=f"chunk_{i}", text="Source fact") for i in range(14)]
        row = dict(source="x", relation="enables", target="y", id="candidate", origin="background",
                   relation_definition=relations.entries["enables"]["definition"])
        result = check_novelty(row, chunks, facts, model, self.trace)
        self.assertEqual(result["status"], "contradiction")
        seen = [r["id"] for _, _, p in model.requests for r in p["references"]]
        self.assertEqual(seen, [c["id"] for c in chunks] + ["late_fact"])

    def test_all_seed_concepts_assessed_and_low_frequency_main_idea_survives(self):
        def respond(role, p):
            if role == "segment_summarizer":
                return dict(summary="A segment", topics=["topic"])
            if role == "chapter_summarizer":
                return dict(overview="Whole chapter", topics=["topic"])
            self.assertEqual(role, "seed_selector")
            self.assertNotIn("chapter_concepts", p)
            return {c["id"]: dict(importance=.95 if c["name"] == "central" else .3,
                        decision="eligible", chapter_topic="topic", background_question="What explains this concept?",
                        relevance=.9, expansion_value=.8, reason="Meaning, not frequency") for c in p["items"]}
        model, concepts, _ = self.registry(respond)
        chunks = [dict(id=f"chunk_{i}", text="A segment.", paragraph_id=f"p_{i}") for i in range(25)]
        outline = build_outline(chunks, model, self.trace)
        self.assertEqual([c for s in outline["segments"] for c in s["chunk_ids"]], [c["id"] for c in chunks])
        concepts.entries = {n: concept(n) for n in ("incidental", "central")}
        extractions = [dict(chunk_id=c["id"], concepts=["central"] if i == 24 else ["incidental"])
                       for i, c in enumerate(chunks)]
        seeds = select_seeds(extractions, chunks, concepts, outline, model, self.trace, threshold=.7)
        self.assertEqual([s["concept"] for s in seeds], ["central"])
        assessed = json.loads((self.trace.directory / "artifacts/seeds.json").read_text())
        self.assertEqual(len(assessed["assessments"]), 2)
        self.assertEqual(seeds[0]["chunk_ids"], ["chunk_24"])

    def test_seed_batch_rejects_extra_missing_and_contradictory_answers(self):
        from pydantic import ValidationError
        from pipeline.batching import ask_keyed
        from pipeline.seeds import SeedAssessment

        eligible = dict(decision="eligible", chapter_topic="groundwater",
            background_question="What controls aquifer permeability?",
            importance=.9, relevance=.9, expansion_value=.9, reason="Useful missing background")
        excluded = dict(decision="excluded", exclusion="already_explained",
            importance=.9, relevance=.9, expansion_value=.1, reason="Already explained")
        items = [dict(id=f"candidate_{i}", name=f"concept {i}") for i in range(4)]
        valid = {item["id"]: dict(eligible) for item in items}
        valid["candidate_3"] = excluded

        def request(answer):
            return ask_keyed(FixtureModel(lambda role, payload: answer), "seed_selector",
                "Assess only these IDs", items, SeedAssessment, "batch")

        self.assertEqual(request(valid), valid)
        invalid_answers = [
            {**valid, "unrequested_concept": eligible},
            {key: value for key, value in valid.items() if key != "candidate_0"},
            {**valid, "candidate_0": dict(eligible, exclusion="already_explained")},
            {**valid, "candidate_0": dict(eligible, background_question=None)},
            {**valid, "candidate_0": dict(eligible, background_question="   ")},
            {**valid, "candidate_0": dict(eligible, chapter_topic="")},
            {**valid, "candidate_0": dict(eligible, eligible_concept=True)},
            {**valid, "candidate_3": dict(excluded, background_question="A question")},
            {**valid, "candidate_3": dict(excluded, exclusion="none")},
            {**valid, "candidate_3": dict(excluded, reason="")},
        ]
        for answer in invalid_answers:
            with self.subTest(answer=answer), self.assertRaises(ValidationError):
                request(answer)

    def test_excluded_seed_cannot_pass_even_with_high_scores(self):
        model, concepts, _ = self.registry(lambda role, payload: {
            item["id"]: dict(decision="excluded", exclusion="already_explained",
                importance=1, relevance=1, expansion_value=1, reason="No unanswered question")
            for item in payload["items"]})
        concepts.entries = {"aquifer": concept("aquifer")}
        chunks = [dict(id="chunk_1", paragraph_id="p_1", text="An aquifer stores groundwater.")]
        outline = dict(overview="Groundwater", topics=["aquifers"],
            segments=[dict(id="segment_1", chunk_ids=["chunk_1"], summary="Aquifers", topics=["aquifers"])])
        seeds = select_seeds([dict(chunk_id="chunk_1", concepts=["aquifer"])],
            chunks, concepts, outline, model, self.trace)
        self.assertEqual(seeds, [])
        artifact = json.loads((self.trace.directory / "artifacts/seeds.json").read_text())
        assessment = artifact["assessments"][0]
        self.assertFalse(assessment["eligible_concept"])
        self.assertEqual(assessment["exclusion"], "already_explained")
        self.assertIsNone(assessment["background_question"])

    def test_duplicate_background_proposals_across_seeds_and_inverse_forms(self):
        def respond(role, p):
            if role == "proposer":
                source = p["seed"]["concept"]
                key, target = ("has_part", "axon") if source == "neuron" else ("part_of", "neuron")
                return dict(proposals=[dict(target=concept(target), relation=key,
                    relation_definition=relations.entries[key]["definition"], confidence=.9, reason="Useful general fact")],
                    reason="One proposal")
            if role == "novelty_checker":
                return dict(status="new", evidence_ids=[], reason="Absent from source")
            return reviewer(role, p)
        model, concepts, relations = self.registry(respond)
        concepts.entries = {n: dict(concept(n), aliases=[n]) for n in ("neuron", "axon")}
        seeds = [dict(id=f"seed_{i}", concept=n, definition=n, kind="structure",
                 chunk_id="chunk_001", paragraph_id="p_001", chunk_ids=["chunk_001"])
                 for i, n in enumerate(("neuron", "axon"))]
        result = debate(seeds, [dict(id="chunk_001", text="Neurons transmit signals.")],
            dict(overview="Neural structures", topics=["neurons"], segments=[]),
            concepts, relations, FactIndex(relations), model, self.trace)
        self.assertTrue(result["candidates"][0]["accepted"])
        self.assertFalse(result["candidates"][1]["accepted"])
        self.assertEqual(result["candidates"][1]["novelty"]["status"], "duplicate")
        self.assertEqual(sum(role == "judge" for role, _, _ in model.requests), 1)

    def test_registry_model_routing_has_no_conversation_history(self):
        from pipeline.evaluation import Reconstruction
        from ollama import ChatResponse
        with patch("pipeline.models.Client") as client:
            client.return_value.chat.return_value = ChatResponse(
                message=dict(role="assistant", content='{"text":"fixture","reason":"fixture"}'))
            model = Models(self.trace, "qwen", "embed", "http://localhost", registry_model="isolated")
            for role in ("relation_resolver", "concept_match_verifier", "judge"):
                model.ask(role, "Instruction", {}, Reconstruction, "one")
            calls = client.return_value.chat.call_args_list
            self.assertEqual([c.kwargs["model"] for c in calls], ["isolated", "isolated", "qwen"])
            self.assertTrue(all(len(c.kwargs["messages"]) == 1 for c in calls))

    def test_expanded_chapters_cover_multiple_segments(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("input.txt", "water_cycle.txt"):
            text = (root / "data" / name).read_text(encoding="utf-8")
            paragraphs, chunks = split_document(text, 85, self.trace)
            self.assertGreater(len(text.split()), 1500)
            self.assertGreaterEqual(len(paragraphs), 15)
            self.assertEqual(" ".join(text.split()), " ".join(" ".join(c["text"] for c in chunks).split()))

    def test_both_dispatches_isolated_configs_and_continues_after_failure(self):
        captured = []
        def run(args):
            captured.append(args)
            return 1 if args.chapter == "neuroscience" else 0
        with patch("pipeline.cli.run_chapter", side_effect=run):
            self.assertEqual(main(["--chapter", "both", "--output-root", self.temp.name, "--no-open"]), 1)
        self.assertEqual([c.chapter for c in captured], ["neuroscience", "water-cycle"])
        self.assertNotEqual(captured[0].input, captured[1].input)
        self.assertNotEqual(captured[0].output_root, captured[1].output_root)
        self.assertIsNot(captured[0], captured[1])

    def test_invalid_chapter_combinations_fail_before_any_run(self):
        for flags in (["--chapter", "both", "--input", "x.txt"],
                      ["--chapter", "both", "--resume", "old"],
                      ["--seed-threshold", "1.1"], ["--seed-threshold", "nan"]):
            with self.subTest(flags=flags), patch("pipeline.cli.run_chapter") as run, self.assertRaises(SystemExit):
                main(flags)
            run.assert_not_called()

    def test_extraction_to_graph_merges_inverse_evidence_after_review(self):
        text = "A neuron has an axon.\n\nAn axon is part of a neuron."
        paragraphs, chunks = split_document(text, 85, self.trace)
        def respond(role, p):
            if role == "extractor":
                first = p["CURRENT_CHUNK"].startswith("A neuron")
                key = "has_part" if first else "part_of"
                return dict(unit_kind="core_statement", concepts=[concept("neuron"), concept("axon")],
                    claims=[dict(text=p["CURRENT_CHUNK"], evidence=p["CURRENT_CHUNK"])],
                    relations=[dict(source=concept("neuron" if first else "axon"), target=concept("axon" if first else "neuron"),
                        relation=key, relation_definition=relations.entries[key]["definition"], evidence=p["CURRENT_CHUNK"])],
                    confidence=.9, reason="Quoted structure")
            if role == "concept_resolver":
                return dict(key=None, exact_meaning=False, same_direction=False, reason="Distinct concept")
            return reviewer(role, p)
        model, concepts, relations = self.registry(respond)
        extractions = extract(chunks, paragraphs, model, self.trace, concepts, relations)
        self.assertTrue(all(not e["relations"] for e in extractions))
        facts = FactIndex(relations)
        decisions = review_extractions(extractions, chunks, dict(overview="Neuron structure", topics=["neuron"]),
                                       concepts, facts, model, self.trace)
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(d["accepted"] for d in decisions))
        self.assertEqual(len(facts.rows), 1)
        graph = build_graph(text, paragraphs, chunks, extractions, dict(candidates=[]), self.trace, concepts, relations)
        domain_edges = [e for e in graph["edges"] if e["label"] in ("has_part", "part_of")]
        self.assertEqual(len(domain_edges), 1)
        self.assertEqual(domain_edges[0]["supporting_evidence"][0]["evidence"], chunks[1]["text"])
        self.assertEqual(decisions[1]["duplicate_of"], decisions[0]["id"])

    def test_uncertain_relation_match_cannot_change_fact_direction(self):
        def respond(role, p):
            if role == "relation_resolver":
                return dict(key="has_part", exact_meaning=True, same_direction=True, reason="Bad match")
            if role == "relation_match_verifier":
                return equivalence(False)
            if role == "relation_definition":
                return dict(key="unverified_part", definition="SOURCE is a part of TARGET", inverse=None, symmetric=False)
            return dict(coherent=True, meaning_preserved=True, direction_preserved=False,
                        symmetry_correct=True, inverse_correct=True, reason="Direction uncertain")
        _, _, relations = self.registry(respond)
        self.assertIsNone(relations.resolve("belongs", "SOURCE is a component of TARGET", "axon", "neuron", "", "one"))

    def test_two_tiny_mocked_chapters_have_fresh_model_and_registry_state(self):
        instances = []
        class FakeModels:
            calls = retries = prompt_tokens = output_tokens = cache_hits = 0
            details = {}
            def __init__(self, trace, model, embedding_model, host, **kwargs):
                self.model, self.embedding_model = model, embedding_model
                self.registry_model = kwargs["registry_model"] or model
                self.requests = []
                instances.append(self)
            def preflight(self):
                pass
            def embed(self, text, entity):
                return [1., 2.]
            def ask(self, role, instruction, payload, schema, entity, validator=None):
                self.requests.append((role, payload))
                if role == "segment_summarizer":
                    value = dict(summary=payload["chunks"][0]["text"], topics=["chapter subject"])
                elif role == "chapter_summarizer":
                    value = dict(overview=payload["segments"][0]["overview"], topics=["chapter subject"])
                elif role == "extractor":
                    text = payload["CURRENT_CHUNK"]
                    name = "neuron" if "neuron" in text else "water"
                    value = dict(unit_kind="core_statement", concepts=[concept(name)],
                                 claims=[dict(text=text, evidence=text)], relations=[], confidence=.9, reason="Fixture")
                elif role == "seed_selector":
                    value = {c["id"]: dict(importance=.9, relevance=.9,
                                 decision="eligible", chapter_topic="chapter subject", background_question="What explains this concept?",
                                 expansion_value=.9, reason="Relevant") for c in payload["items"]}
                elif role == "proposer":
                    value = dict(proposals=[], reason="No useful addition")
                elif role == "reconstructor":
                    value = dict(text=" ".join(payload["claims"]), reason="Fixture")
                else:
                    raise AssertionError(role)
                result = schema.model_validate(value)
                if validator:
                    validator(result)
                return result
        inputs = {}
        for name, text in (("neuroscience", "A neuron transmits signals."), ("water-cycle", "Liquid water evaporates.")):
            path = Path(self.temp.name) / (name + ".txt")
            path.write_text(text, encoding="utf-8")
            inputs[name] = path
        out = Path(self.temp.name) / "both"
        with patch("pipeline.cli.CHAPTERS", inputs), patch("pipeline.models.Models", FakeModels):
            code = main(["--chapter", "both", "--output-root", str(out), "--no-open"])
        self.assertEqual(code, 0)
        self.assertEqual(len(instances), 2)
        self.assertIsNot(instances[0], instances[1])
        runs = [next((out / name).iterdir()) for name in inputs]
        registries = [json.loads((run / "artifacts/concepts.json").read_text()) for run in runs]
        self.assertEqual([[c["name"] for c in r["concepts"]] for r in registries], [["neuron"], ["water"]])
        manifests = [json.loads((run / "manifest.json").read_text()) for run in runs]
        self.assertNotEqual(manifests[0]["run_id"], manifests[1]["run_id"])
        self.assertTrue(all(m["status"] == "completed" for m in manifests))
        self.assertNotIn("Liquid water", json.dumps(instances[0].requests))
        self.assertNotIn("A neuron", json.dumps(instances[1].requests))

    def test_resume_cannot_import_another_chapters_cache(self):
        prior = Path(self.temp.name) / "prior"
        prior.mkdir()
        (prior / "input.txt").write_text("A neuron transmits signals.", encoding="utf-8")
        (prior / "manifest.json").write_text(json.dumps(dict(config=dict(chapter="neuroscience"))), encoding="utf-8")
        source = Path(self.temp.name) / "custom.txt"
        source.write_text("A neuron transmits signals.", encoding="utf-8")
        with patch("pipeline.models.Models") as model:
            code = main(["--input", str(source), "--resume", str(prior),
                         "--output-root", str(Path(self.temp.name) / "resume"), "--no-open"])
        self.assertEqual(code, 1)
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()
