"""Optional run-isolated Neo4j export of the saved graph, with query tracing."""
import json
import os
import subprocess
import time
from urllib.parse import urlsplit


def preflight(trace, root, start=False):
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user, password = os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DB", "neo4j")
    if not password:
        raise ValueError("NEO4J_PASSWORD is required for --neo4j")
    if urlsplit(uri).username or urlsplit(uri).password:
        raise ValueError("Use separate NEO4J_USER/NEO4J_PASSWORD, not credentials in NEO4J_URI")
    if start:
        if urlsplit(uri).hostname not in {"localhost", "127.0.0.1"} or urlsplit(uri).port != 7687:
            raise ValueError("--start-neo4j requires a local Neo4j URI on port 7687")
        if user != "neo4j" or database != "neo4j":
            raise ValueError("Bundled Neo4j requires user and database neo4j")
        command = ["docker", "compose", "-f", str(root / "compose.yaml"), "up", "-d", "neo4j"]
        request = trace.emit("process.started", command=command)
        result = subprocess.run(command, cwd=root, capture_output=True, text=True, timeout=120)
        trace.emit("process.completed", parent_id=request, returncode=result.returncode,
                   stdout=result.stdout, stderr=result.stderr)
        result.check_returncode()
    driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5)
    deadline = time.monotonic() + (120 if start else 0)
    try:
        while True:
            request = trace.emit("database.connect_requested", uri=uri, database=database)
            try:
                driver.verify_connectivity()
                trace.emit("database.connected", parent_id=request)
                break
            except Exception as exc:
                trace.emit("database.connect_failed", parent_id=request, error=str(exc))
                if time.monotonic() >= deadline:
                    raise
                time.sleep(3)
    except BaseException:
        driver.close()
        raise
    return driver


def export_graph(graph, driver, trace):
    database = os.getenv("NEO4J_DB", "neo4j")
    node_rows = [{"id": n["id"], "label": n["label"], "kind": n["kind"], "origin": n["origin"],
                  "properties_json": json.dumps(n, ensure_ascii=False)} for n in graph["nodes"]]
    edge_rows = [{**{k: e[k] for k in ("id", "source", "target", "label", "origin")},
                  "properties_json": json.dumps(e, ensure_ascii=False)} for e in graph["edges"]]
    statements = [
        ("UNWIND $rows AS row CREATE (n:PipelineNode {run_id: $run_id, id: row.id}) SET n += row RETURN count(n) AS count", node_rows),
        ("UNWIND $rows AS row MATCH (a:PipelineNode {run_id: $run_id, id: row.source}), "
         "(b:PipelineNode {run_id: $run_id, id: row.target}) "
         "CREATE (a)-[r:LINK {id: row.id, label: row.label, origin: row.origin, properties_json: row.properties_json}]->(b) "
         "RETURN count(r) AS count", edge_rows)]
    with driver.session(database=database) as session:
        trace.emit("database.transaction_started")
        with session.begin_transaction() as tx:
            try:
                for query, rows in statements:
                    parameters = {"run_id": trace.run_id, "rows": rows}
                    event = trace.emit("database.query_requested", query=query, parameters=parameters)
                    result = tx.run(query, parameters)
                    records = result.data()
                    counters = vars(result.consume().counters)
                    trace.emit("database.query_completed", parent_id=event, records=records, counters=counters)
                    if records[0]["count"] != len(rows):
                        raise ValueError("Database export count mismatch")
                tx.commit()
                trace.emit("database.transaction_committed", nodes=len(node_rows), edges=len(edge_rows))
            except BaseException as exc:
                tx.rollback()
                trace.emit("database.transaction_rolled_back", error=str(exc))
                raise
