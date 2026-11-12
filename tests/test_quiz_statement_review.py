"""Classification conflicts must preserve exact evidence and durable submissions."""
import json
import unittest
import uuid
from unittest.mock import patch

from pipeline.models import ModelResponseError, ModelServiceError
from pipeline.quiz_grading import QuizGrader, assess_rubric
from pipeline.student_store import StudentStore, grade
from tests import test_professor as professor_fixture
from tests.test_quiz_grading import graph_fixture, models_with, statements


def review(kind, statement_id="statement_1"):
    return dict(statement_id=statement_id, kind=kind, reason="Classified using the question and unchanged learner words.")


class StatementReviewTests(unittest.TestCase):
    def setUp(self):
        self.question = dict(text="What type of energy do photovoltaic cells produce?",
            expected_answer="electrical energy", examiner_material=dict(facts=[dict(id="e1",
                source="photovoltaic cell", target="electricity", relation="produces",
                definition="Converts light into electrical energy.")]))

    def complete(self, text, **changes):
        return dict(dict(fact_id="e1", status="complete", missing="",
            demonstrated="Names the requested output.",
            evidence=[dict(statement_id="statement_1", quote=text)]), **changes)

    def test_second_person_claim_is_reviewed_without_rewriting_or_borrowing_endpoints(self):
        text = "you are producing electrical energy"
        models = models_with(statements(text, False), review("assertion"), dict(judgments=[]), self.complete(text))
        result = QuizGrader(graph_fixture(), models).match(text, self.question["text"])
        statement = result["statements"][0]
        self.assertEqual((statement["text"], statement["start"], statement["end"]), (text, 0, len(text)))
        self.assertFalse(statement["initial_is_assertion"])
        self.assertTrue(statement["is_assertion"])
        self.assertEqual(result["matches"], [])
        rubric = assess_rubric(models, self.question, result)
        self.assertEqual(grade(self.question, dict(result, rubric=rubric)), {"e1": "match"})
        payload = json.loads(models.client.chat.call_args_list[1].kwargs["messages"][0]["content"].split("\nDATA:\n")[1])
        self.assertEqual(set(payload), {"statement", "question"})

    def test_short_answer_can_receive_rubric_credit_without_inventing_a_graph_match(self):
        text = "electrical energy"
        models = models_with(statements(text, False), review("answer_fragment"), self.complete(text))
        result = QuizGrader(graph_fixture(), models).match(text, self.question["text"])
        self.assertFalse(result["statements"][0]["is_assertion"])
        self.assertEqual(result["uncredited"][0]["reason_code"], "answer_fragment_rubric_only")
        self.assertEqual(result["matches"], [])
        self.assertEqual(assess_rubric(models, self.question, result)[0]["status"], "complete")
        self.assertEqual(models.client.chat.call_count, 3)

    def test_questions_help_and_unrelated_lists_are_excluded_from_rubric_evidence(self):
        for kind, text in [("question", "What is energy?"), ("help_request", "Please give me a hint"),
                           ("name_list", "Paris, mercury, cats"), ("other", "I don't know")]:
            with self.subTest(kind=kind):
                negative = self.complete(text, status="not_demonstrated", evidence=[], demonstrated="", missing="The requested output is not identified.")
                models = models_with(statements(text, False), review(kind), negative)
                result = QuizGrader(graph_fixture(), models).match(text, self.question["text"])
                self.assertEqual(result["matches"], [])
                self.assertEqual(assess_rubric(models, self.question, result)[0]["status"], "not_demonstrated")
                payload = json.loads(models.client.chat.call_args_list[2].kwargs["messages"][0]["content"].split("\nDATA:\n")[1])
                self.assertEqual(payload["statements"], [])
                self.assertEqual(payload["excluded_statements"][0]["text"], text)

    def test_failed_review_never_defaults_to_a_grade(self):
        text = "electrical energy"
        wrong = review("answer_fragment", "statement_99")
        for responses, error in [([wrong]*3, ModelResponseError), ([RuntimeError("offline")], ModelServiceError)]:
            with self.subTest(error=error):
                models = models_with(statements(text, False), *responses)
                with self.assertRaises(error):
                    QuizGrader(graph_fixture(), models).match(text, self.question["text"])

    def test_eligibility_does_not_allow_a_fabricated_quote(self):
        text = "electrical energy"
        invalid = self.complete("photovoltaic cells produce electrical energy")
        models = models_with(statements(text, False), review("answer_fragment"), invalid, self.complete(text))
        result = QuizGrader(graph_fixture(), models).match(text, self.question["text"])
        rubric = assess_rubric(models, self.question, result)
        self.assertEqual(rubric[0]["evidence"][0]["quote"], text)
        retry = models.client.chat.call_args_list[-1].kwargs["messages"][0]["content"]
        self.assertIn("does not occur verbatim in statement_1", retry)
        self.assertIn("Exact learner text: 'electrical energy'", retry)

    def test_complete_retry_explains_empty_missing_field(self):
        text = "electrical energy"
        models = models_with(statements(text, False), review("answer_fragment"),
                             self.complete(text, missing="None. The answer covers the request."), self.complete(text))
        result = QuizGrader(graph_fixture(), models).match(text, self.question["text"])
        self.assertEqual(assess_rubric(models, self.question, result)[0]["missing"], "")
        retry = models.client.chat.call_args_list[-1].kwargs["messages"][0]["content"]
        self.assertIn("missing must be exactly an empty string", retry)

    def test_reviewed_fragment_can_still_be_wrong(self):
        text = "thermal energy"
        models = models_with(statements(text, False), review("answer_fragment"),
            self.complete(text, status="contradiction", demonstrated="Gives a different output.", missing=""))
        result = QuizGrader(graph_fixture(), models).match(text, self.question["text"])
        rubric = assess_rubric(models, self.question, result)
        self.assertEqual(grade(self.question, dict(result, rubric=rubric)), {"e1": "conflict"})


