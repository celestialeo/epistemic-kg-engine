"""Run only when explicitly launched: native KAG, then the frozen evaluator."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback
import uuid


class Tee:
    def __init__(self, console, logfile):
        self.console, self.logfile = console, logfile

    def write(self, value):
        self.console.write(value)
        self.logfile.write(value)
        self.flush()
        return len(value)

    def flush(self):
        self.console.flush()
        self.logfile.flush()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def verify_sources(root):
    provenance = read_json(root / "comparison/provenance.json")
    if git(root, "rev-parse", "HEAD") != provenance["upstream_commit"]:
        raise RuntimeError("KAG checkout differs from the pinned upstream commit")
    if git(root, "diff", "--name-only", "HEAD", "--", "kag", "knext"):
        raise RuntimeError("Upstream KAG source was modified; restore it before this comparison")
    for name, expected in provenance["sha256"].items():
        actual = hashlib.sha256((root / "comparison" / name).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Frozen comparison file changed: {name}")
    return provenance


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=root / "comparison/config.json")
    parser.add_argument("--input", type=Path, help="Override the bundled water-cycle input")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--check-only", action="store_true",
                        help="Check models, schema, components and full input coverage without extraction/evaluation")
    args = parser.parse_args()
    config = read_json(args.config.resolve())
    input_path = (args.input or root / config["input"]).resolve()
    output_root = (args.output_root or root / ("outputs/checks" if args.check_only else config["output_root"])).resolve()
    if config.get("storage") != "local_files":
        raise ValueError("This runner requires storage=local_files; no backend is used")
    if config["kag_window_length"] != 0 or config["kag_split_length"] <= 0:
        raise ValueError("This reconstruction comparison requires positive chunk length and zero overlap")
    source_bytes = input_path.read_bytes()
    source = source_bytes.decode("utf-8-sig")
    if not source.strip():
        raise ValueError("Input text is empty")
    provenance = verify_sources(root)
    from .baseline.trace import Trace
    from .baseline.models import Models
    from .baseline.evaluation import evaluate, reconstruction_context
    from . import native
    from .projection import graph_projection, native_union, paragraphs
    from .presentation import render_graph, render_report, statistics

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    trace = Trace(output_root / run_id, run_id)
    manifest = {"run_id": run_id, "status": "running", "config": config,
                "input_path": str(input_path), "input_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "provenance": provenance, "started_at": datetime.now(timezone.utc).isoformat(),
                "storage": "local_files", "check_only": args.check_only,
                "pipeline": "KAG construction with local schema/file storage + frozen baseline reconstruction/evaluation"}
    original_cwd = Path.cwd()
    code = 1
    built = {}
    log_handler = None
    previous_log_level = logging.getLogger().level
    with (trace.directory / "run.log").open("x", encoding="utf-8") as logfile:
        with redirect_stdout(Tee(sys.stdout, logfile)), redirect_stderr(Tee(sys.stderr, logfile)):
            try:
                print(f"Run directory: {trace.directory}", flush=True)
                trace.save("manifest.json", manifest)
                trace.text("input.txt", source)
                trace.save("artifacts/paragraphs.json", paragraphs(source))
                trace.save("artifacts/comparison_provenance.json", provenance)
                # Root logging may already have upstream handlers; add a run-local copy.
                log_handler = logging.StreamHandler(logfile)
                log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
                logging.getLogger().addHandler(log_handler)
                logging.getLogger().setLevel(logging.DEBUG)
                models = Models(trace, config["model"], config["embedding_model"], config["ollama_url"],
                                timeout=config["model_timeout"], think=config["think"],
                                context_tokens=config["context_tokens"],
                                max_output_tokens=config["max_output_tokens"],
                                document_context_tokens=config["document_context_tokens"],
                                document_output_tokens=config["document_output_tokens"])
                with trace.span("preflight"):
                    models.preflight()
                    # Validate dimensions before committing a schema tied to this model.
                    probe = models.client.embeddings(model=config["embedding_model"], prompt="water")
                    trace.emit("service.response", operation="embedding_dimension_probe",
                               embedding_dimensions=len(probe.embedding), model=config["embedding_model"])
                    if len(probe.embedding) != config["embedding_dimensions"]:
                        raise ValueError("Configured embedding dimensions do not match the installed model")
                    trace.save("artifacts/environment.json", {
                        "python": sys.version, "platform": platform.platform(), "model_details": models.details,
                        "installed_models": models.client.list().model_dump(mode="json"),
                        "packages": sorted([{"name": d.metadata["Name"], "version": d.version}
                                            for d in metadata.distributions()], key=lambda d: d["name"] or ""),
                        "comparison_source_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                     for p in (root / "comparison").rglob("*.py")
                                                     if "setup_backups" not in p.parts},
                        "upstream_commit": provenance["upstream_commit"]})
                with trace.span("local_schema_setup"):
                    native_config = native.prepare(config, root, trace)
                    manifest["kag_project"] = native_config["project"]
                    trace.save("manifest.json", manifest)
                    built, observer = native.components(native_config, trace)
                with trace.span("ingestion"):
                    native_chunks, chunks = native.read_chunks(built, input_path, source, trace)
                if args.check_only:
                    manifest.update(status="ready", input_chunks=len(chunks), final_score=None)
                    print(f"Ready: {len(chunks)} chunks; local file storage; models available. No experiment was run.", flush=True)
                    return 0
                with trace.span("kag_construction"):
                    snapshots = native.construct(built, observer, native_chunks, chunks, trace)
                with trace.span("graph_export"):
                    trace.save("artifacts/kag_graph_occurrences.json", native_union(snapshots))
                    graph, projection_issues = graph_projection(snapshots, chunks, source, run_id, trace)
                    trace.save("artifacts/graph.json", graph)
                    trace.text("knowledge_graph.html", render_graph(graph))
                    trace.save("artifacts/concepts.json", [n for n in graph["nodes"] if n["kind"] in {"concept", "event"}])
                    trace.save("artifacts/relations.json", [e for e in graph["edges"] if e["origin"] == "document"])
                    trace.save("artifacts/extractions.json", [dict(chunk_id=c["id"],
                               **reconstruction_context(graph, c["id"])) for c in chunks])
                    for name in ("debate", "seeds", "chapter_outline", "extraction_review", "background_review"):
                        trace.save(f"artifacts/{name}.json", {"status": "not_applicable",
                                   "reason": "This baseline stage is not part of the native KAG pipeline"})
                    # Preserve upstream recovery behavior; report any issues next to the score.
                    trace.save("artifacts/comparison_issues.json", projection_issues + observer.issues)
                with trace.span("evaluation"):
                    evaluation = evaluate(chunks, graph, models, trace)
                    trace.save("artifacts/evaluation.json", evaluation)
                    trace.text("reconstruction.txt", "\n\n".join(r["reconstruction"] for r in evaluation["results"]) + "\n")
                with trace.span("report"):
                    stats = statistics(graph, chunks, evaluation, models, observer, trace)
                    stats["comparison_issues"] = projection_issues + observer.issues
                    trace.save("statistics.json", stats)
                    page, markdown = render_report(stats, evaluation)
                    trace.text("index.html", page)
                    trace.text("report.md", markdown)
                manifest["status"] = "completed" if evaluation["status"] == "completed" else "incomplete"
                manifest["final_score"] = evaluation["final_score"]
                manifest["comparison_issue_count"] = len(projection_issues) + len(observer.issues)
                code = 0 if manifest["status"] == "completed" else 2
                print(f"Finished: {manifest['status']}. Open {trace.directory / 'index.html'}", flush=True)
            except BaseException as exc:
                manifest.update(status="failed", error=str(exc), error_type=type(exc).__name__)
                trace.emit("run.failed", error=str(exc), error_type=type(exc).__name__)
                trace.text("error.txt", traceback.format_exc())
                print(f"Stopped: {exc}\nSaved diagnostics: {trace.directory}", file=sys.stderr, flush=True)
                code = 130 if isinstance(exc, KeyboardInterrupt) else 1
            finally:
                native.close_components(built)
                os.chdir(original_cwd)
                if log_handler:
                    logging.getLogger().removeHandler(log_handler)
                    log_handler.close()
                logging.getLogger().setLevel(previous_log_level)
                manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
                manifest["artifacts"] = {k: v for k, v in trace.artifacts.items() if k != "manifest.json"}
                trace.save("manifest.json", manifest)
                trace.close()
    return code
