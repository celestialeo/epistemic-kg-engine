"""Configuration, preflight, execution, and presentation for the local pipeline."""
import argparse
from datetime import datetime, timezone
import html
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit
import uuid
import webbrowser

from .plan import build_plan

ROOT = Path(__file__).resolve().parents[1]


def read_chunks(path, limit):
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = data.get("chunks") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("Input must contain a nonempty 'chunks' list.")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("chunk_id"), str) or not row["chunk_id"].strip():
            raise ValueError("Every chunk needs a nonempty string chunk_id.")
        if row["chunk_id"] in seen:
            raise ValueError("Duplicate chunk_id: " + row["chunk_id"])
        seen.add(row["chunk_id"])
        if not isinstance(row.get("text"), str) or not row["text"].strip():
            raise ValueError("Every chunk needs nonempty text: " + row["chunk_id"])
    return rows[:limit] if limit else rows


def prepare_chunks(rows, source):
    return [{**row, "original_chunk_id": row["chunk_id"],
             "chunk_id": source + "::" + row["chunk_id"]} for row in rows]


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def validate_artifact(path, key, allow_empty=False):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get(key)
    if not isinstance(rows, list) or (not rows and not allow_empty):
        raise ValueError(f"{path.name}: expected nonempty list '{key}'.")
    errors = [row for row in rows if "error" in row]
    if errors:
        raise ValueError(f"{path.name}: {len(errors)}/{len(rows)} rows failed; inspect the artifact and log.")
    if key == "approved_edges":
        # The critic currently records failures as text and falls back to proposer
        # confidence. Do not silently call that a successfully reviewed run.
        scored = rows + data.get("rejected_edges", [])
        if any(str(row.get("critic_reason", "")).startswith("critic-error:") for row in scored):
            raise ValueError(f"{path.name}: background critic failed; inspect critic_reason fields.")


