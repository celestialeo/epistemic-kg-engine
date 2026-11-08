"""Completeness scoring must not fabricate graph matches or learner evidence."""
import copy
import unittest

from pipeline.models import ModelResponseError, ModelServiceError
from pipeline.quiz_grading import assess_rubric
from pipeline.student_store import grade, score
from tests.test_quiz_grading import models_with


def rubric_judgment(**changes):
    return dict(dict(fact_id="transition", status="partial",
                     evidence=[dict(statement_id="statement_1", quote="The device delivers electrical energy.")],
                     demonstrated="The answer identifies the delivered energy.",
                     missing="The source energy and its conversion are not explained."), **changes)


class QuizRubricTests(unittest.TestCase):
    def setUp(self):
        self.question = dict(text="Explain how the device converts energy.",
            expected_answer="The device converts incident light into electrical energy.",
            examiner_material=dict(facts=[dict(id="transition", source="incident light", target="electrical energy",
                relation="converted_into", definition="The source energy is converted into the target energy.")]))
        self.result = dict(input="The device delivers electrical energy.",
            statements=[dict(id="statement_1", text="The device delivers electrical energy.", is_assertion=True)],
            matches=[dict(id="delivery", status="match")])

    def assess(self, *outputs):
        self.models = models_with(*outputs)
        return assess_rubric(self.models, self.question, self.result)

    def test_partial_completeness_is_separate_from_a_valid_graph_match(self):
        original = copy.deepcopy(self.result)
        rubric = self.assess(rubric_judgment())
        self.assertEqual(self.result, original)
        marks = grade(self.question, dict(self.result, rubric=rubric))
        self.assertEqual(marks, {"transition": "related"})
        self.assertEqual(score(marks), 50)
        self.assertEqual(self.result["matches"], [dict(id="delivery", status="match")])
        self.assertIn("not explained", rubric[0]["missing"])

    def test_partial_does_not_require_inventing_a_complete_edge(self):
        self.result["matches"] = []
        rubric = self.assess(rubric_judgment())
        self.assertEqual(score(grade(self.question, dict(self.result, rubric=rubric))), 50)
        self.assertEqual(self.result["matches"], [])

    def test_omission_and_contradiction_are_distinct(self):
        for status, evidence, demonstrated, expected in [
            ("not_demonstrated", [], "", "not_demonstrated"),
            ("contradiction", rubric_judgment()["evidence"], "An explicit opposing assertion.", "conflict")]:
            with self.subTest(status=status):
                rubric = self.assess(rubric_judgment(status=status, evidence=evidence, demonstrated=demonstrated))
                self.assertEqual(grade(self.question, dict(self.result, rubric=rubric)), {"transition": expected})

    def test_missing_criterion_cannot_be_marked_complete(self):
        invalid = rubric_judgment(status="complete")
        rubric = self.assess(invalid, rubric_judgment())
        self.assertEqual(rubric[0]["status"], "partial")
        self.assertEqual(self.models.client.chat.call_count, 2)

    def test_invalid_evidence_stays_unresolved_after_three_attempts(self):
        invalid = rubric_judgment(evidence=[dict(statement_id="statement_1", quote="incident light")])
        with self.assertRaisesRegex(ModelResponseError, "verbatim"):
            self.assess(invalid, invalid, invalid)
        self.assertEqual(self.models.client.chat.call_count, 3)

    def test_partial_requires_evidence_and_a_missing_aspect(self):
        for change in [dict(evidence=[]), dict(missing=""), dict(demonstrated="")]:
            with self.subTest(change=change):
                invalid = rubric_judgment(**change)
                with self.assertRaises(ModelResponseError):
                    self.assess(invalid, invalid, invalid)

    def test_evidence_must_belong_to_an_assertion_with_correct_id(self):
        for identifier, assertion in [("statement_99", True), ("statement_1", False)]:
            with self.subTest(identifier=identifier, assertion=assertion):
                self.result["statements"][0]["is_assertion"] = assertion
                invalid = rubric_judgment(evidence=[dict(statement_id=identifier, quote=self.result["input"])])
                with self.assertRaisesRegex(ModelResponseError, "verbatim"):
                    self.assess(invalid, invalid, invalid)

    def test_unrequested_fact_is_rejected_and_not_scored(self):
        invalid = rubric_judgment(fact_id="delivery")
        with self.assertRaisesRegex(ModelResponseError, "supplied rubric fact ID"):
            self.assess(invalid, invalid, invalid)
        with self.assertRaises(ValueError):
            grade(self.question, dict(self.result, rubric=[invalid]))

    def test_missing_or_duplicate_assessments_never_default_to_zero(self):
        for rubric in [[], [rubric_judgment(), rubric_judgment()], [rubric_judgment(status="unresolved")]]:
            with self.subTest(rubric=rubric):
                with self.assertRaises(ValueError):
                    grade(self.question, dict(self.result, rubric=rubric))

    def test_validated_contradiction_cannot_be_ignored_by_completeness_judgment(self):
        self.result["matches"] = [dict(id="transition", status="conflict")]
        invalid = rubric_judgment(status="complete", missing="")
        corrected = rubric_judgment(status="contradiction")
        rubric = self.assess(invalid, corrected)
        self.assertEqual(grade(self.question, dict(self.result, rubric=rubric)), {"transition": "conflict"})

    def test_each_requested_fact_gets_its_own_assessment(self):
        self.question["examiner_material"]["facts"].append(dict(id="delivery", relation="delivers"))
        rubric = self.assess(rubric_judgment(), rubric_judgment(fact_id="delivery", status="complete", missing=""))
        self.assertEqual(score(grade(self.question, dict(self.result, rubric=rubric))), 75)

    def test_service_failure_is_unresolved(self):
        with self.assertRaises(ModelServiceError):
            self.assess(RuntimeError("Model unavailable"))
        self.assertEqual(self.models.client.chat.call_count, 1)


if __name__ == "__main__":
    unittest.main()
