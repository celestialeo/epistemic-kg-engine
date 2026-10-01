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
CHAPTERS = {
    "neuroscience": ROOT / "data/input.txt",
    "neuroscience-simplified": ROOT / "data/sample.txt",
    "water-cycle": ROOT / "data/water_cycle.txt",
    "water-cycle-simplified": ROOT / "data/water_cycle_sample.txt",
}


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
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--input", type=Path, help="Custom UTF-8 chapter; blank lines separate paragraphs")
    inputs.add_argument("--chapter", choices=[*CHAPTERS, "both"],
                        help="Built-in chapter; both runs full neuroscience and water-cycle; default: neuroscience")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/runs")
    parser.add_argument("--chunk-words", type=int, default=85, help="Maximum words per chunk; sentences and paragraphs retain order")
    parser.add_argument("--seed-limit", type=int, default=0, help="Optional cap AFTER assessing all concepts (0=all eligible)")
    parser.add_argument("--seed-threshold", type=float, default=.7, help="Minimum importance, relevance AND expansion value (default: .7)")
    parser.add_argument("--seed-max-words", type=int, default=4, help="Maximum words in an expansion seed; longer concepts remain in the graph")
    parser.add_argument("--model", default="qwen3.5:9b", help="Model for every language role (default: qwen3.5:9b)")
    parser.add_argument("--registry-model", help="Optional separate Ollama model for isolated concept/relation checks; defaults to --model")
    parser.add_argument("--batch-size", type=int, default=4, help="Review/seed items per model call; no items are skipped")
    parser.add_argument("--health-window", type=int, default=10, help="Recent completed items used for early failure detection; retries do not count")
    parser.add_argument("--health-min-samples", type=int, default=5, help="Completed items required before detecting a failing step")
    parser.add_argument("--health-max-failure-rate", type=float, default=.5, help="Stop when recent failures exceed this fraction")
    parser.add_argument("--think", action="store_true", help="Enable extended model thinking; requires a thinking-capable model")
    parser.add_argument("--context-tokens", type=int, default=8192, help="Model context window (default: 8192)")
    parser.add_argument("--max-output-tokens", type=int, default=4096, help="Per-call output budget, including thinking when enabled (default: 4096)")
    parser.add_argument("--model-timeout", type=int, default=600, help="Ollama request timeout in seconds (default: 600)")
    parser.add_argument("--resume", type=Path, help="Reuse validated model responses from this run when prompts and model digests match; writes a new complete run")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--neo4j", action="store_true", help="Also export the final graph to Neo4j")
    parser.add_argument("--start-neo4j", action="store_true", help="Start bundled Neo4j using Docker Compose and export the graph")
    parser.add_argument("--no-open", action="store_true", help="Do not open the results page automatically")
    parser.add_argument("--new", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.chunk_words < 1 or args.seed_limit < 0 or args.seed_max_words < 1:
        parser.error("chunk-words and seed-max-words must be positive; seed-limit must be nonnegative")
    if not 0 <= args.seed_threshold <= 1:
        parser.error("seed-threshold must be between 0 and 1")
    if args.batch_size < 1 or not 1 <= args.health_min_samples <= args.health_window:
        parser.error("batch-size must be positive; health-min-samples must be between 1 and health-window")
    if not 0 <= args.health_max_failure_rate < 1:
        parser.error("health-max-failure-rate must be between 0 inclusive and 1 exclusive")
    if args.resume and args.chapter == "both":
        parser.error("--resume applies to one chapter run; choose a single chapter")
    if args.context_tokens < 1 or args.max_output_tokens < 1 or args.model_timeout < 1:
        parser.error("context-tokens, max-output-tokens and model-timeout must be positive")
    if args.max_output_tokens >= args.context_tokens:
        parser.error("max-output-tokens must be smaller than context-tokens to leave room for the prompt")
    selected = ["neuroscience", "water-cycle"] if args.chapter == "both" else [args.chapter or ("custom" if args.input else "neuroscience")]
    code = 0
    for chapter in selected:
        config = argparse.Namespace(**vars(args))
        config.chapter = chapter
        config.input = args.input or CHAPTERS[chapter]
        config.output_root = args.output_root / chapter
        result = run_chapter(config)
        if result == 130:
            return result
        code = max(code, result)
    return code


def run_chapter(args):
    """A fresh model boundary, cache, registries, fact index, graph and trace."""
    started = datetime.now().astimezone()
    run_id = make_run_id(started)
    out = args.output_root.resolve() / run_id
    trace = Trace(out, run_id)
    from .health import HealthMonitor
    trace.health = HealthMonitor(trace, args.health_window, args.health_min_samples, args.health_max_failure_rate)
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
                from .debate import review_extractions, debate
                from .seeds import build_outline, select_seeds
                from .registry import ConceptRegistry, RelationRegistry, FactIndex
                from .graph_view import build_graph, render_graph
                from .evaluation import evaluate
                from .report import statistics_for, render_report
                from .database import preflight, export_graph
                with trace.span("input"):
                    request = trace.emit("input.read_requested", path=str(args.input.resolve()), encoding="utf-8-sig")
                    raw_input = args.input.read_bytes()
                    text = raw_input.decode("utf-8-sig")
                    if args.resume:
                        saved_manifest = json.loads((args.resume / "manifest.json").read_text(encoding="utf-8"))
                        saved_input = (args.resume / "input.txt").read_bytes().decode("utf-8")
                        if (saved_manifest["config"].get("chapter") != args.chapter
                                or saved_input != text):
                            raise ValueError("--resume must belong to the same chapter and unchanged input text")
                    trace.emit("input.read_completed", parent_id=request, bytes=len(raw_input),
                               sha256=hashlib.sha256(raw_input).hexdigest(), text=text)
                    trace.text("input.txt", text)
                    paragraphs, chunks = split_document(text, args.chunk_words, trace)
                    trace.save("artifacts/paragraphs.json", paragraphs)
                    trace.save("artifacts/chunks.json", chunks)
                with trace.span("preflight"):
                    models = Models(trace, args.model, args.embedding_model, host,
                                    timeout=args.model_timeout, think=args.think,
                                    context_tokens=args.context_tokens, max_output_tokens=args.max_output_tokens,
                                    registry_model=args.registry_model, batch_size=args.batch_size)
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
                concepts, relations = ConceptRegistry(models, trace), RelationRegistry(models, trace)
                trace.save("artifacts/unresolved_items.json", [])
                facts = FactIndex(relations)
                trace.save("artifacts/relations.json", relations.snapshot())
                trace.save("artifacts/concepts.json", {"concepts": [], "mentions": []})
                with trace.span("outline"):
                    outline = build_outline(chunks, models, trace)
                with trace.span("extraction"):
                    extractions = extract(chunks, paragraphs, models, trace, concepts, relations)
                    concepts.reconcile(extractions, outline)
                    trace.save("artifacts/extraction_proposals.json", extractions)
                with trace.span("extraction_review"):
                    document_reviews = review_extractions(extractions, chunks, outline, concepts, facts, models, trace)
                    trace.save("artifacts/extractions.json", extractions)
                    manifest["incomplete_extraction_chunks"] = [e["chunk_id"] for e in extractions if e["status"] == "incomplete"]
                with trace.span("seeds"):
                    seeds = select_seeds(extractions, chunks, concepts, outline, models, trace,
                                         args.seed_threshold, args.seed_limit, args.seed_max_words)
                with trace.span("debate"):
                    result = debate(seeds, chunks, outline, concepts, relations, facts, models, trace, document_reviews)
                    trace.save("artifacts/debate.json", result)
                with trace.span("graph"):
                    graph = build_graph(text, paragraphs, chunks, extractions, result, trace, concepts, relations)
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
                manifest["unresolved_items"] = getattr(trace, "unresolved_items", [])
                incomplete = manifest["incomplete_extraction_chunks"] or manifest["unresolved_items"]
                manifest["status"] = "completed_with_issues" if incomplete else "completed"
                code = 2 if incomplete else 0
                label = "Completed with unresolved items; inspect the report" if incomplete else "Completed"
                print(f"\n{label}: {out / 'index.html'}", flush=True)
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
                                unresolved_items=getattr(trace, "unresolved_items", []),
                                finished_at_utc=finished.astimezone(timezone.utc).isoformat(),
                                duration_seconds=time.monotonic()-trace.started,
                                artifacts={k: v for k, v in trace.artifacts.items() if k != "manifest.json"},
                                event_counts_before_finalization=dict(trace.counts))
                trace.save("manifest.json", manifest)
                trace.emit("run.completed" if code in (0, 2) else "run.closed", status=manifest["status"])
                trace.close()
    return code
