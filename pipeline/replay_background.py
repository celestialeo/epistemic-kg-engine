"""Replay only background expansion from immutable saved document artifacts."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from .debate import debate
from .graph_view import build_graph, render_graph
from .models import Models
from .registry import ConceptRegistry, FactIndex, RelationRegistry
from .seeds import collect_seeds
from .trace import Trace


def load_document(source, models, trace):
    def read(name):
        return json.loads((source / "artifacts" / (name + ".json")).read_text(encoding="utf-8"))

    chunks, extractions, outline = read("chunks"), read("extractions"), read("chapter_outline")
    concepts, relations = ConceptRegistry(models, trace), RelationRegistry(models, trace)
    names = {name for extraction in extractions for name in extraction["concepts"]}
    saved = read("concepts")
    concepts.entries = {entry["name"]: entry for entry in saved["concepts"] if entry["name"] in names}
    concepts.chapter_names = sorted(names)
    # The final concept snapshot also contains aliases proposed by rejected
    # background candidates. Restore only pre-expansion document reconciliation.
    reconciliation = read("concept_reconciliation")
    concepts.aliases = {name: target for name, target in reconciliation["redirects"].items() if target in names}
    document_facts = [row for extraction in extractions for row in extraction["relations"] if row.get("accepted")]
    needed = {row["relation"] for row in document_facts}
    for contract in read("relations")["relations"]:
        if contract["key"] in needed:
            relations.entries[contract["key"]] = contract
    facts = FactIndex(relations)
    for row in document_facts:
        facts.add(row)
    return chunks, extractions, outline, concepts, relations, facts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/background_replays"))
    parser.add_argument("--reuse-seeds", action="store_true", help="Isolate proposal/admission changes using saved gaps")
    args = parser.parse_args(argv)
    source = args.source.resolve()
    if args.output_root.resolve().is_relative_to(source):
        parser.error("Replay output must be outside the saved source run")
    source_files = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in source.rglob("*") if p.is_file()}
    original = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    config = original["config"]
    run_id = "background_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    trace = Trace(args.output_root / run_id, run_id)
    started = time.monotonic()
    manifest = dict(run_id=run_id, source_run=str(source), scope="background_only", status="running",
                    source_hashes=source_files, reuse_seeds=args.reuse_seeds, config=config)
    manifest["code_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in Path(__file__).parent.glob("*.py")}
    trace.save("manifest.json", manifest)
    try:
        models = Models(trace, config["model"], config["embedding_model"],
                        os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                        think=config.get("think", False), context_tokens=config["context_tokens"],
                        max_output_tokens=config["max_output_tokens"], batch_size=config.get("batch_size", 4),
                        registry_model=config.get("registry_model"))
        chunks, extractions, outline, concepts, relations, facts = load_document(source, models, trace)
        trace.save("artifacts/unresolved_items.json", [])
        with trace.span("background"):
            if args.reuse_seeds:
                seeds = json.loads((source / "artifacts/seeds.json").read_text(encoding="utf-8"))["selected"]
                trace.save("artifacts/seeds.json", dict(selected=seeds, source_run=str(source)))
            else:
                seeds = collect_seeds(extractions, chunks, concepts, trace, outline=outline,
                                      limit=config.get("seed_limit", 0))
            result = debate(seeds, chunks, outline, concepts, relations, facts, models, trace,
                            proposal_limit=config.get("background_proposal_limit", 0))
            trace.save("artifacts/debate.json", result)
        # Render the accepted result using the existing graph builder; no extraction
        # or reconstruction/evaluation calls are repeated.
        text = (source / "input.txt").read_text(encoding="utf-8")
        paragraphs = json.loads((source / "artifacts/paragraphs.json").read_text(encoding="utf-8"))
        graph = build_graph(text, paragraphs, chunks, extractions, result, trace, concepts, relations)
        trace.save("artifacts/graph.json", graph)
        trace.text("knowledge_graph.html", render_graph(graph))
        rows = result["candidates"]
        summary = dict(seeds=len(seeds), proposed=len(rows), accepted=sum(row["accepted"] for row in rows),
                       statuses=dict(Counter(row["review_status"] for row in rows)),
                       rejection_stages=dict(Counter(row.get("rejection_stage") for row in rows if not row["accepted"])),
                       model_calls=models.calls, retries=models.retries,
                       duration_seconds=round(time.monotonic() - started, 2))
        trace.save("statistics.json", summary)
        manifest["status"] = "completed_with_issues" if getattr(trace, "unresolved_items", []) else "completed"
        print(json.dumps(dict(output=str(trace.directory), **summary), indent=2), flush=True)
    except BaseException as exc:
        manifest.update(status="failed", error=str(exc))
        raise
    finally:
        manifest["source_unchanged"] = all((source / name).is_file() and
            hashlib.sha256((source / name).read_bytes()).hexdigest() == digest
            for name, digest in source_files.items())
        trace.save("manifest.json", manifest)
        trace.close()


if __name__ == "__main__":
    main()
