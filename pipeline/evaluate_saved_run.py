"""Evaluate a saved graph and add reconstruction results to its existing report."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from .evaluation import evaluate
from .health import HealthMonitor
from .models import Models
from .report import render_report
from .trace import Trace


def evaluate_saved_run(directory, host="http://localhost:11434", *, resume=None,
                       document_context_tokens=None, document_output_tokens=None):
    directory = Path(directory).resolve()
    read = lambda name: json.loads((directory / name).read_text(encoding="utf-8"))
    manifest = read("manifest.json")
    if manifest["status"] not in {"completed", "completed_with_issues"}:
        raise ValueError("Evaluate a completed run so its saved graph cannot change during evaluation")
    chunks, graph = read("artifacts/chunks.json"), read("artifacts/graph.json")
    paragraphs, debate = read("artifacts/paragraphs.json"), read("artifacts/debate.json")
    stats = read("statistics.json")
    config = manifest["config"]
    if document_context_tokens is None:
        document_context_tokens = config.get("document_context_tokens", 16384)
    if document_output_tokens is None:
        document_output_tokens = config.get("document_output_tokens", 8192)
    if not 0 < document_output_tokens < document_context_tokens:
        raise ValueError("Document output budget must be positive and smaller than its context window")
    started = datetime.now().astimezone()
    identifier = started.strftime("evaluation_%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    trace = Trace(directory / identifier, identifier)
    trace.health = HealthMonitor(trace, config.get("health_window", 10),
                                config.get("health_min_samples", 5), config.get("health_max_failure_rate", .5))
    source_hashes = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                     for name in ("input.txt", "artifacts/chunks.json", "artifacts/graph.json")}
    metadata = dict(source_run=manifest["run_id"], started_at=started.isoformat(),
                    source_sha256=source_hashes, status="running", trace_directory=identifier,
                    document_context_tokens=max(document_context_tokens, config.get("context_tokens", 8192)),
                    document_output_tokens=max(document_output_tokens, config.get("max_output_tokens", 4096)))
    trace.save("manifest.json", metadata)
    # Keep the prior presentation and manifest intact in this evaluation's trace.
    for name in ("manifest.json", "statistics.json", "index.html", "report.md"):
        trace.text("before/" + name, (directory / name).read_text(encoding="utf-8"))
    try:
        models = Models(trace, config["model"], config.get("embedding_model", "nomic-embed-text"),
                        host, config.get("model_timeout", 600), think=config.get("think", False),
                        context_tokens=config.get("context_tokens", 8192),
                        max_output_tokens=config.get("max_output_tokens", 4096),
                        registry_model=config.get("registry_model"), batch_size=config.get("batch_size", 4),
                        document_context_tokens=document_context_tokens, document_output_tokens=document_output_tokens)
        print(f"Evaluation trace: {trace.directory}", flush=True)
        models.preflight()
        trace.save("artifacts/environment.json", dict(model_details=models.details, config=config,
                   evaluation_code_sha256=hashlib.sha256(Path(__file__).with_name("evaluation.py").read_bytes()).hexdigest()))
        if resume:
            saved = json.loads((Path(resume) / "manifest.json").read_text(encoding="utf-8"))
            if saved.get("source_sha256") != source_hashes:
                raise ValueError("Evaluation cache belongs to different source artifacts")
            models.load_cache(resume)
        with trace.span("evaluation"):
            result = evaluate(chunks, graph, models, trace)
        reconstruction = "\n\n".join(row["reconstruction"] for row in result["results"])
        metadata.update(status=result["status"], final_score=result["final_score"],
                        finished_at=datetime.now().astimezone().isoformat(),
                        duration_seconds=time.monotonic() - trace.started,
                        metric_version=result["metric_version"],
                        unresolved_items=getattr(trace, "unresolved_items", []),
                        models=dict(generation=models.model, calls=models.calls, retries=models.retries,
                                    cache_hits=models.cache_hits,
                                    prompt_tokens=models.prompt_tokens, output_tokens=models.output_tokens))
        stats.update(fidelity=result["summary"], interpretation=result["interpretation"],
                     reconstruction_score=result["final_score"], evaluation_status=result["status"],
                     evaluation_metric_version=result["metric_version"], evaluation=metadata)
        page, markdown = render_report(stats, paragraphs, chunks, debate, result)
        outputs = {
            "artifacts/evaluation.json": json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            "reconstruction.txt": reconstruction + "\n",
            "statistics.json": json.dumps(stats, indent=2, ensure_ascii=False) + "\n",
            "index.html": page,
            "report.md": markdown,
        }
        for name, text in outputs.items():
            trace.text("published/" + name, text)
        for name, digest in source_hashes.items():
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Source artifact changed during evaluation: {name}")
        # Publish only after evaluation and report rendering finish; preserve
        # the original graph, run timing, status, model counts and event stream.
        for name, text in outputs.items():
            raw = text.encode("utf-8")
            destination = directory / name
            pending = destination.with_name(destination.name + "." + identifier + ".tmp")
            pending.write_bytes(raw)
            pending.replace(destination)
            manifest.setdefault("artifacts", {})[name] = dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        manifest["evaluation"] = metadata
        manifest_path = directory / "manifest.json"
        pending = manifest_path.with_name("manifest." + identifier + ".tmp")
        pending.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        pending.replace(manifest_path)
        trace.emit("evaluation.published", source_run=manifest["run_id"], final_score=result["final_score"])
        print(f"Reconstruction score: {result['final_score']}", flush=True)
        print(f"Report: {directory / 'index.html'}", flush=True)
        return result
    except BaseException as exc:
        metadata.update(status="failed", error=str(exc), error_type=type(exc).__name__)
        trace.emit("evaluation.failed", error=str(exc), error_type=type(exc).__name__)
        raise
    finally:
        trace.save("manifest.json", metadata)
        trace.close()


def main():
    from dotenv import load_dotenv
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--host", default=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    parser.add_argument("--resume-evaluation", type=Path, help="Reuse validated responses from this evaluation trace")
    parser.add_argument("--document-context-tokens", type=int)
    parser.add_argument("--document-output-tokens", type=int)
    args = parser.parse_args()
    if any(value is not None and value < 1 for value in (args.document_context_tokens, args.document_output_tokens)):
        parser.error("Token limits must be positive")
    result = evaluate_saved_run(args.directory, args.host, resume=args.resume_evaluation,
                               document_context_tokens=args.document_context_tokens,
                               document_output_tokens=args.document_output_tokens)
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
