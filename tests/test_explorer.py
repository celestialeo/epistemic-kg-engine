import copy
import json
from pathlib import Path
import tempfile
import unittest
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

from pipeline.cli import main
from pipeline.explorer import create_app, load_snapshot
from pipeline.graph_match import GraphMatcher, batch_schema
from pipeline.models import ModelResponseError, OutputLimitError


def graph_fixture():
    return dict(run_id="fixture", nodes=[
        dict(id="water", label="Water", kind="concept", origin="document", definition="Liquid water"),
        dict(id="soil", label="Soil", kind="concept", origin="document", aliases=["ground"]),
    ], edges=[dict(id="entry", source="water", target="soil", label="enters", origin="document",
                   evidence="Water can enter soil when pores are available.", modality="can",
                   conditions="when pores are available", verification_basis="quote_entailment_model_review")])


class FixtureModels:
    options = {"num_ctx": 8192, "num_predict": 4096}

    def __init__(self, respond=None):
        self.requests = []
        self.respond = respond or (lambda payload: [])

    def ask(self, role, instruction, payload, schema, entity_id, validator=None):
        self.requests.append((role, instruction, payload))
        if role == "explorer_parse":
            value = dict(concepts=["water", "ground"], assertions=[payload["input"]])
        else:
            value = dict(matches=self.respond(payload))
        result = schema.model_validate(value)
        if validator:
            validator(result)
        return result


def result_for(kind="edge", identifier="entry", status="match", quote="Water"):
    return dict(kind=kind, id=identifier, status=status, input_quote=quote, reason="Fixture semantic decision")


