"""One sequential, fully traced document-to-graph pipeline."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import traceback
from urllib.parse import urlsplit
import uuid
import webbrowser

from .trace import Trace

ROOT = Path(__file__).resolve().parents[1]


def make_run_id(started):
    """Use local wall time and its UTC offset, including across midnight/DST."""
    return started.strftime("run_%Y%m%d_%H%M%S_UTC%z_") + uuid.uuid4().hex[:8]


class Tee:
    def __init__(self, terminal, file):
        self.terminal, self.file = terminal, file

    def write(self, value):
        self.terminal.write(value)
        self.file.write(value)
        self.flush()
        return len(value)

    def flush(self):
        self.terminal.flush()
        self.file.flush()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "data/input.txt", help="UTF-8 prose; blank lines separate paragraphs")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/runs")
    parser.add_argument("--chunk-words", type=int, default=85, help="Maximum words per chunk; sentences and paragraphs retain order")
    parser.add_argument("--seed-limit", type=int, default=6, help="Background seed concepts (0=all); every chunk is extracted and evaluated")
    parser.add_argument("--model", default="llama3.2:3b")
    parser.add_argument("--resume", type=Path, help="Reuse validated model responses from this run when prompts and model digests match; writes a new complete run")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--neo4j", action="store_true", help="Also export the final graph to Neo4j")
    parser.add_argument("--start-neo4j", action="store_true", help="Start bundled Neo4j using Docker Compose and export the graph")
    parser.add_argument("--no-open", action="store_true", help="Do not open the results page automatically")
    parser.add_argument("--new", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.chunk_words < 1 or args.seed_limit < 0:
        parser.error("chunk-words must be positive and seed-limit must be nonnegative")
    started = datetime.now().astimezone()
    run_id = make_run_id(started)
    out = args.output_root.resolve() / run_id
    trace = Trace(out, run_id)
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    manifest = {"schema_version": 1, "run_id": run_id, "status": "running", "config": config,
                "started_at": started.isoformat(),
                "started_at_utc": started.astimezone(timezone.utc).isoformat(),
                "time_zone": started.tzname(),
                "logging_scope": "Application actions, full model requests/responses, explicit rationales, parsing, "
                                 "validation, graph mutations and database queries. Hidden internal thinking is unavailable."}
    driver = None
    code = 0
    with (out / "run.log").open("w", encoding="utf-8") as console:
        with redirect_stdout(Tee(sys.stdout, console)), redirect_stderr(Tee(sys.stderr, console)):
            try:
                trace.emit("run.started", config=config, logging_scope=manifest["logging_scope"])
                trace.save("manifest.json", manifest)
                from dotenv import load_dotenv
                load_dotenv(ROOT / ".env", override=False)
                host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
                if urlsplit(host).username or urlsplit(host).password:
                    raise ValueError("Do not embed credentials in OLLAMA_HOST")
                from .ingest import split_document
                from .models import Models
                from .extraction import extract
                from .debate import select_seeds, debate
                from .graph_view import build_graph, render_graph
                from .evaluation import evaluate
                from .report import statistics_for, render_report
                from .database import preflight, export_graph
                with trace.span("input"):
                    request = trace.emit("input.read_requested", path=str(args.input.resolve()), encoding="utf-8-sig")
                    raw_input = args.input.read_bytes()
                    text = raw_input.decode("utf-8-sig")
                    trace.emit("input.read_completed", parent_id=request, bytes=len(raw_input),
                               sha256=hashlib.sha256(raw_input).hexdigest(), text=text)
                    trace.text("input.txt", text)
                    paragraphs, chunks = split_document(text, args.chunk_words, trace)
                    trace.save("artifacts/paragraphs.json", paragraphs)
                    trace.save("artifacts/chunks.json", chunks)
                with trace.span("preflight"):
                    models = Models(trace, args.model, args.embedding_model, host)
                    models.preflight()
                    if args.resume:
                        models.load_cache(args.resume)
                    trace.save("artifacts/environment.json", {
                        "python": sys.version, "model_details": models.details,
                        "dependencies": {name: importlib.metadata.version(name) for name in ("ollama", "pydantic", "numpy", "neo4j", "python-dotenv")},
                        "code_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in sorted((ROOT / "pipeline").glob("*")) if p.is_file()}})
                    if args.neo4j or args.start_neo4j:
                        driver = preflight(trace, ROOT, args.start_neo4j)
                    else:
                        trace.emit("database.export_disabled", reason="Portable graph output selected; enable with --neo4j")
                with trace.span("extraction"):
                    extractions = extract(chunks, paragraphs, models, trace)
                    trace.save("artifacts/extractions.json", extractions)
                with trace.span("debate"):
                    seeds = select_seeds(extractions, chunks, paragraphs, args.seed_limit, trace)
                    result = debate(seeds, models, trace)
                    trace.save("artifacts/debate.json", result)
                with trace.span("graph"):
                    graph = build_graph(text, paragraphs, chunks, extractions, result, trace)
                    trace.save("artifacts/graph.json", graph)
                    trace.text("knowledge_graph.html", render_graph(graph))
                    if driver:
                        export_graph(graph, driver, trace)
                        trace.text("graph.cypher", "MATCH p=(n:PipelineNode {run_id: " + json.dumps(run_id) + "})-[r]->(m) RETURN p;\n")
                with trace.span("evaluation"):
                    evaluation = evaluate(chunks, graph, models, trace)
                    trace.save("artifacts/evaluation.json", evaluation)
                with trace.span("report"):
                    stats = statistics_for(paragraphs, chunks, extractions, result, graph, evaluation, models, trace)
                    trace.save("statistics.json", stats)
                    page, markdown = render_report(stats, paragraphs, chunks, result, evaluation)
                    trace.text("index.html", page)
                    trace.text("report.md", markdown)
                manifest["status"] = "completed"
                print(f"\nCompleted: {out / 'index.html'}", flush=True)
                if not args.no_open:
                    opened = webbrowser.open((out / "index.html").as_uri())
                    trace.emit("presentation.browser_requested", path="index.html", opened=opened)
            except BaseException as exc:
                code = 130 if isinstance(exc, KeyboardInterrupt) else 1
                manifest.update(status="interrupted" if code == 130 else "failed", error=str(exc), error_type=type(exc).__name__)
                trace.emit("run.failed", error=str(exc), error_type=type(exc).__name__, traceback=traceback.format_exc())
                traceback.print_exc()
                print(f"Run stopped; complete diagnostic log: {out / 'events.jsonl'}", flush=True)
            finally:
                if driver:
                    driver.close()
                    trace.emit("database.closed")
                finished = datetime.now().astimezone()
                manifest.update(finished_at=finished.isoformat(),
                                finished_at_utc=finished.astimezone(timezone.utc).isoformat(),
                                duration_seconds=time.monotonic()-trace.started,
                                artifacts={k: v for k, v in trace.artifacts.items() if k != "manifest.json"},
                                event_counts_before_finalization=dict(trace.counts))
                trace.save("manifest.json", manifest)
                trace.emit("run.completed" if code == 0 else "run.closed", status=manifest["status"])
                trace.close()
    return code
