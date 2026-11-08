"""End-to-end HTTP flows with deterministic model responses at the model boundary."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from pipeline.explorer import create_app
from pipeline.student_store import StudentStore, grade
from pipeline.cli import main as pipeline_main
from pipeline.models import ModelResponseError


class TeachingModels:
    options = {"num_ctx": 8192, "num_predict": 4096}

    def __init__(self):
        self.calls = []
        self.fail = False

    def ask(self, role, instruction, payload, schema, entity_id, validator=None):
        self.calls.append(role)
        if self.fail:
            raise RuntimeError("Fixture model unavailable")
        if role == "quiz_question":
            value = dict(question="Explain " + payload["material"]["subject"]["label"] + ".",
                         expected_answer="Water enters soil.",
                         assessed_fact_ids=[f["id"] for f in payload["material"]["facts"]])
        elif role == "quiz_question_review":
            value = dict(plain_exam_language=True, open_question=True, grounded_in_material=True,
                         reveals_answer=False, answer_leak_quote="", reason="Open and grounded.")
        elif role in {"quiz_hint", "quiz_reveal"}:
            value = dict(text="Think about where water goes." if role == "quiz_hint" else "Water enters soil.")
        elif role == "quiz_statements":
            value = dict(statements=[dict(text=payload["learner_answer"], is_assertion=True)])
        elif role == "quiz_meaning":
            text = payload["statement"]["text"]
            value = dict(judgments=[])
            if "Water" in text and "soil" in text:
                value["judgments"] = [dict(statement_id=payload["statement"]["id"], edge_id=fact["id"],
                    meaning="contradiction" if "never" in text else "equivalent", asserts_relation=True,
                    source_identified=True, target_identified=True,
                    source_quote="Water", target_quote="soil", relation_quote="never enters" if "never" in text else "enters",
                    reason="Fixture semantic assessment.") for fact in payload["facts"] if fact["id"] == "entry"]
        elif role == "quiz_rubric":
            statement = payload["statements"][0]
            value = dict(fact_id=payload["fact"]["id"],
                         status="contradiction" if "never" in statement["text"] else "complete",
                         evidence=[dict(statement_id=statement["id"], quote=statement["text"])],
                         demonstrated="The learner explains the movement.", missing="")
        else:
            raise AssertionError("Unexpected model role: " + role)
        result = schema.model_validate(value)
        if validator:
            validator(result)
        return result


def write_run(root, topic="water", name="run_01", timestamp="2026-10-29T12:00:00+00:00", status="completed"):
    run = root / topic / name
    (run / "artifacts").mkdir(parents=True)
    manifest = dict(status=status, run_id=name, started_at=timestamp, started_at_utc=timestamp,
                    config=dict(chapter=topic, input=f"data/{topic}.txt"))
    graph = dict(run_id=name, nodes=[
        dict(id="water", label="Water", kind="concept", origin="document", definition="Liquid water"),
        dict(id="soil", label="Soil", kind="concept", origin="document", definition="Soil")],
        edges=[dict(id="entry", source="water", target="soil", label="enters", origin="document",
                    definition="The subject moves into the object.", evidence="Water enters soil.")])
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run / "artifacts/graph.json").write_text(json.dumps(graph), encoding="utf-8")
    return run


class ProfessorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.run = write_run(self.runs)
        self.db = self.root / "students.sqlite3"
        self.models = TeachingModels()
        self.client = self.new_client()
        self.student = self.post("students", dict(name="Ada"))["id"]
        self.topic = self.client.get("/api/professor/catalog").json()["topics"][0]

    def new_client(self):
        client = TestClient(create_app([], professor_store=StudentStore(self.db), runs_root=self.runs,
                           model_factory=lambda s, t: self.models), base_url="http://127.0.0.1")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def post(self, path, body, expected=200):
        response = self.client.post("/api/professor/" + path, json=body)
        self.assertEqual(response.status_code, expected, response.text)
        return response.json()

    def command(self, action, state=None, **kwargs):
        body = dict(action=action, request_id=str(uuid.uuid4()), **kwargs)
        if state:
            body.update(session_id=state["id"], question_id=state["state"]["question"]["id"])
        if action == "start":
            body.update(student_id=self.student, run_id=self.topic["id"])
        return self.post("quiz", body)

    def analytics(self, student=True):
        return self.client.get("/api/professor/analytics" + ("?student_id="+self.student if student else "")).json()

    def test_complete_personalized_flow_restart_override_and_class_analytics(self):
        original = {p: p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        other = self.post("students", dict(name="Grace"))["id"]
        state = self.command("start", review_mode=True)
        self.assertNotIn("expected_answer", state["state"]["question"])
        self.assertEqual(self.analytics()["topics"][0]["score"], None)
        state = self.command("hint", state)
        state = self.command("answer", state, text="Water never enters soil.")
        self.assertEqual(state["answer_score"], 0)
        initial_id = state["id"]
        calls = len(self.models.calls)
        self.client = self.new_client()
        restored = self.client.get("/api/professor/sessions/" + initial_id).json()
        self.assertEqual(restored["state"]["question"]["id"], state["state"]["question"]["id"])
        self.assertEqual(len(self.models.calls), calls)
        answer = restored["answers"][0]
        self.post("answers/"+answer["id"]+"/override", dict(marks={"entry":"related"},
                    feedback="Partially correct after review.", reason="Professor interpretation of the answer."))
        revised = self.client.get("/api/professor/sessions/"+initial_id).json()
        self.assertEqual(revised["answers"][0]["score"], 50)
        self.assertEqual(revised["answers"][0]["original_score"], 0)
        self.assertEqual(revised["state"]["edge_status"]["entry"], "related")
        self.assertIn("Professor review", revised["state"]["question"]["feedback"])
        for _ in range(4):
            state = self.command("next", state)
            state = self.command("answer", state, text="Water enters soil.")
        self.assertTrue(state["state"]["completed"])
        report = self.analytics()
        self.assertEqual(report["topics"][0]["score"], 90)
        self.assertEqual(report["answer_count"], 5)
        self.assertEqual(report["topics"][0]["completed_count"], 1)
        self.assertEqual(report["topics"][0]["coverage"][0]["independent"], 1)
        class_report = self.analytics(False)
        self.assertEqual(class_report["topics"][0]["unassessed_students"], 1)
        self.assertEqual(class_report["topics"][0]["score"], 90)
        other_report = self.client.get("/api/professor/analytics?student_id="+other).json()
        self.assertEqual(other_report["weakest"], [])
        self.assertEqual(other_report["unassessed"], ["water"])
        self.assertEqual({p: p.read_bytes() for p in original}, original)

    def test_latest_runs_refresh_without_mixing_fact_identity_or_losing_history(self):
        state = self.command("start")
        self.command("answer", state, text="Water enters soil.")
        write_run(self.runs, name="run_02", timestamp="2026-10-30T12:00:00+00:00")
        write_run(self.runs, name="run_03", timestamp="2026-10-31T12:00:00+00:00", status="failed")
        newest = self.client.get("/api/professor/catalog").json()["topics"][0]
        self.assertEqual(newest["run_name"], "run_02")
        self.assertNotEqual(newest["id"], self.topic["id"])
        report = self.analytics()["topics"][0]
        self.assertIsNone(report["score"])
        self.assertEqual(report["coverage"][0]["unassessed"], 0)
        self.assertEqual(report["trend"], [])
        self.assertEqual(StudentStore(self.db).history(self.student)[0]['run_id'], self.topic['id'])
        recommendation = self.client.get(f"/api/professor/recommendation/{self.student}/{newest['id']}").json()
        self.assertIn("All eligible", recommendation["reason"])
        self.assertEqual(self.client.get("/professor/graph/"+self.topic["id"]).status_code, 200)

    def test_retry_receipt_survives_restart_and_conflicting_id_is_rejected(self):
        start = dict(action="start", request_id=str(uuid.uuid4()), student_id=self.student, run_id=self.topic["id"])
        state = self.post("quiz", start)
        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text="Water enters soil.")
        result = self.post("quiz", body)
        self.client = self.new_client()
        calls = len(self.models.calls)
        self.assertEqual(self.post("quiz", body), result)
        self.assertEqual(self.post("quiz", start), state)
        self.assertEqual(len(self.models.calls), calls)
        self.assertEqual(self.analytics()["answer_count"], 1)
        self.post("quiz", dict(body, text="Something else"), 422)

    def test_failed_grading_saves_pending_answer_and_retry_survives_restart(self):
        state = self.command("start")
        before = StudentStore(self.db).session(state["id"])
        self.models.fail = True
        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text="Water enters soil.")
        failure = self.post("quiz", body, 503)
        self.assertIn("answer is saved and awaiting grading", failure["detail"])
        self.assertEqual(StudentStore(self.db).session(state["id"]), before)
        self.assertEqual(StudentStore(self.db).answers(), [])
        self.client = self.new_client()
        detail = self.client.get("/api/professor/sessions/"+state["id"]).json()
        pending = detail["pending_answers"]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["text"], body["text"])
        self.assertEqual(pending[0]["grading_status"], "pending")
        self.assertIsNone(pending[0]["score"])
        report = self.analytics()
        self.assertEqual(report["assessment_count"], 0)
        self.assertEqual(report["answer_count"], 0)
        self.assertEqual(report["topics"][0]["coverage"][0]["assessed"], 0)
        self.assertEqual(detail["state"]["question"]["attempts"], 0)
        self.post("quiz", dict(body, text="Changed answer"), 422)
        self.post("quiz", dict(body, request_id=str(uuid.uuid4())), 409)
        self.post("quiz", dict(action="next", request_id=str(uuid.uuid4()), session_id=state["id"],
                               question_id=body["question_id"]), 409)
        self.models.fail = False
        result = self.post("quiz", pending[0]["request"])
        self.assertEqual(result["answer_score"], 100)
        self.assertEqual(self.post("quiz", body), result)
        self.assertEqual(len(StudentStore(self.db).answers()), 1)
        self.assertEqual(StudentStore(self.db).pending_answers(state["id"]), [])
        self.assertEqual(result["state"]["question"]["attempts"], 1)

    def test_model_startup_failure_still_saves_submission(self):
        state = self.command("start")
        self.client = self.new_client()
        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text="Water enters soil.")
        with patch("pipeline.explorer.GraphMatcher", side_effect=RuntimeError("Cannot load model")):
            self.post("quiz", body, 503)
        self.assertEqual(StudentStore(self.db).pending_answers(state["id"])[0]["text"], body["text"])
        self.post("quiz", body)
        self.assertEqual(len(StudentStore(self.db).answers()), 1)

    def test_citation_failure_is_pending_not_a_grade(self):
        state = self.command("start")
        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text="Water enters soil.")
        for failure in [ModelResponseError("Invalid citation after retries"),
                        ValueError("Context too small"), KeyError("Missing model configuration")]:
            with self.subTest(failure=type(failure).__name__):
                with patch("pipeline.quiz_grading.QuizGrader.match", side_effect=failure):
                    self.post("quiz", body, 503)
        self.assertIsNone(self.analytics()["topics"][0]["score"])
        self.assertEqual(StudentStore(self.db).answers(), [])
        self.assertEqual(len(StudentStore(self.db).pending_answers(state["id"])), 1)
        result = self.post("quiz", body)
        self.assertEqual(result["state"]["edge_status"], {"entry": "match"})

    def test_question_citation_failure_can_retry_saved_answer_after_restart_once(self):
        from tests.test_quiz_grading import models_with, repair
        original = self.models.ask
        invalid = dict(judgments=[dict(statement_id='statement_1', edge_id='entry', meaning='equivalent',
            asserts_relation=True, source_identified=True, target_identified=True,
            source_quote='Water', target_quote='soil', relation_quote='infiltrates',
            reason='The statement describes the movement.')])
        failed_repair = dict(judgments=[repair('Water enters soil.', **invalid['judgments'][0])])
        corrected = dict(judgments=[repair('Water enters soil.', **dict(invalid['judgments'][0], relation_quote='enters'))])
        grader_models = models_with(invalid, failed_repair, failed_repair, failed_repair)

        def respond(role, instruction, payload, schema, entity_id, validator=None):
            if role == 'quiz_question':
                result = schema.model_validate(dict(question='Explain how water infiltrates soil.',
                    expected_answer='Water enters soil.', assessed_fact_ids=['entry']))
                if validator:
                    validator(result)
                return result
            if role == 'quiz_meaning':
                return grader_models.ask(role, instruction, payload, schema, entity_id, validator)
            return original(role, instruction, payload, schema, entity_id, validator)

        with patch.object(self.models, 'ask', side_effect=respond):
            state = self.command('start')
            before = StudentStore(self.db).session(state['id'])
            body = dict(action='answer', request_id=str(uuid.uuid4()), session_id=state['id'],
                        question_id=state['state']['question']['id'], text='Water enters soil.')
            failure = self.post('quiz', body, 503)
            self.assertIn('relation_span', failure['detail'])
            self.assertIn('learner token indices', failure['detail'])
            store = StudentStore(self.db)
            self.assertEqual(store.session(state['id']), before)
            self.assertEqual(store.answers(), [])
            self.assertEqual(store.knowledge(self.student, self.topic['id']), {})
            self.assertEqual(len(store.pending_answers(state['id'])), 1)
            self.client = self.new_client()
            saved = self.client.get('/api/professor/sessions/'+state['id']).json()
            self.assertEqual(saved['pending_answers'][0]['request']['request_id'], body['request_id'])
            self.post('quiz', dict(body, request_id=str(uuid.uuid4())), 409)
            grader_models = models_with(invalid, corrected)
            result = self.post('quiz', saved['pending_answers'][0]['request'])
            self.assertEqual(result['answer_score'], 100)
            calls = grader_models.client.chat.call_count
            self.assertEqual(self.post('quiz', body), result)
            self.assertEqual(grader_models.client.chat.call_count, calls)
            self.assertEqual(len(store.answers()), 1)
            self.assertEqual(store.answers()[0]['id'], body['request_id'])
            self.assertEqual(store.pending_answers(state['id']), [])

    def test_commit_failure_retains_pending_answer_and_original_checkpoint(self):
        state = self.command("start")
        before = StudentStore(self.db).session(state["id"])
        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text="Water enters soil.")
        with StudentStore(self.db).connect() as db:
            db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON requests BEGIN SELECT RAISE(FAIL, 'write failed'); END")
        self.post("quiz", body, 503)
        store = StudentStore(self.db)
        self.assertEqual(store.session(state["id"]), before)
        self.assertEqual(store.answers(), [])
        self.assertEqual(len(store.pending_answers(state["id"])), 1)
        with store.connect() as db:
            db.execute("DROP TRIGGER fail_receipt")
        self.post("quiz", body)
        self.assertEqual(len(store.answers()), 1)
        self.assertEqual(store.pending_answers(state["id"]), [])

    def test_rubric_failure_preserves_submission_without_scoring_or_advancing(self):
        state = self.command("start")
        store = StudentStore(self.db)
        before = store.session(state["id"])
        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text="Water enters soil.")
        with patch("pipeline.quiz.assess_rubric", side_effect=ModelResponseError("Rubric evidence unresolved")):
            self.post("quiz", body, 503)
        self.assertEqual(store.session(state["id"]), before)
        self.assertEqual(store.answers(), [])
        self.assertEqual(store.pending_answers(state["id"])[0]["text"], body["text"])
        self.assertIsNone(self.analytics()["topics"][0]["score"])
        self.client = self.new_client()
        result = self.post("quiz", body)
        self.assertEqual(result["answer_score"], 100)
        self.assertEqual(self.post("quiz", body), result)
        self.assertEqual(len(store.answers()), 1)
        self.assertEqual(store.pending_answers(state["id"]), [])

    def test_partial_rubric_colors_partial_without_inventing_mastery_on_reload_or_next_quiz(self):
        run = write_run(self.runs, name="run_02", timestamp="2026-10-30T12:00:00+00:00")
        graph_file = run / "artifacts/graph.json"
        graph = json.loads(graph_file.read_text(encoding="utf-8"))
        graph["edges"].append(dict(id="approach", source="water", target="soil", label="moves_toward",
            definition="The subject moves closer to the object without necessarily entering it.", origin="document"))
        graph_file.write_text(json.dumps(graph), encoding="utf-8")
        self.topic = self.client.get("/api/professor/catalog").json()["topics"][0]
        original = self.models.ask

        def respond(role, instruction, payload, schema, entity_id, validator=None):
            if role == "quiz_question":
                value = dict(question="Explain how water reaches the inside of soil.",
                             expected_answer="Water enters soil.", assessed_fact_ids=["entry"])
            elif role == "quiz_meaning":
                value = dict(judgments=[dict(statement_id=payload["statement"]["id"], edge_id="approach",
                    meaning="equivalent", asserts_relation=True, source_identified=True, target_identified=True,
                    source_quote="Water", target_quote="soil", relation_quote="moves toward", reason="Movement closer.")])
            elif role == "quiz_rubric":
                value = dict(fact_id="entry", status="partial",
                    evidence=[dict(statement_id="statement_1", quote="Water moves toward soil.")],
                    demonstrated="Movement toward soil is described.", missing="Entry into the soil is not stated.")
            else:
                return original(role, instruction, payload, schema, entity_id, validator)
            result = schema.model_validate(value)
            if validator:
                validator(result)
            return result

        with patch.object(self.models, "ask", side_effect=respond):
            state = self.command("start")
            result = self.command("answer", state, text="Water moves toward soil.")
            self.assertEqual(result["answer_score"], 50)
            self.assertEqual(result["state"]["edge_status"], {"approach": "match", "entry": "related"})
            self.assertIn("Partly answered", result["state"]["question"]["feedback"])
            self.assertIn("Entry into the soil is not stated", result["state"]["question"]["feedback"])
            stored = StudentStore(self.db).answers()[0]
            self.assertEqual(stored["marks"], {"entry": "related"})
            self.assertEqual([m["id"] for m in stored["result"]["matches"]], ["approach"])
            self.client = self.new_client()
            restored = self.client.get("/api/professor/sessions/"+state["id"]).json()
            self.assertEqual(restored["state"]["edge_status"], {"approach": "match", "entry": "related"})
            another = self.command("start")
            self.assertEqual(another["state"]["edge_status"], {"approach": "match", "entry": "related"})
            coverage = self.analytics()["topics"][0]["coverage"][0]
            self.assertEqual((coverage["assessed"], coverage["independent"], coverage["unassessed"]), (2, 1, 0))

    def test_blank_and_stale_submissions_are_not_staged(self):
        state = self.command("start")
        body = dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text=" ")
        self.post("quiz", body, 422)
        self.post("quiz", dict(body, question_id=str(uuid.uuid4()), text="Water enters soil."), 422)
        self.assertEqual(StudentStore(self.db).pending_answers(state["id"]), [])

    def test_unassessed_weakness_assistance_and_revisions_are_distinct(self):
        write_run(self.runs, topic="unassessed-topic")
        self.client.get("/api/professor/catalog")
        state = self.command("start")
        state = self.command("reveal", state)
        self.assertEqual(self.analytics()["assessment_count"], 0)
        state = self.command("answer", state, text="Water never enters soil.")
        state = self.command("answer", state, text="Water enters soil.")
        report = self.analytics()
        self.assertEqual(report["assessment_count"], 1)
        self.assertEqual(report["answer_count"], 2)
        self.assertEqual(report["unassessed"], ["unassessed topic"])
        self.assertEqual(report["review_topics"], [])
        water = next(t for t in report["topics"] if t["title"] == "water")
        self.assertEqual(water["score"], 100)
        self.assertEqual(water["coverage"][0]["assisted"], 1)
        self.assertEqual(water["coverage"][0]["independent"], 0)

    def test_invalid_students_overrides_stale_questions_and_origins(self):
        self.post("students", dict(name="  "), 422)
        state = self.command("start")
        state = self.command("answer", state, text="Water enters soil.")
        answer = StudentStore(self.db).answers()[0]
        self.post("answers/"+answer["id"]+"/override", dict(marks={"invented":"match"}, feedback="x", reason="x"), 422)
        self.command("next", state)
        self.post("quiz", dict(action="answer", request_id=str(uuid.uuid4()), session_id=state["id"],
                    question_id=state["state"]["question"]["id"], text="Water enters soil."), 422)
        response = self.client.post("/api/professor/students", json={"name":"No"}, headers={"Origin":"https://other.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/professor/students/"+str(uuid.uuid4())+"/history").status_code, 404)

    def test_rubric_only_grades_facts_actually_asked(self):
        question = dict(examiner_material=dict(facts=[dict(id="asked")]), target_ids=["asked", "not_asked"])
        self.assertEqual(grade(question, dict(matches=[dict(id="not_asked",status="match")])), {"asked":"not_demonstrated"})

    def test_interact_opens_latest_completed_input_without_running_pipeline(self):
        latest = write_run(self.runs, name="run_02", timestamp="2026-10-30T12:00:00+00:00")
        write_run(self.runs, name="run_03", timestamp="2026-10-31T12:00:00+00:00", status="running")
        with patch("pipeline.cli.run_chapter") as run, patch("pipeline.professor.serve") as serve:
            self.assertEqual(pipeline_main(["--interact", "--input", "data/water.txt",
                "--output-root", str(self.runs), "--no-open", "--explorer-port", "8765"]), 0)
            run.assert_not_called()
            serve.assert_called_once_with(runs_root=self.runs, selected_run=latest.resolve(), port=8765, open_browser=False)

    def test_interact_missing_input_never_starts_a_pipeline_run(self):
        with patch("pipeline.cli.run_chapter") as run, patch("pipeline.professor.serve") as serve:
            with self.assertRaises(SystemExit) as raised:
                pipeline_main(["--interact", "--chapter", "ai-test", "--output-root", str(self.runs)])
            self.assertEqual(raised.exception.code, 2)
            run.assert_not_called()
            serve.assert_not_called()

    def test_personalization_prioritizes_demonstrated_gap(self):
        state = self.command("start")
        self.command("answer", state, text="Water never enters soil.")
        result = self.client.get(f"/api/professor/recommendation/{self.student}/{self.topic['id']}").json()
        self.assertEqual(result["reason"], "Review previously assessed gaps")
        chosen = self.topic["concepts"][0]["id"]
        start = self.command("start", focus_id=chosen)
        self.assertEqual(StudentStore(self.db).session(start["id"])["checkpoint"]["root"], chosen)

    def test_class_scores_weight_students_equally_and_trend_tracks_progress(self):
        for _ in range(2):
            state = self.command("start", review_mode=True)
            self.command("answer", state, text="Water enters soil.")
        self.student = self.post("students", dict(name="Grace"))["id"]
        state = self.command("start")
        self.command("answer", state, text="Water never enters soil.")
        report = self.analytics(False)["topics"][0]
        self.assertEqual(report["score"], 50)
        self.assertEqual([point["score"] for point in report["class_trend"]], [100, 100, 50])
        self.assertEqual(report["assessment_count"], 3)
        self.assertEqual(report["assessed_students"], 2)

    def test_later_answer_supersedes_earlier_override_without_erasing_audit(self):
        state = self.command("start")
        self.command("answer", state, text="Water never enters soil.")
        answer = StudentStore(self.db).answers()[0]
        self.post("answers/"+answer["id"]+"/override", dict(marks={"entry":"related"},
                    feedback="Partial after review.", reason="Review note."))
        self.command("answer", state, text="Water enters soil.")
        restored = self.client.get("/api/professor/sessions/"+state["id"]).json()
        self.assertEqual(restored["state"]["edge_status"]["entry"], "match")
        self.assertNotIn("Professor review", restored["state"]["question"]["feedback"])
        self.assertEqual(len(restored["answers"][0]["overrides"]), 1)
        self.assertEqual(self.analytics()["topics"][0]["score"], 100)

    def test_history_and_graph_survive_source_run_removal(self):
        state = self.command("start")
        self.command("answer", state, text="Water enters soil.")
        # Move a fixture only; real pipeline outputs are never changed by the dashboard.
        (self.run / "manifest.json").rename(self.root / "archived_manifest.json")
        (self.run / "artifacts/graph.json").rename(self.root / "archived_graph.json")
        self.client = self.new_client()
        self.assertEqual(self.client.get("/api/professor/sessions/"+state["id"]).status_code, 200)
        self.assertEqual(self.client.get("/professor/graph/"+self.topic["id"]).status_code, 200)


if __name__ == "__main__":
    unittest.main()
