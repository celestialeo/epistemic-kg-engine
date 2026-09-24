"""Configuration, preflight, execution, and presentation for the local pipeline."""
import argparse
from datetime import datetime, timezone
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit
import uuid
import webbrowser

from .plan import build_plan
from .graph_view import write_graph
from .saved_runs import discover_runs, read_manifest, resolve_run, restore_plan

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


def check_dependencies(display_only=False):
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10+ is required (3.11 recommended). Create a new .venv with that Python.")
    modules = ["dotenv", "neo4j"] if display_only else ["dotenv", "neo4j", "langchain_ollama", "pydantic", "numpy", "scipy"]
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


def preflight(args, display_only=False):
    from neo4j import GraphDatabase

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
    if display_only:
        return
    from ollama import Client
    from langchain_ollama import OllamaEmbeddings
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


def run_step(step, out, index, log_dir=None):
    log = (log_dir or out / "logs") / f"{index:02d}_{step.name}.log"
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
    return (f'MATCH (ch:Chunk) WHERE ch.source_type = {json.dumps(source)}\n'
            'OPTIONAL MATCH p=(ch)-[*1..2]->(n)\nRETURN ch, p LIMIT 200')


def present(out, source, open_browser):
    graph = write_graph(out, source)
    query = graph_query(source)
    (out / "graph.cypher").write_text(query + ";\n", encoding="utf-8")
    url = os.environ["NEO4J_BROWSER_URL"].rstrip("/") + "/?" + urlencode({
        "dbms": os.environ["NEO4J_URI"], "db": os.environ["NEO4J_DB"], "cmd": "edit", "arg": query})
    links = "".join(f'<li><a href="{p.name}">{html.escape(p.stem)}</a></li>'
                    for p in sorted(out.glob("*.html")) if p.name not in {"index.html", "knowledge_graph.html"})
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><title>Pipeline results</title>'
            '<style>body{font:17px system-ui;max-width:900px;margin:60px auto;padding:20px;'
            'line-height:1.6}pre{background:#eee;padding:20px;overflow:auto}a{color:#175bc1}</style>'
            f'<h1>Pipeline results</h1><p>Run: {html.escape(source)}</p>'
            '<p><a href="knowledge_graph.html">Explore the interactive knowledge graph</a></p>'
            '<p>Blue: document knowledge. Orange: background additions. Purple: document concepts '
            'used in background knowledge. Select nodes and arrows for names, source text, and explanations.</p>'
            f'<p><a href="{html.escape(url, quote=True)}">Open graph in Neo4j Browser</a></p>'
            '<p>Log in with your Neo4j credentials, then press Play (Ctrl+Enter). '
            'Choose the Graph result view. Double-click nodes to explore their neighbors. '
            'The initial view is limited to 200 rows.</p>'
            f'<pre>{html.escape(query)}</pre><h2>Fidelity reports</h2><ul>{links}</ul>'
            '<p><a href="manifest.json">Run manifest</a> · <a href="graph.cypher">Graph query</a></p></html>')
    (out / "index.html").write_text(page, encoding="utf-8")
    update_comparison_links(out)
    print(f"\nResults: {out / 'index.html'}\nNeo4j: {url}")
    if open_browser:
        for target in ((out / "index.html").as_uri(), graph.as_uri()):
            try:
                if not webbrowser.open(target):
                    print("Could not open a browser automatically. Open the printed link.")
            except webbrowser.Error:
                print("Could not open a browser automatically. Open the printed link.")


def update_comparison_links(out):
    """Expose completed and partial experiments without changing historical reports."""
    index = out / "index.html"
    if not index.exists():
        return
    links = []
    for report in sorted(out.glob("factscore/*/report.html"), reverse=True):
        relative = report.relative_to(out).as_posix()
        dashboard = report.parent / "beforevsafter.html"
        dashboard_link = (f'<a href="{html.escape(dashboard.relative_to(out).as_posix(), quote=True)}">'
                          'Graphs and reports dashboard</a> · ') if dashboard.exists() else ''
        links.append(f'<li><a href="{html.escape(relative, quote=True)}">{html.escape(report.parent.name)}: '
                     'statistics and claim audit</a> · '
                     + dashboard_link +
                     f'<a href="{html.escape(relative.replace("report.html", "graph_comparison.html"), quote=True)}">'
                     'Compare before/after graphs</a></li>')
    section = '<!-- FACTSCORE START --><h2>FActScore comparisons</h2><ul>' + ''.join(links) + '</ul><!-- FACTSCORE END -->'
    page = index.read_text(encoding="utf-8")
    page = re.sub(r'<!-- FACTSCORE START -->.*?<!-- FACTSCORE END -->', '', page, flags=re.DOTALL)
    if links:
        page = page.replace('</html>', section + '</html>')
    index.write_text(page, encoding="utf-8")


