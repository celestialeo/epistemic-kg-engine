"""Background admission regressions; fixture domains are not production rules."""
import unittest
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pipeline.debate import (RepresentationCheck, validate_review_consistency,
                             check_novelty_many, check_novelty, apply_verdict,
                             review_background_many, connected_explanation)
from pipeline.registry import ConceptRegistry, RelationRegistry, FactIndex
from pipeline.replay_background import load_document


class FixtureModel:
    batch_size = 4

    def __init__(self, respond):
        self.respond = respond

    def ask(self, role, instruction, payload, schema, entity_id, validator=None):
        result = schema.model_validate(self.respond(role, payload))
        if validator:
            validator(result)
        return result


class BackgroundExpansionTests(unittest.TestCase):
    def setUp(self):
        self.trace = Mock()

    def representation(self, **kwargs):
        return RepresentationCheck(**(dict(link_reading="A acts on B", meaning_matches=False,
            direction_valid=False, explanation_matches=False, scope_preserved=True,
            reason="The direction is incorrect.",
            suggested_correction=None) | kwargs))

    def audit_model(self):
        def answer(role, payload):
            self.assertNotIn("review", payload)  # Existing verdict cannot bias extraction.
            return {field: dict(reason_quote="The direction is incorrect." if field == "direction_valid" else None,
                                implied_value=False if field == "direction_valid" else None)
                    for field in payload["field_meanings"]}
        return FixtureModel(answer)

    def test_consistent_rejection_does_not_trigger_retry(self):
        validate_review_consistency(self.representation(), self.audit_model(), "one")

    def test_reason_flag_conflict_requires_reviewer_correction(self):
        with self.assertRaisesRegex(ValueError, "direction_valid=True"):
            validate_review_consistency(self.representation(direction_valid=True), self.audit_model(), "one")

    def test_agreeing_audit_does_not_block_review_over_quote_formatting(self):
        review = self.representation()
        model = FixtureModel(lambda role, payload: {
            field: dict(reason_quote="An agreeing paraphrase", implied_value=getattr(review, field))
            for field in payload["field_meanings"]})
        validate_review_consistency(review, model, "one")

    def test_alias_cannot_merge_a_distinct_measure_with_its_property(self):
        def answer(role, payload):
            if role == "concept_alias_resolver":
                return dict(canonical_name="temperature", reason="Related measure")
            return dict(same_concept=True, same_scope=True,
                        distinction="One is a property, the other is its measuring instrument.", reason="Related")
        registry = ConceptRegistry(FixtureModel(answer), self.trace)
        registry.entries["temperature"] = dict(name="temperature", definition="Thermal property", kind="property")
        name = registry.resolve_background(dict(name="thermometer", definition="Measuring instrument", kind="entity"), {}, "one")
        self.assertEqual(name, "thermometer")
        self.assertNotIn("thermometer", registry.aliases)

    def test_real_alias_still_reuses_canonical_concept(self):
        def answer(role, payload):
            if role == "concept_alias_resolver":
                return dict(canonical_name="sodium chloride", reason="Same compound")
            return dict(same_concept=True, same_scope=True, distinction=None, reason="Same compound")
        registry = ConceptRegistry(FixtureModel(answer), self.trace)
        registry.entries["sodium chloride"] = dict(name="sodium chloride", definition="NaCl", kind="substance")
        self.assertEqual(registry.resolve_background(dict(name="NaCl", definition="Sodium chloride", kind="substance"), {}, "one"), "sodium chloride")

    def test_mechanism_is_sent_to_novelty_and_can_be_new(self):
        def answer(role, payload):
            assertion = payload["items"][0]["candidate"]
            self.assertEqual(assertion["intended_fact"], "Cooling slows a reaction by reducing molecular motion.")
            return {"one": dict(additional_information=["Reduced molecular motion explains slowing"],
                                status="new", evidence_ids=[], related_reference_ids=["text"], reason="Mechanism absent")}
        model = FixtureModel(answer)
        facts = FactIndex(RelationRegistry(model, self.trace))
        row = dict(id="one", source="cooling", relation="inhibits", target="reaction rate",
                   conditions="by reducing molecular motion", intended_fact="Cooling slows a reaction by reducing molecular motion.")
        result = check_novelty_many([row], [dict(id="text", text="Cooling slows the reaction.")], facts, model, self.trace)
        self.assertEqual(result["one"]["status"], "new")

    def test_duplicate_with_acknowledged_new_information_is_invalid(self):
        model = FixtureModel(lambda role, payload: {"one": dict(additional_information=["Missing mechanism"],
            status="duplicate", evidence_ids=["text"], related_reference_ids=[], reason="Same outcome")})
        facts = FactIndex(RelationRegistry(model, self.trace))
        with self.assertRaisesRegex(ValueError, "not wholly duplicate"):
            check_novelty_many([dict(id="one", source="a", relation="inhibits", target="b")],
                              [dict(id="text", text="A reduces B")], facts, model, self.trace)

    def test_exact_and_inverse_duplicates_never_reach_debate(self):
        model = FixtureModel(lambda *args: self.fail("Exact duplicates need no model call"))
        facts = FactIndex(RelationRegistry(model, self.trace))
        facts.add(dict(id="known", source="tree", relation="has_part", target="root"))
        result = check_novelty(dict(source="root", relation="part_of", target="tree"), [], facts, model, self.trace)
        self.assertEqual(result["status"], "duplicate")

    def test_named_background_predicate_cannot_be_redefined_by_its_draft(self):
        model = FixtureModel(lambda *args: self.fail("Known contract needs usage review, not a new definition"))
        relations = RelationRegistry(model, self.trace)
        contract = dict(relations.entries["has_part"])
        key = relations.resolve_background("has_part", "TARGET contains SOURCE", "tree", "root", {}, "one")
        self.assertEqual(key, "has_part")
        self.assertEqual(relations.entries[key], contract)

    def test_judge_cannot_accept_with_a_failed_truth_gate(self):
        row = dict(id="one", origin="background", relation="causes")
        verdict = dict(accept=True, semantics_valid=True, direction_valid=True, types_valid=True,
                       no_contradiction=False, certain=False, objections_resolved=False,
                       evidence_status="not_applicable", chapter_related=True, gap_addressed=True,
                       domain_relevance=1, reason="The claim is false")
        apply_verdict(row, verdict, self.trace, None)
        self.assertFalse(row["accepted"])

    def test_withdrawal_ends_review_without_judge(self):
        row = dict(id="one", chunk_id="chunk", origin="background")
        roles = []
        def ask(models, role, instruction, items, *args, **kwargs):
            if not items:
                return {}
            roles.append(role)
            if role == "critic":
                return {"one": dict(objections=["False claim"])}
            if role == "proposer_rebuttal":
                return {"one": dict(position="withdraw", reason="The objection is correct")}
            self.fail("A withdrawal must not reach the judge")
        with patch("pipeline.debate.review_context", return_value={"chapter": {}}), patch("pipeline.debate.ask_keyed", side_effect=ask):
            review_background_many([row], {"chunk": {}}, {}, None, None, self.trace)
        self.assertEqual(roles, ["critic", "proposer_rebuttal"])
        self.assertEqual(row["review_status"], "withdrawn")

    def test_supporting_links_need_a_surviving_anchor(self):
        anchor = dict(id="anchor", source="seed", target="new")
        support = dict(id="support", source="new", target="other")
        seed = dict(id="seed_1", concept="seed")
        facts = SimpleNamespace(rows=[])
        self.assertEqual(connected_explanation([anchor, support], seed, facts), {"anchor", "support"})
        self.assertEqual(connected_explanation([support], seed, facts), set())

    def test_saved_replay_does_not_import_rejected_background_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            saved = {
                "chunks": [], "extractions": [dict(concepts=["property"], relations=[])],
                "chapter_outline": dict(overview="", topics=[]),
                "concepts": dict(concepts=[dict(name="property", definition="A property", kind="property"),
                                           dict(name="unaccepted", definition="Rejected addition", kind="entity")],
                                 aliases={"measure": "property"}),
                "concept_reconciliation": dict(redirects={"property": "property"}),
                "relations": dict(relations=[]),
            }
            for name, value in saved.items():
                (artifacts / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
            before = {p.name: p.read_bytes() for p in artifacts.iterdir()}
            _, _, _, concepts, _, facts = load_document(root, None, self.trace)
            self.assertEqual(set(concepts.entries), {"property"})
            self.assertNotIn("measure", concepts.aliases)
            self.assertEqual(facts.rows, [])
            self.assertEqual(before, {p.name: p.read_bytes() for p in artifacts.iterdir()})


if __name__ == "__main__":
    unittest.main()