class MatcherTests(unittest.TestCase):
    def test_paraphrase_returns_existing_ids_evidence_and_preserves_graph(self):
        graph = graph_fixture()
        before = copy.deepcopy(graph)
        model = FixtureModels(lambda p: [result_for(quote="Water soaks into the ground")])
        result = GraphMatcher(graph, model).match("Water soaks into the ground")
        self.assertEqual(result["matches"][0]["id"], "entry")
        self.assertEqual(result["matches"][0]["record"]["evidence"], graph["edges"][0]["evidence"])
        self.assertEqual(graph, before)
        payload = model.requests[-1][2]
        edge = next(r["record"] for r in payload["records"] if r["kind"] == "edge")
        self.assertEqual(edge["source"]["label"], "Water")
        self.assertEqual(edge["target"]["label"], "Soil")
        self.assertNotIn("id", edge["source"])
        self.assertNotIn("id", edge["target"])
        self.assertEqual(edge["modality"], "can")
        self.assertEqual(edge["conditions"], "when pores are available")

    def test_no_match_and_conflict_are_distinct(self):
        empty = GraphMatcher(graph_fixture(), FixtureModels()).match("An unrelated statement")
        self.assertEqual(empty["matches"], [])
        model = FixtureModels(lambda p: [result_for(status="conflict", quote="Water never enters soil")])
        result = GraphMatcher(graph_fixture(), model).match("Water never enters soil")
        self.assertEqual(result["matches"][0]["status"], "conflict")

    def test_invalid_ids_wrong_kinds_duplicate_ids_and_unquoted_input_fail(self):
        for rows in ([result_for(identifier="invented")], [result_for(kind="node")],
                     [result_for(), result_for()], [result_for(quote="invented text")],
                     [result_for(kind="node", identifier="water", status="conflict")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                GraphMatcher(graph_fixture(), FixtureModels(lambda p: rows)).match("Water enters soil")

    def test_all_records_are_checked_across_batches_and_output_limit_splits(self):
        graph = graph_fixture()
        graph["nodes"] += [dict(id=f"n{i}", label=f"Unrelated concept {i}", definition="x" * 100,
                               kind="concept", origin="document") for i in range(15)]
        checked = []

        def respond(payload):
            if len(payload["records"]) > 2:
                raise OutputLimitError("fixture output limit")
            checked.extend((r["kind"], r["record"]["id"]) for r in payload["records"])
            return []
        result = GraphMatcher(graph, FixtureModels(respond)).match("Water enters soil")
        self.assertEqual(result["checked_records"], len(graph["nodes"]) + len(graph["edges"]))
        self.assertEqual(len(checked), result["checked_records"])
        self.assertEqual(len(set(checked)), len(checked))

    def test_oversized_record_fails_without_silent_truncation(self):
        graph = graph_fixture()
        graph["nodes"][0]["definition"] = "x" * 20000
        with self.assertRaisesRegex(ValueError, "context"):
            GraphMatcher(graph, FixtureModels()).match("Water")

    def test_edge_batch_schema_excludes_nested_node_ids(self):
        records = GraphMatcher(graph_fixture(), FixtureModels()).records
        schema = batch_schema([records[-1]])
        schema.model_validate(dict(matches=[result_for()]))
        with self.assertRaises(ValueError):
            schema.model_validate(dict(matches=[result_for(kind="node", identifier="water")]))
        # In a mixed batch, kind and ID must still belong to the same record.
        with self.assertRaises(ValueError):
            batch_schema(records).model_validate(dict(matches=[result_for(kind="edge", identifier="water")]))

    def test_validation_exhaustion_splits_without_losing_records(self):
        checked = []
        def respond(payload):
            if len(payload["records"]) > 1:
                raise ModelResponseError("Invalid IDs after retries")
            row = payload["records"][0]
            checked.append(row["record"]["id"])
            return [result_for(kind=row["kind"], identifier=row["record"]["id"])]
        result = GraphMatcher(graph_fixture(), FixtureModels(respond)).match("Water")
        self.assertCountEqual(checked, ["water", "soil", "entry"])
        self.assertEqual(len(result["matches"]), 3)

    def test_single_record_validation_failure_is_not_hidden(self):
        def respond(payload):
            raise ModelResponseError("Still invalid")
        with self.assertRaisesRegex(ModelResponseError, "Still invalid"):
            GraphMatcher(graph_fixture(), FixtureModels(respond)).match("Water")

    def test_service_failure_does_not_split_or_retry_batches(self):
        model = FixtureModels(lambda payload: (_ for _ in ()).throw(RuntimeError("Service offline")))
        with self.assertRaisesRegex(RuntimeError, "Service offline"):
            GraphMatcher(graph_fixture(), model).match("Water")
        self.assertEqual(len(model.requests), 2)

    def test_empty_graph_does_not_call_model(self):
        model = FixtureModels()
        self.assertEqual(GraphMatcher(dict(nodes=[], edges=[]), model).match("Water")["matches"], [])
        self.assertEqual(model.requests, [])


class ExplorerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        (self.run / "artifacts").mkdir(parents=True)
        (self.run / "manifest.json").write_text(json.dumps(dict(status="completed", reconstruction_score=87,
                                                             config={})), encoding="utf-8")
        (self.run / "artifacts/graph.json").write_text(json.dumps(graph_fixture()), encoding="utf-8")

    def app(self, factory=None, runs=None):
        return create_app(runs or [self.run], model_factory=factory or (lambda s, t: FixtureModels()))

    def test_page_query_assets_and_saved_artifacts_remain_unchanged(self):
        before = {p: p.read_bytes() for p in self.run.rglob("*") if p.is_file()}
        with TestClient(self.app(lambda s, t: FixtureModels(lambda p: [result_for()])),
                        base_url="http://127.0.0.1") as client:
            page = client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertIn('id="query-form"', page.text)
            self.assertIn("87.00 / 100", page.text)
            self.assertEqual(client.get("/explorer.js").status_code, 200)
            self.assertEqual(client.get("/explorer.css").status_code, 200)
            result = client.post("/runs/0/match", json=dict(text="Water enters soil"))
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["matches"][0]["id"], "entry")
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        logs = list((self.run / "explorer_sessions").glob("*/events.jsonl"))
        self.assertEqual(len(logs), 1)
        self.assertIn('"explorer.closed"', logs[0].read_text(encoding="utf-8"))

    def test_browsing_without_model_is_logged_to_corresponding_run_and_retries_deduplicate(self):
        other = self.root / "other"
        (other / "artifacts").mkdir(parents=True)
        (other / "manifest.json").write_bytes((self.run / "manifest.json").read_bytes())
        (other / "artifacts/graph.json").write_bytes((self.run / "artifacts/graph.json").read_bytes())
        def no_model(*args):
            self.fail("Browsing must not initialize the model")
        with TestClient(self.app(no_model, [self.run, other]), base_url="http://127.0.0.1") as client:
            for index, action in enumerate(["select", "zoom"]):
                batch = dict(page_id=str(uuid.uuid4()), events=[dict(sequence=1,
                    timestamp="2026-10-25T12:00:00Z", action=action, details={"id": "water"})])
                for _ in range(2):
                    self.assertEqual(client.post(f"/runs/{index}/events", json=batch).status_code, 200)
        for run, action in [(self.run, "select"), (other, "zoom")]:
            logs = list((run / "explorer_sessions").glob("*/events.jsonl"))
            self.assertEqual(len(logs), 1)
            rows = [json.loads(line) for line in logs[0].read_text().splitlines()]
            self.assertEqual(rows[0]["data"]["source_run"], str(run.resolve()))
            interactions = [row for row in rows if row["event"] == "explorer.interaction"]
            self.assertEqual([row["data"]["action"] for row in interactions], [action])

    def test_interaction_validation_and_origin(self):
        batch = dict(page_id=str(uuid.uuid4()), events=[dict(sequence=1,
                     timestamp="now", action="page_open", details={})])
        with TestClient(self.app(), base_url="http://127.0.0.1") as client:
            self.assertEqual(client.post("/runs/9/events", json=batch).status_code, 404)
            self.assertEqual(client.post("/runs/0/events", json=batch,
                headers={"Origin": "https://unrelated.example"}).status_code, 403)
            batch["events"][0]["action"] = "model.response"
            self.assertEqual(client.post("/runs/0/events", json=batch).status_code, 422)
            batch["events"][0]["action"] = "search"
            batch["events"][0]["details"] = {"text": "x" * 40000}
            self.assertEqual(client.post("/runs/0/events", json=batch).status_code, 422)
        self.assertFalse((self.run / "explorer_sessions").exists())

    def test_browsing_saves_during_model_call_and_query_failure_is_correlated(self):
        entered, release = threading.Event(), threading.Event()
        def factory(snapshot, trace):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test timed out")
            raise RuntimeError("Ollama unavailable")
        with TestClient(self.app(factory), base_url="http://127.0.0.1") as client:
            with ThreadPoolExecutor() as pool:
                pending = pool.submit(client.post, "/runs/0/match", json={"text": "Water"})
                try:
                    self.assertTrue(entered.wait(5))
                    batch = dict(page_id=str(uuid.uuid4()), events=[dict(sequence=1,
                                 timestamp="now", action="pan", details={"pan_x": 10})])
                    self.assertEqual(client.post("/runs/0/events", json=batch).status_code, 200)
                    log = next((self.run / "explorer_sessions").glob("*/events.jsonl"))
                    self.assertIn('"explorer.interaction"', log.read_text())
                finally:
                    release.set()
                self.assertEqual(pending.result().status_code, 503)
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([row["sequence"] for row in rows], list(range(1, len(rows)+1)))
        query = next(row for row in rows if row["event"] == "explorer.query")
        error = next(row for row in rows if row["event"] == "explorer.error")
        self.assertEqual(error["parent_id"], query["event_id"])

    def test_validation_unknown_run_and_foreign_origin(self):
        with TestClient(self.app(), base_url="http://127.0.0.1") as client:
            for text in ("", "   ", "x" * 1501):
                self.assertEqual(client.post("/runs/0/match", json=dict(text=text)).status_code, 422)
            self.assertEqual(client.post("/runs/9/match", json=dict(text="Water")).status_code, 404)
            self.assertEqual(client.post("/runs/0/match", json=dict(text="Water"),
                                         headers={"Origin": "https://unrelated.example"}).status_code, 403)
            self.assertEqual(client.post("/runs/0/match", json=dict(text="Water"),
                                         headers={"Origin": "http://127.0.0.1"}).status_code, 200)

    def test_model_startup_failure_can_retry(self):
        attempts = []
        def factory(snapshot, trace):
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError("Ollama unavailable")
            return FixtureModels()
        with TestClient(self.app(factory), base_url="http://127.0.0.1") as client:
            self.assertEqual(client.post("/runs/0/match", json=dict(text="Water")).status_code, 503)
            self.assertEqual(client.post("/runs/0/match", json=dict(text="Water")).json()["matches"], [])

    def test_invalid_model_output_is_error_not_no_match(self):
        with TestClient(self.app(lambda s, t: FixtureModels(lambda p: [result_for(identifier="invented")])),
                        base_url="http://127.0.0.1") as client:
            response = client.post("/runs/0/match", json=dict(text="Water"))
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("matches", response.json())

    def test_completed_with_issues_is_visible_and_unfinished_run_is_rejected(self):
        manifest = self.run / "manifest.json"
        manifest.write_text(json.dumps(dict(status="completed_with_issues", reconstruction_score=None)), encoding="utf-8")
        with TestClient(self.app(), base_url="http://127.0.0.1") as client:
            self.assertIn("completed with issues", client.get("/").text)
            self.assertIn("unresolved", client.get("/").text)
        manifest.write_text(json.dumps(dict(status="running")), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "completed run"):
            load_snapshot(self.run)

    def test_multiple_graphs_have_separate_routes(self):
        with TestClient(self.app(runs=[self.run, self.run]), base_url="http://127.0.0.1") as client:
            self.assertIn("Choose a graph", client.get("/").text)
            self.assertIn('data-endpoint="/runs/1/match"', client.get("/runs/1").text)
            self.assertEqual(client.get("/runs/-1").status_code, 404)


class ExplorerDispatchTests(unittest.TestCase):
    def test_default_launch_is_after_all_chapters_and_preserves_exit_code(self):
        order = []
        def run(args):
            order.append(args.chapter)
            args.completed_run_directory = Path(args.chapter)
            return 2 if args.chapter == "water-cycle" else 0
        def serve(runs, **kwargs):
            self.assertEqual(order, ["neuroscience", "water-cycle"])
            self.assertEqual(runs, [Path("neuroscience"), Path("water-cycle")])
            self.assertEqual(kwargs, dict(port=8765, open_browser=False))
        with patch("pipeline.cli.run_chapter", side_effect=run), patch("pipeline.explorer.serve", side_effect=serve) as server:
            self.assertEqual(main(["--chapter", "both", "--no-open", "--explorer-port", "8765"]), 2)
            server.assert_called_once()

    def test_skip_flag_and_failed_run_do_not_start_server(self):
        def run(args):
            args.completed_run_directory = Path("run")
            return 0
        with patch("pipeline.cli.run_chapter", side_effect=run), patch("pipeline.explorer.serve") as server:
            self.assertEqual(main(["--no-explorer"]), 0)
            server.assert_not_called()
        with patch("pipeline.cli.run_chapter", return_value=1), patch("pipeline.explorer.serve") as server:
            self.assertEqual(main([]), 1)
            server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