class StatementReviewPersistenceTests(unittest.TestCase):
    setUp = professor_fixture.ProfessorTests.setUp
    new_client = professor_fixture.ProfessorTests.new_client
    post = professor_fixture.ProfessorTests.post
    command = professor_fixture.ProfessorTests.command

    def test_failed_classification_review_retries_once_after_restart_with_original_answer(self):
        state = self.command("start")
        store = StudentStore(self.db)
        before = store.session(state["id"])
        original = self.models.ask
        review_models = models_with(RuntimeError("Classification service unavailable"))

        def respond(role, instruction, payload, schema, entity_id, validator=None):
            if role == "quiz_statements":
                result = schema.model_validate(statements(payload["learner_answer"], False))
                if validator:
                    validator(result)
                return result
            if role == "quiz_statement_review":
                return review_models.ask(role, instruction, payload, schema, entity_id, validator=validator)
            return original(role, instruction, payload, schema, entity_id, validator=validator)

        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
            question_id=state["state"]["question"]["id"], text="Water enters soil.")
        with patch.object(self.models, "ask", side_effect=respond):
            failure = self.post("quiz", body, 503)
            self.assertIn("saved and awaiting grading", failure["detail"])
            self.assertEqual(store.session(state["id"]), before)
            self.assertEqual(store.answers(), [])
            self.client = self.new_client()
            saved = self.client.get("/api/professor/sessions/" + state["id"]).json()
            pending = saved["pending_answers"][0]
            self.assertEqual(pending["text"], body["text"])
            self.assertIsNone(pending["score"])
            self.assertEqual({key: pending["request"][key] for key in body}, body)
            review_models = models_with(review("assertion"))
            result = self.post("quiz", pending["request"])
            self.assertEqual(result["answer_score"], 100)
            self.assertEqual(self.post("quiz", body), result)
            self.assertEqual(review_models.client.chat.call_count, 1)
            self.assertEqual(len(store.answers()), 1)
            self.assertEqual(store.pending_answers(state["id"]), [])


if __name__ == "__main__":
    unittest.main()
