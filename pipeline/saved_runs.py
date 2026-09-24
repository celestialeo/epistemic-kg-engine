"""Discover saved runs and plan graph restoration without model calls."""
import json
from pathlib import Path

from .plan import Step


def read_manifest(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]:
        raise ValueError(f"Invalid run manifest: {directory}")
    return manifest


def discover_runs(root):
    runs = []
    for path in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            runs.append((path.parent, read_manifest(path.parent)))
        except (OSError, ValueError):
            continue
    return runs


def restore_plan(out, manifest):
    source = manifest["run_id"]
    steps = []
    for name, script, flag, filename in [
        ("load_chunks", "load_chunks_to_neo4j.py", "--chunks", "chunks.json"),
        ("load_concepts", "load_concepts_to_neo4j.py", "--concepts", "concepts.json"),
        ("load_units", "load_kus_to_neo4j.py", "--extractions", "extractions.json"),
        ("load_mentions", "load_mentions_to_neo4j.py", "--mentions", "mentions.json"),
        ("load_relations", "load_epistemic_relations_to_neo4j.py", "--relations", "relations.json"),
        ("enrich_chunks", "enrich_chunks_in_neo4j.py", "--extractions", "extractions.json"),
    ]:
        args = [flag, str(out / filename)]
        if name not in {"load_mentions", "enrich_chunks"}:
            args += ["--source-type", source]
        steps.append(Step(name, script, tuple(args)))
    background = out / "background_approved.json"
    if background.exists() and json.loads(background.read_text(encoding="utf-8"))["approved_edges"]:
        steps.append(Step("load_background", "load_background_to_neo4j.py",
                          ("--in", str(background), "--with-facts")))
    for label in ("concepts_only", "document", "with_background"):
        if (out / (label + ".json")).exists() and not (out / (label + ".html")).exists():
            steps.append(Step("report_" + label, "report_fidelity.py",
                              ("--in", str(out / (label + ".json")),
                               "--out", str(out / (label + ".html")), "--title", label)))
    return steps


def resolve_run(value, runs_root):
    direct = Path(value).expanduser()
    directory = direct if direct.is_dir() else runs_root / value
    directory = directory.resolve()
    if not (directory / "manifest.json").is_file():
        raise ValueError(f"Saved run not found: {value}. Use --list-runs to see available runs.")
    return directory
