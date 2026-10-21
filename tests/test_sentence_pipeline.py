"""Sentence-to-graph regressions with fixture responses, without live inference."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.debate import review_extractions
from pipeline.extraction import extract
from pipeline.graph_view import build_graph
from pipeline.ingest import split_document
from pipeline.models import Models
from pipeline.registry import ConceptRegistry, FactIndex, RelationRegistry
from pipeline.seeds import collect_seeds
from pipeline.trace import Trace
from test_semantics import FixtureModel, concept, reviewer


class SentencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name) / "run", "fixture")
        self.addCleanup(self.trace.close)

    def test_complete_collective_target_and_distributed_subjects_survive_to_graph(self):
        first = "The water cycle describes how water moves between the atmosphere, the land, and bodies of water."
        second = "Oceans, lakes, rivers, soil, groundwater, snow, and ice store water in reservoirs."
        text = first + " " + second
        movement = "water movement between the atmosphere, land, and bodies of water"
        stored = "water in reservoirs"
        subjects = ["ocean", "lake", "river", "soil", "groundwater", "snow", "ice"]
        def respond(role, payload):
            if role == "extractor":
                sentence = payload["CURRENT_SENTENCE"].strip()
                key = "describes" if sentence == first else "stores"
                sources = ["water cycle"] if sentence == first else subjects
                target = dict(concept(movement if sentence == first else stored,
                                      kind="process" if sentence == first else "substance"), form="phrase")
                return dict(unit_kind="core_statement", concepts=[], confidence=.9, reason="Sentence assertions",
                    claims=[dict(text=sentence, evidence=sentence)],
                    relations=[dict(source=concept(source), relation=key,
                        relation_definition=relations.entries[key]["definition"], target=target,
                        evidence=sentence) for source in sources])
            if role == "concept_resolver":
                return dict(key=None, exact_meaning=False, same_direction=False, reason="Different subjects")
            if role == "extraction_reviewer":
                return reviewer(role, payload)
            self.fail("Unexpected model role: " + role)
        model = FixtureModel(respond)
        concepts, relations = ConceptRegistry(model, self.trace), RelationRegistry(model, self.trace)
        paragraphs, chunks = split_document(text, 100, self.trace)
        extracted = extract(chunks, paragraphs, model, self.trace, concepts, relations)
        self.assertEqual(len(chunks), 1)
        requests = [p["CURRENT_SENTENCE"].strip() for r, _, p in model.requests if r == "extractor"]
        self.assertEqual(requests, [first, second])
        facts = FactIndex(relations)
        review_extractions(extracted, chunks, dict(overview="Water cycle", topics=["water"]),
                           concepts, facts, model, self.trace)
        graph = build_graph(text, paragraphs, chunks, extracted, dict(candidates=[]), self.trace, concepts, relations)
        labels = {n["id"]: n["label"] for n in graph["nodes"]}
        assertions = [(labels[e["source"]], e["label"], labels[e["target"]]) for e in graph["edges"]
                      if e["label"] in {"describes", "stores"}]
        self.assertEqual(assertions, [("water cycle", "describes", movement)] +
                         [(source, "stores", stored) for source in subjects])
        for row in extracted[0]["relations"]:
            self.assertEqual(text[row["evidence_start"]:row["evidence_end"]], row["evidence"])
        seeds = collect_seeds(extracted, chunks, concepts, self.trace)
        self.assertEqual({s["concept"] for s in seeds}, {"water cycle", *subjects})
        self.assertEqual(concepts.entries[movement]["form"], "phrase")
        self.assertEqual(concepts.entries[stored]["form"], "phrase")

    def test_seed_collection_includes_targets_and_long_concepts_without_scoring(self):
        names = ["soil", "water", "a specific concept with five words", "water in reservoirs"]
        registry = SimpleNamespace(entries={n: dict(concept(n), form="phrase" if n == names[-1] else "concept") for n in names})
        chunks = [dict(id="c", paragraph_id="p")]
        extracted = [dict(chunk_id="c", concepts=names + ["soil"])]
        seeds = collect_seeds(extracted, chunks, registry, self.trace)
        self.assertEqual([s["concept"] for s in seeds], names[:-1])
        self.assertEqual(len(collect_seeds(extracted, chunks, registry, self.trace, limit=1)), 1)

    def test_phrase_is_not_collapsed_into_a_concept_or_a_different_phrase(self):
        model = FixtureModel(lambda role, payload: self.fail("Different phrase labels must not be merged"))
        registry = ConceptRegistry(model, self.trace)
        names = [registry.resolve(concept("water", kind="substance"), "", "one")]
        for index, name in enumerate(("water in reservoirs", "water underground")):
            names.append(registry.resolve(dict(concept(name, kind="substance"), form="phrase"), "", str(index)))
        self.assertEqual(len(set(names)), 3)
        self.assertEqual(model.requests, [])

    def test_fact_deduplication_preserves_modality_and_conditions(self):
        facts = FactIndex(RelationRegistry(None, self.trace))
        base = dict(id="one", source="soil", relation="stores", target="water")
        facts.add(base)
        self.assertIsNone(facts.add(dict(base, id="two", modality="can")))
        self.assertIsNone(facts.add(dict(base, id="three", conditions="when pores are available")))
        self.assertEqual(facts.find(dict(base, modality="can"))["id"], "two")
        self.assertEqual(len(facts.rows), 3)

    def test_preflight_does_not_require_an_embedding_model(self):
        with patch("pipeline.models.Client") as client:
            client.return_value.show.return_value.model_dump.return_value = {}
            client.return_value.list.return_value.model_dump.return_value = {"models": []}
            models = Models(self.trace, "generation", "unused_embedding", "http://localhost")
            models.preflight()
            self.assertEqual([c.args[0] for c in client.return_value.show.call_args_list], ["generation"])
            client.return_value.embed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