def check_dependencies():
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required (3.11 recommended). Create a new .venv with that Python.")
    modules = ["dotenv", "neo4j", "langchain_ollama", "pydantic", "numpy", "scipy"]
    missing = [name for name in modules if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("Missing dependencies: " + ", ".join(missing) +
                           ". Run: python -m pip install -r requirements.txt")


def load_environment():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    defaults = {"NEO4J_URI": "bolt://127.0.0.1:7687", "NEO4J_USER": "neo4j",
                "NEO4J_DB": "neo4j", "NEO4J_BROWSER_URL": "http://localhost:7474/browser/",
                "OLLAMA_HOST": "http://127.0.0.1:11434"}
    for key, value in defaults.items():
        os.environ.setdefault(key, value)
    if not os.getenv("NEO4J_PASSWORD"):
        raise RuntimeError("Copy .env.example to .env and set NEO4J_PASSWORD to your database password.")
    for key in ("NEO4J_URI", "NEO4J_BROWSER_URL"):
        if urlsplit(os.environ[key]).username or urlsplit(os.environ[key]).password:
            raise ValueError(f"Do not embed credentials in {key}; use NEO4J_USER and NEO4J_PASSWORD.")


def preflight(args):
    from neo4j import GraphDatabase
    from ollama import Client
    from langchain_ollama import OllamaEmbeddings

    if args.start_neo4j:
        uri = urlsplit(os.environ["NEO4J_URI"])
        if uri.hostname not in {"localhost", "127.0.0.1"} or uri.port != 7687:
            raise ValueError("--start-neo4j uses localhost:7687; use your existing server without that flag.")
        if os.environ["NEO4J_USER"] != "neo4j" or os.environ["NEO4J_DB"] != "neo4j":
            raise ValueError("The bundled Docker service uses the neo4j user and database.")
        subprocess.run(["docker", "compose", "-f", str(ROOT / "compose.yaml"), "up", "-d", "neo4j"],
                       cwd=ROOT, check=True)
    deadline = time.monotonic() + (120 if args.start_neo4j else 0)
    while True:
        try:
            with GraphDatabase.driver(os.environ["NEO4J_URI"],
                    auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
                    connection_timeout=5) as driver:
                driver.verify_connectivity()
                with driver.session(database=os.environ["NEO4J_DB"]) as session:
                    session.run("RETURN 1 AS ready").consume()
            break
        except Exception:
            if time.monotonic() >= deadline:
                raise RuntimeError("Neo4j preflight failed. Check its service, URI, database, and password.") from None
            print("Waiting for Neo4j...", flush=True)
            time.sleep(3)
    client = Client(host=os.environ["OLLAMA_HOST"], timeout=15)
    try:
        client.show(args.model)
        if not args.skip_evaluation:
            client.show(args.embedding_model)
    except Exception:
        raise RuntimeError("Ollama preflight failed. Start Ollama and pull the configured models: "
                           + args.model + ", " + args.embedding_model) from None
    if not args.skip_evaluation:
        # A listed model may not support embeddings. Fail before graph writes.
        OllamaEmbeddings(model=args.embedding_model).embed_query("pipeline preflight")


def run_step(step, out, index):
    log = out / "logs" / f"{index:02d}_{step.name}.log"
    command = [sys.executable, "-u", str(ROOT / "src" / step.script), *step.args]
    print(f"\n[{index}] {step.name}", flush=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    with log.open("w", encoding="utf-8") as stream:
        with subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as process:
            try:
                for line in process.stdout:
                    stream.write(line)
                    stream.flush()
                    print(line, end="", flush=True)
                code = process.wait()
            except KeyboardInterrupt:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise
    if code:
        raise RuntimeError(f"Step '{step.name}' exited with {code}. See {log}")
    if step.artifact:
        validate_artifact(out / step.artifact, step.rows_key, step.rows_key == "approved_edges")


def graph_query(source):
    # source is generated internally, never inserted from user input.
    return (f'MATCH (ch:Chunk) WHERE ch.source_type = "{source}"\n'
            'OPTIONAL MATCH p=(ch)-[*1..2]->(n)\nRETURN ch, p LIMIT 200')


def present(out, source, open_browser):
    query = graph_query(source)
    (out / "graph.cypher").write_text(query + ";\n", encoding="utf-8")
    url = os.environ["NEO4J_BROWSER_URL"].rstrip("/") + "/?" + urlencode({
        "dbms": os.environ["NEO4J_URI"], "db": os.environ["NEO4J_DB"], "cmd": "edit", "arg": query})
    links = "".join(f'<li><a href="{p.name}">{html.escape(p.stem)}</a></li>'
                    for p in sorted(out.glob("*.html")) if p.name != "index.html")
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Pipeline results</title>'
            '<style>body{font:17px system-ui;max-width:900px;margin:60px auto;padding:20px;'
            'line-height:1.6}pre{background:#eee;padding:20px;overflow:auto}a{color:#175bc1}</style>'
            f'<h1>Pipeline results</h1><p>Run: {html.escape(source)}</p>'
            f'<p><a href="{html.escape(url, quote=True)}">Open graph in Neo4j Browser</a></p>'
            '<p>Log in with your Neo4j credentials, then press Play (Ctrl+Enter). '
            'Choose the Graph result view. Double-click nodes to explore their neighbors. '
            'The initial view is limited to 200 rows.</p>'
            f'<pre>{html.escape(query)}</pre><h2>Fidelity reports</h2><ul>{links}</ul>'
            '<p><a href="manifest.json">Run manifest</a> · <a href="graph.cypher">Graph query</a></p></html>')
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"\nResults: {out / 'index.html'}\nNeo4j: {url}")
    if open_browser:
        for target in ((out / "index.html").as_uri(), url):
            try:
                if not webbrowser.open(target):
                    print("Could not open a browser automatically. Open the printed link.")
            except webbrowser.Error:
                print("Could not open a browser automatically. Open the printed link.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run extraction, Neo4j loading, background enrichment, and fidelity reports.")
    parser.add_argument("--input", type=Path, default=ROOT / "data/chunks.json")
    parser.add_argument("--output-dir", type=Path, help="New, empty directory; defaults to outputs/runs/<run-id>.")
    parser.add_argument("--model", default="llama3.2:3b")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--limit", type=int, default=0, help="Input chunks to process; 0 means all.")
    parser.add_argument("--seed-limit", type=int, default=20)
    parser.add_argument("--skip-background", action="store_true")
    parser.add_argument("--skip-evaluation", action="store_true")
    parser.add_argument("--start-neo4j", action="store_true", help="Start the bundled Docker Compose service.")
    parser.add_argument("--no-open", action="store_true", help="Write links without opening browser windows.")
    parser.add_argument("--dry-run", action="store_true", help="Validate input and show steps without services or writes.")
    args = parser.parse_args(argv)
    manifest = None
    out = None
    try:
        if args.limit < 0 or args.seed_limit < 1:
            raise ValueError("--limit must be >= 0 and --seed-limit must be >= 1.")
        rows = read_chunks(args.input.resolve(), args.limit)
        source = datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        out = (args.output_dir or ROOT / "outputs" / "runs" / source).resolve()
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            raise ValueError("Output directory must be new or empty; previous runs are preserved.")
        plan = build_plan(out, args.model, args.embedding_model, len(rows), source,
                          not args.skip_background, not args.skip_evaluation, args.seed_limit)
        if args.dry_run:
            print(f"Input: {args.input.resolve()}\nChunks: {len(rows)}\nOutput: {out}")
            for i, step in enumerate(plan, 1):
                print(f"{i:02d}. {step.name}: {step.script} " + " ".join(step.args))
            print("Finish: write graph query, results page, and Neo4j Browser link.")
            return 0
        check_dependencies()
        load_environment()
        preflight(args)
        out.mkdir(parents=True, exist_ok=True)
        (out / "logs").mkdir()
        write_json(out / "chunks.json", {"chunks": prepare_chunks(rows, source)})
        manifest = {"run_id": source, "input": str(args.input.resolve()), "chunk_count": len(rows),
                    "model": args.model, "embedding_model": args.embedding_model,
                    "background": not args.skip_background, "evaluation": not args.skip_evaluation,
                    "database": os.environ["NEO4J_DB"], "status": "running", "steps": []}
        write_json(out / "manifest.json", manifest)
        for i, step in enumerate(plan, 1):
            entry = {"name": step.name, "script": step.script, "args": step.args, "status": "running"}
            manifest["steps"].append(entry)
            write_json(out / "manifest.json", manifest)
            if step.name == "load_background" and not json.loads(
                    (out / "background_approved.json").read_text(encoding="utf-8"))["approved_edges"]:
                print("No background edges approved; skipping the background load.")
                entry["status"] = "skipped"
            else:
                run_step(step, out, i)
                entry["status"] = "complete"
            write_json(out / "manifest.json", manifest)
        manifest["status"] = "complete"
        write_json(out / "manifest.json", manifest)
        present(out, source, not args.no_open)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        if manifest is not None:
            manifest["status"] = "failed"
            if manifest["steps"] and manifest["steps"][-1]["status"] == "running":
                manifest["steps"][-1]["status"] = "failed"
            write_json(out / "manifest.json", manifest)
        print(f"Pipeline stopped: {exc or 'interrupted'}", file=sys.stderr)
        return 1
