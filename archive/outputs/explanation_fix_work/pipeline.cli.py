from .settings import setting, snapshot, automatic_chunk_words
"""One sequential, fully traced document-to-graph pipeline."""
import _submission_runtime as _notebook
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

ROOT = _notebook.root
CHAPTERS = {
    "neuroscience": ROOT / "data/input.txt",
    "neuroscience-simplified": ROOT / "data/sample.txt",
    "water-cycle": ROOT / "data/water_cycle.txt",
    "water-cycle-simplified": ROOT / "data/water_cycle_sample.txt",
    "ai-test": ROOT / "data/ai_test.txt",
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
    parser.add_argument("--chunk-words", type=int, default=setting("workload", "chunk_words"), help="Optional word cap; default derives from source size and model budgets")
    parser.add_argument("--seed-limit", type=int, default=setting("workload", "seed_limit") or 0,
                        help="Optional cap on important concepts with unanswered gaps; ranked by chapter importance (0=no cap)")
    parser.add_argument("--background-proposal-limit", type=int, default=setting("workload", "background_proposal_limit") or 0,
                        help="Optional cap on initial facts per seed (0=no cap); each rejected fact may receive one separate repair")
    # Accepted for old commands, but neither lexical nor similarity cutoffs
    # decide whether a distinct concept deserves background knowledge.
    parser.add_argument("--seed-similarity-threshold", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--seed-threshold", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--seed-max-words", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--model", default="qwen3.5:9b", help="Model for every language role (default: qwen3.5:9b)")
    parser.add_argument("--registry-model", help="Optional separate Ollama model for isolated concept/relation checks; defaults to --model")
    parser.add_argument("--batch-size", type=int, default=setting("workload", "batch_size"), help="Review/seed items per model call; no items are skipped")
    parser.add_argument("--identity-candidates", type=int, default=setting("workload", "identity_candidates"),
                        help="Maximum retrieved alias candidates per concept; identity still requires semantic verification")
    parser.add_argument("--health-window", type=int, default=setting("health", "window"), help="Recent completed items used for early failure detection; retries do not count")
    parser.add_argument("--health-min-samples", type=int, default=setting("health", "minimum"), help="Completed items required before detecting a failing step")
    parser.add_argument("--health-max-failure-rate", type=float, default=setting("health", "max_failure_rate"), help="Stop when recent failures exceed this fraction")
    parser.add_argument("--think", action="store_true", help="Enable extended model thinking; requires a thinking-capable model")
    parser.add_argument("--context-tokens", type=int, default=setting("model", "context_tokens"), help="Configured model context window")
    parser.add_argument("--max-output-tokens", type=int, default=setting("model", "max_output_tokens"), help="Configured per-call output ceiling; effective budget accounts for input size")
    parser.add_argument("--document-context-tokens", type=int,
                        help="Minimum context for document alignment; defaults to --context-tokens to avoid a late context change")
    parser.add_argument("--document-output-tokens", type=int,
                        help="Minimum output budget for document alignment; defaults to --max-output-tokens")
    parser.add_argument("--model-timeout", type=float, default=setting("model", "timeout_seconds"), help="Configured Ollama request timeout")
    parser.add_argument("--no-model-cache", action="store_true", help="Make every model request fresh, including repeated requests within this run")
    parser.add_argument("--resume", type=Path, help="Reuse validated model responses from this run when prompts and model digests match; writes a new complete run")
    parser.add_argument("--embedding-model", default="nomic-embed-text")
    parser.add_argument("--neo4j", action="store_true", help="Also export the final graph to Neo4j")
    parser.add_argument("--start-neo4j", action="store_true", help="Start bundled Neo4j using Docker Compose and export the graph")
    parser.add_argument("--no-open", action="store_true", help="Do not open the results page automatically")
    parser.add_argument("--interact", action="store_true",
                        help="Interacting with graph: open the saved graph, quiz and professor dashboard without rerunning the pipeline")
    parser.add_argument("--no-explorer", action="store_true", help="Stop after evaluation/reporting without starting the graph and professor dashboard")
    parser.add_argument("--explorer-port", type=int, default=0, help="Local graph explorer port; 0 selects a free port (default)")
    parser.add_argument("--new", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.no_model_cache and args.resume:
        parser.error("--no-model-cache requires a fresh run without --resume")
    if not 0 <= args.explorer_port <= 65535:
        parser.error("explorer-port must be between 0 and 65535")
    if args.interact:
        if args.no_explorer or args.resume or args.neo4j or args.start_neo4j:
            parser.error("--interact opens saved results; do not combine it with --no-explorer, --resume or database export flags")
        from .professor import discover_latest, serve
        snapshots, warnings = discover_latest(args.output_root)
        for warning in warnings:
            print(warning, file=sys.stderr)
        if args.input:
            snapshots = [s for s in snapshots if Path(s.manifest.get("config", {}).get("input", "")).resolve() == args.input.resolve()]
        elif args.chapter and args.chapter != "both":
            snapshots = [s for s in snapshots if s.manifest.get("config", {}).get("chapter") == args.chapter]
        elif args.chapter == "both":
            snapshots = [s for s in snapshots if s.manifest.get("config", {}).get("chapter") in {"neuroscience", "water-cycle"}]
        if not snapshots:
            parser.error("No completed run found for this input. Run the pipeline first, or check --output-root.")
        latest = max(snapshots, key=lambda s: (
            datetime.fromisoformat((s.manifest.get("started_at_utc") or s.manifest["started_at"]).replace("Z", "+00:00")).timestamp(),
            s.directory.name))
        serve(runs_root=args.output_root, selected_run=latest.directory,
              port=args.explorer_port, open_browser=not args.no_open)
        return 0
    if (args.chunk_words is not None and args.chunk_words < 1) or args.seed_limit < 0 or args.background_proposal_limit < 0:
        parser.error("chunk-words must be positive; seed-limit and background-proposal-limit must be nonnegative")
    if (args.batch_size is not None and args.batch_size < 1) or (args.identity_candidates is not None and args.identity_candidates < 1) or not 1 <= args.health_min_samples <= args.health_window:
        parser.error("batch-size must be positive; health-min-samples must be between 1 and health-window")
    if not 0 <= args.health_max_failure_rate < 1:
        parser.error("health-max-failure-rate must be between 0 inclusive and 1 exclusive")
    if args.resume and args.chapter == "both":
        parser.error("--resume applies to one chapter run; choose a single chapter")
    if args.context_tokens < 1 or args.max_output_tokens < 1 or args.model_timeout < 1:
        parser.error("context-tokens, max-output-tokens and model-timeout must be positive")
    if args.max_output_tokens >= args.context_tokens:
        parser.error("max-output-tokens must be smaller than context-tokens to leave room for the prompt")
    if args.document_context_tokens is None:
        args.document_context_tokens = args.context_tokens
    if args.document_output_tokens is None:
        args.document_output_tokens = args.max_output_tokens
    if not 0 < args.document_output_tokens < args.document_context_tokens:
        parser.error("document token budgets must be positive, with document-output-tokens smaller than document-context-tokens")
    selected = ["neuroscience", "water-cycle"] if args.chapter == "both" else [args.chapter or ("custom" if args.input else "neuroscience")]
    code = 0
    completed_runs = []
    for chapter in selected:
        config = argparse.Namespace(**vars(args))
        config.chapter = chapter
        config.input = args.input or CHAPTERS[chapter]
        config.output_root = args.output_root / chapter
        result = run_chapter(config)
        if result == 130:
            return result
        code = max(code, result)
        if result in (0, 2) and getattr(config, "completed_run_directory", None):
            completed_runs.append(config.completed_run_directory)
    if completed_runs and not args.no_explorer:
        try:
            from .professor import serve
            serve(runs_root=args.output_root, selected_run=completed_runs[-1],
                  port=args.explorer_port, open_browser=not args.no_open)
        except KeyboardInterrupt:
            pass
        except Exception as exc:
            print(f"Graph and professor dashboard could not start: {exc}. Completed pipeline results are saved. "
                  "Reopen them with python run_pipeline.py --interact.", file=sys.stderr)
            return max(code, 1)
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
    config["resolved_settings"] = snapshot()
    manifest = {"schema_version": 1, "run_id": run_id, "status": "running", "config": config,
                "pipeline_stages": ["extraction", "debate", "graph", "evaluation"],
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
                from .seeds import build_outline
                from .gaps import collect_seeds
                from .registry import ConceptRegistry, RelationRegistry, FactIndex
                from .graph_view import build_graph, render_graph
                from .evaluation import evaluate
                from .report import statistics_for, render_report
                from .database import preflight, export_graph
                with trace.span("input"):
                    request = trace.emit("input.read_requested", path=str(args.input.resolve()), encoding="utf-8-sig")
                    raw_input = _notebook.input_bytes(args.input)
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
                    effective_chunk_words = args.chunk_words or automatic_chunk_words(text, args.context_tokens, args.max_output_tokens)
                    trace.emit("workload.resolved", chunk_words=effective_chunk_words, source_words=len(text.split()), mode="override" if args.chunk_words else "input_budget")
                    config["effective_chunk_words"] = effective_chunk_words
                    paragraphs, chunks = split_document(text, effective_chunk_words, trace)
                    trace.save("artifacts/paragraphs.json", paragraphs)
                    trace.save("artifacts/chunks.json", chunks)
                with trace.span("preflight"):
                    models = Models(trace, args.model, args.embedding_model, host,
                                    timeout=args.model_timeout, think=args.think,
                                    context_tokens=args.context_tokens, max_output_tokens=args.max_output_tokens,
                                    registry_model=args.registry_model, batch_size=args.batch_size,
                                    identity_candidates=args.identity_candidates,
                                    document_context_tokens=args.document_context_tokens,
                                    document_output_tokens=args.document_output_tokens)
                    models.cache_enabled = not getattr(args, "no_model_cache", False)
                    models.preflight()
                    if args.resume:
                        models.load_cache(args.resume)
                    trace.save("artifacts/environment.json", {
                        "python": sys.version, "model_details": models.details,
                        "dependencies": {name: importlib.metadata.version(name) for name in ("ollama", "pydantic", "numpy", "neo4j", "python-dotenv")},
                        "code_sha256": _notebook.source_hashes()})
                    if args.neo4j or args.start_neo4j:
                        driver = preflight(trace, ROOT, args.start_neo4j)
                    else:
                        trace.emit("database.export_disabled", reason="Portable graph output selected; enable with --neo4j")
                concepts, relations = ConceptRegistry(models, trace), RelationRegistry(models, trace)
                trace.save("artifacts/unresolved_items.json", [])
                facts = FactIndex(relations)
                trace.save("artifacts/relations.json", relations.snapshot())
                trace.save("artifacts/concepts.json", {"concepts": [], "mentions": []})
                from .checkpoints import Checkpoints
                trace.checkpoints = Checkpoints(trace, models, text, config, (concepts, relations, facts), args.resume)
                with trace.span("extraction"):
                    saved = trace.checkpoints.restore('extraction')
                    if saved is not None:
                        extractions = saved['extractions']
                    else:
                        extractions = extract(chunks, paragraphs, models, trace, concepts, relations)
                        trace.checkpoints.save('extraction', dict(extractions=extractions))
                with trace.span("debate"):
                    saved = trace.checkpoints.restore('source_review')
                    if saved is not None:
                        extractions, outline, document_reviews = saved['extractions'], saved['outline'], saved['reviews']
                    else:
                        outline = build_outline(chunks, models, trace)
                        concepts.reconcile(extractions, outline)
                        trace.save("artifacts/extraction_proposals.json", extractions)
                        from .qualifiers import complete_arguments
                        complete_arguments(extractions, models, trace)
                        document_reviews = review_extractions(extractions, chunks, outline, concepts, facts, models, trace)
                        from .source_recovery import recover_source
                        document_reviews = recover_source(extractions, chunks, paragraphs, outline, concepts,
                                                          relations, facts, models, trace, document_reviews)
                        trace.save("artifacts/extractions.json", extractions)
                        trace.checkpoints.save('source_review', dict(extractions=extractions, outline=outline, reviews=document_reviews))
                    manifest["incomplete_extraction_chunks"] = [e["chunk_id"] for e in extractions if e["status"] == "incomplete"]
                    saved = trace.checkpoints.restore('seeds')
                    if saved is not None:
                        seeds = saved['seeds']
                    else:
                        seeds = collect_seeds(extractions, chunks, concepts, trace, limit=args.seed_limit,
                                              outline=outline) if outline["topics"] else []
                        trace.checkpoints.save('seeds', dict(seeds=seeds))
                    if not outline["topics"]:
                        seeds = []
                        trace.emit("debate.skipped", reason="Chapter scope is unresolved; document reviews retained")
                        trace.save("artifacts/seeds.json", dict(policy="chapter_importance_and_knowledge_gaps", selected=[],
                                   status="unresolved", reason="No validated chapter topics"))
                    result = debate(seeds, chunks, outline, concepts, relations, facts, models, trace, document_reviews,
                                    proposal_limit=args.background_proposal_limit)
                    trace.save("artifacts/debate.json", result)
                with trace.span("graph"):
                    graph = build_graph(text, paragraphs, chunks, extractions, result, trace, concepts, relations)
                    manifest.update(graph_quality_required=False, graph_quality_status="not_run",
                                    graph_acceptance_policy="document_review_and_background_debate")
                    trace.emit("graph.review_policy", policy=manifest["graph_acceptance_policy"],
                               post_graph_review=False)
                    trace.save("artifacts/graph.json", graph)
                    trace.text("knowledge_graph.html", render_graph(graph))
                    if driver:
                        export_graph(graph, driver, trace)
                        trace.text("graph.cypher", "MATCH p=(n:PipelineNode {run_id: " + json.dumps(run_id) + "})-[r]->(m) RETURN p;\n")
                with trace.span("evaluation"):
                    evaluation = evaluate(chunks, graph, models, trace)
                    trace.save("artifacts/evaluation.json", evaluation)
                    trace.text("reconstruction.txt", "\n\n".join(
                        row["reconstruction"] for row in evaluation["results"]) + "\n")
                    manifest.update(evaluation_status=evaluation["status"],
                                    reconstruction_score=evaluation["final_score"])
                    stats = statistics_for(paragraphs, chunks, extractions, result, graph, evaluation, models, trace)
                    trace.save("statistics.json", stats)
                    page, markdown = render_report(stats, paragraphs, chunks, result, evaluation)
                    trace.text("index.html", page)
                    trace.text("report.md", markdown)
                manifest["unresolved_items"] = getattr(trace, "unresolved_items", [])
                incomplete = (manifest["incomplete_extraction_chunks"] or manifest["unresolved_items"]
                              or evaluation["status"] != "completed")
                manifest["status"] = "completed_with_issues" if incomplete else "completed"
                code = 2 if incomplete else 0
                label = "Completed with unresolved items; inspect the report" if incomplete else "Completed"
                if evaluation["final_score"] is not None:
                    print(f"\nReconstruction score: {evaluation['final_score']:.2f} / 100", flush=True)
                print(f"\n{label}: {out / 'index.html'}", flush=True)
                if not args.no_open and args.no_explorer:
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
                                performance=dict(model_calls=int(getattr(locals().get('models'), 'calls', 0)),
                                    cache_hits=int(getattr(locals().get('models'), 'cache_hits', 0)),
                                    service_retries=int(getattr(locals().get('models'), 'service_retries', 0)),
                                    checkpoints_restored=trace.counts.get('checkpoint.restored', 0),
                                    resumed_from=str(args.resume) if args.resume else None),
                                artifacts={k: v for k, v in trace.artifacts.items() if k != "manifest.json"},
                                event_counts_before_finalization=dict(trace.counts))
                trace.save("manifest.json", manifest)
                trace.emit("run.completed" if code in (0, 2) else "run.closed", status=manifest["status"])
                trace.close()
    if code in (0, 2):
        args.completed_run_directory = out
    return code
