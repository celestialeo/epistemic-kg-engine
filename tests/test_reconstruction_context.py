"""Reconstruction sees only chunk-local structured document facts."""
import json
import unittest
from unittest.mock import Mock

from pipeline.evaluation import evaluate, reconstruction_context


class ReconstructionContextTests(unittest.TestCase):
    def graph(self):
        return {
            "nodes": [
                dict(id="a", label="ConceptA", kind="concept", semantic_kind="entity",
                     definition="PRIVATE registry prose", aliases=["PRIVATE alias"]),
                dict(id="b", label="ProcessP", kind="event"),
                dict(id="c", label="ConceptC", kind="concept"),
                dict(id="s", label="PRIVATE statement", kind="statement", text="PRIVATE original",
                     chunk_id="chunk_001"),
            ],
            "edges": [
                dict(source="a", target="b", label="participates_in", origin="document",
                     chunk_id="chunk_001", definition="SOURCE participates in TARGET",
                     conditions="during ConditionQ", modality="may not",
                     evidence="PRIVATE evidence", reason="PRIVATE reasoning"),
                dict(source="a", target="c", label="PRIVATE background", origin="background",
                     chunk_id="chunk_001"),
                dict(source="a", target="c", label="PRIVATE other chunk", origin="document",
                     chunk_id="chunk_002"),
                dict(source="s", target="a", label="PRIVATE annotation", origin="document",
                     chunk_id="chunk_001"),
            ],
            "provenance": dict(text="PRIVATE original", extractions=[dict(
                chunk_id="chunk_001", concepts=["PRIVATE concept"],
                claims=[dict(text="PRIVATE claim", evidence="PRIVATE quote")])]),
        }

    def test_only_local_document_facts_and_qualifications_are_projected(self):
        context = reconstruction_context(self.graph(), "chunk_001")
        self.assertEqual(context, {
            "concepts": [dict(id="a", label="ConceptA", kind="concept", semantic_kind="entity"),
                         dict(id="b", label="ProcessP", kind="event")],
            "relations": [dict(source="ConceptA", relation="participates_in", target="ProcessP",
                               definition="SOURCE participates in TARGET",
                               conditions="during ConditionQ", modality="may not")],
        })
        self.assertNotIn("PRIVATE", json.dumps(context))

    def test_deduplicated_local_support_includes_fact_but_never_evidence(self):
        graph = self.graph()
        graph["edges"][0]["chunk_id"] = "chunk_002"
        graph["edges"][0]["supporting_evidence"] = [
            dict(chunk_id="chunk_001", evidence="PRIVATE local evidence")]
        context = reconstruction_context(graph, "chunk_001")
        self.assertEqual(len(context["relations"]), 1)
        self.assertEqual(context["relations"][0]["modality"], "may not")
        self.assertNotIn("PRIVATE", json.dumps(context))
        graph["edges"][0]["origin"] = "background"
        self.assertEqual(reconstruction_context(graph, "chunk_001"), dict(concepts=[], relations=[]))

    def test_model_receives_only_filtered_context(self):
        graph = self.graph()
        models = Mock()

        def ask(role, instruction, payload, schema, entity_id, validator=None):
            if role == "reconstructor":
                self.assertEqual(payload, reconstruction_context(graph, "chunk_001"))
                self.assertNotIn("PRIVATE", json.dumps(payload))
                return schema(text="ConceptA may not participate in ProcessP during ConditionQ.",
                              reason="Structured facts")
            self.assertEqual(role, "evaluation_claims")
            return schema(claims=[])

        models.ask.side_effect = ask
        evaluate([dict(id="chunk_001", order=0, text="PRIVATE original")], graph, models, Mock())
        self.assertEqual(sum(call.args[0] == "reconstructor" for call in models.ask.call_args_list), 1)

    def test_source_claims_and_background_cannot_trigger_reconstruction(self):
        graph = self.graph()
        graph["edges"][0]["origin"] = "background"
        models = Mock()

        def ask(role, instruction, payload, schema, entity_id, validator=None):
            self.assertEqual(role, "evaluation_claims")
            return schema(claims=[dict(text=payload["text"], evidence=payload["text"])])

        models.ask.side_effect = ask
        result = evaluate([dict(id="chunk_001", order=0, text="PRIVATE original")], graph, models, Mock())
        self.assertEqual(result["results"][0]["reconstruction"], "")
        self.assertEqual(result["final_score"], 0)