def compare_factscore_run(args, source):
    from .factscore import load_references
    from .factscore_experiment import run_comparison, validate_source
    validate_source(source)
    if args.factscore_reference:
        load_references(args.factscore_reference)
    identifier = datetime.now(timezone.utc).strftime("compare_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    destination = source / "factscore" / identifier
    if args.dry_run:
        print(f"Compare saved artifacts: {source}\nOutput: {destination}\n"
              "Steps: freeze artifacts and references; check background evidence; reconstruct both graphs; "
              "score atomic claims and coverage; write paired statistics and before/after graph views.\n"
              f"Evidence: {args.factscore_reference or 'input document only (no independent external verification)'}.\n"
              f"Pilot limits (0=all): {args.factscore_limit} chunks, {args.factscore_edge_limit} background edges.\n"
              "Execution requires Ollama; no Neo4j reads or writes.")
        return 0
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    data = run_comparison(source, destination, args.factscore_reference, args.factscore_verifier,
                          limit=args.factscore_limit, edge_limit=args.factscore_edge_limit)
    update_comparison_links(source)
    if not args.no_open:
        try:
            webbrowser.open((destination / "report.html").as_uri())
            webbrowser.open((destination / "graph_comparison.html").as_uri())
        except webbrowser.Error:
            print(f"Open comparison files in {destination}")
    if data["status"] != "complete":
        print("Comparison saved with errors. Read the report's error audit before interpreting results.", file=sys.stderr)
        return 1
    return 0


def select_number(prompt, maximum):
    while True:
        value = input(prompt).strip()
        if value.isdigit() and 1 <= int(value) <= maximum:
            return int(value)
        print(f"Enter a number between 1 and {maximum}.")


def list_saved_runs():
    runs = discover_runs(ROOT / "outputs" / "runs")
    for i, (directory, manifest) in enumerate(runs, 1):
        print(f"{i}. {directory.name} | {manifest.get('status', 'unknown')} | "
              f"{manifest.get('chunk_count', '?')} chunks | {manifest.get('model', '?')}")
    if not runs:
        print("No saved runs found in outputs/runs/.")
    return runs


def display_saved_run(args, value):
    out = resolve_run(value, ROOT / "outputs" / "runs")
    saved = read_manifest(out)
    if saved.get("status") == "running":
        raise ValueError("This run is still marked running. Choose a finished run.")
    if args.graph_only:
        if args.dry_run:
            print(f"Render interactive graph from saved artifacts: {out}")
            return 0
        graph = write_graph(out, saved["run_id"])
        print(f"Knowledge graph: {graph}")
        if not args.no_open:
            try:
                if not webbrowser.open(graph.as_uri()):
                    print("Could not open a browser automatically. Open the printed file.")
            except webbrowser.Error:
                print("Could not open a browser automatically. Open the printed file.")
        return 0
    # Check every required artifact before writing anything to Neo4j.
    for filename, key in [("chunks.json", "chunks"), ("concepts.json", "concepts"),
                          ("extractions.json", "extractions"), ("mentions.json", "mentions"),
                          ("relations.json", "relations")]:
        if not (out / filename).is_file():
            raise ValueError(f"Cannot restore this run: missing {filename}.")
        validate_artifact(out / filename, key)
    if (out / "background_approved.json").exists():
        validate_artifact(out / "background_approved.json", "approved_edges", allow_empty=True)
    elif saved.get("background") and saved.get("status") == "complete":
        raise ValueError("Cannot restore this run: missing background_approved.json.")
    plan = restore_plan(out, saved)
    print(f"Opening saved run: {saved['run_id']} ({saved.get('status', 'unknown')})")
    print("Restore saved graph files and open reports; no extraction, model calls, or evaluation.")
    if args.dry_run:
        for step in plan:
            print(f"  {step.name}: {step.script}")
        return 0
    check_dependencies(display_only=True)
    load_environment()
    preflight(args, display_only=True)
    log_dir = out / "logs" / ("display_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8])
    log_dir.mkdir(parents=True)
    for i, step in enumerate(plan, 1):
        run_step(step, out, i, log_dir=log_dir)
    present(out, saved["run_id"], not args.no_open)
    return 0


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
    parser.add_argument("--graph-only", action="store_true",
                        help="With --view-run, render the interactive graph without Neo4j or Ollama.")
    parser.add_argument("--dry-run", action="store_true", help="Validate input and show steps without services or writes.")
    parser.add_argument("--factscore", action="store_true", help="After a new full run, compare baseline and evidence-filtered graphs.")
    parser.add_argument("--factscore-reference", type=Path, help="Reference passage/chunk JSON; omit to test support against the input document only.")
    parser.add_argument("--factscore-verifier", help="Ollama verifier model; defaults to the source run's generation model.")
    parser.add_argument("--factscore-limit", type=int, default=0, help="Pilot: compare the first N saved chunks (0=all).")
    parser.add_argument("--factscore-edge-limit", type=int, default=0, help="Pilot: compare only N highest-ranked eligible baseline edges (0=all).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--new", action="store_true", help="Start a new run without the menu.")
    mode.add_argument("--view-run", nargs="?", const="", metavar="RUN_ID_OR_DIRECTORY",
                      help="Restore and display a saved run; omit its name to choose from a list.")
    mode.add_argument("--list-runs", action="store_true", help="List saved runs without connecting to services.")
    mode.add_argument("--compare-factscore", metavar="RUN_ID_OR_DIRECTORY", help="Compare a saved full run using Ollama, without Neo4j; preserve baseline artifacts.")
    args = parser.parse_args(argv)
    manifest = None
    out = None
    try:
        if args.factscore_limit < 0 or args.factscore_edge_limit < 0:
            raise ValueError("FActScore pilot limits must be >= 0.")
        if (args.factscore_reference or args.factscore_verifier or args.factscore_limit or args.factscore_edge_limit) and not (args.factscore or args.compare_factscore):
            raise ValueError("Use FActScore options with --factscore or --compare-factscore RUN_ID.")
        if args.factscore and (args.skip_background or args.skip_evaluation or args.view_run is not None or args.list_runs):
            raise ValueError("--factscore requires a new full run with background and evaluation enabled.")
        if args.graph_only and args.view_run is None:
            raise ValueError("Use --graph-only with --view-run [RUN_ID].")
        if args.compare_factscore:
            source_directory = resolve_run(args.compare_factscore, ROOT / "outputs" / "runs")
            if read_manifest(source_directory).get("status") != "complete":
                raise ValueError("Choose a completed full run for --compare-factscore.")
            if args.limit or args.skip_background or args.skip_evaluation or args.output_dir or args.start_neo4j:
                raise ValueError("Saved comparisons use all saved chunks and their saved models; omit new-run/service options.")
            return compare_factscore_run(args, source_directory)
        if args.list_runs:
            list_saved_runs()
            return 0
        if not args.new and not args.factscore and args.view_run is None and not args.dry_run and sys.stdin.isatty():
            print("\n1. New run\n2. Display existing run")
            if select_number("Choose [1-2]: ", 2) == 2:
                args.view_run = ""
        if args.view_run is not None:
            if args.view_run == "":
                runs = list_saved_runs()
                if not runs:
                    return 0
                if not sys.stdin.isatty():
                    raise ValueError("Provide --view-run RUN_ID when running without an interactive terminal.")
                args.view_run = str(runs[select_number("Choose a run: ", len(runs)) - 1][0])
            return display_saved_run(args, args.view_run)
        if args.limit < 0 or args.seed_limit < 1:
            raise ValueError("--limit must be >= 0 and --seed-limit must be >= 1.")
        rows = read_chunks(args.input.resolve(), args.limit)
        if args.factscore_reference:
            from .factscore import load_references
            load_references(args.factscore_reference)
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
            if args.factscore:
                print("FActScore: freeze baseline; retrieve evidence; filter background; score both reconstructions; save statistics and graph comparison.")
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
        if args.factscore:
            # The baseline is complete. A later comparison failure belongs to its
            # own manifest and must not retroactively fail the baseline run.
            manifest = None
            return compare_factscore_run(args, out)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        if manifest is not None:
            manifest["status"] = "failed"
            if manifest["steps"] and manifest["steps"][-1]["status"] == "running":
                manifest["steps"][-1]["status"] = "failed"
            write_json(out / "manifest.json", manifest)
        print(f"Pipeline stopped: {exc or 'interrupted'}", file=sys.stderr)
        return 1
