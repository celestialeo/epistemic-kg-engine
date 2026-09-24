"""Compare the existing graph logic with evidence-filtered background, offline from Neo4j."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .factscore import (CachedModels, PassageIndex, atomic_claims, check_background, digest,
                        evaluate_reconstruction, load_references, precision, save_json)
from .factscore_report import compare_results, write_report
from .graph_view import build_graph, write_graph

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT_FILES = {"chunks.json": "chunks", "concepts.json": "concepts", "extractions.json": "extractions",
                  "mentions.json": "mentions", "relations.json": "relations"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_source(source):
    for filename, key in {**DOCUMENT_FILES, "background_approved.json": "approved_edges", "document.json": "results"}.items():
        data = read_json(source / filename)
        if not isinstance(data, dict) or not isinstance(data.get(key), list):
            raise ValueError(f"Invalid comparison input: {filename} needs a {key} list.")
        if any("error" in row for row in data[key]):
            raise ValueError(f"Cannot compare incomplete source artifacts: {filename} contains errors.")
    chunks = read_json(source / "chunks.json")["chunks"]
    rows = read_json(source / "document.json")["results"]
    originals = {r["chunk_id"]: r["text"] for r in chunks}
    if not rows or len(originals) != len(chunks) or len({r["chunk_id"] for r in rows}) != len(rows):
        raise ValueError("Comparison needs nonempty unique chunks and document evaluation rows.")
    if set(originals) != {r["chunk_id"] for r in rows}:
        raise ValueError("Document evaluation must cover exactly the source chunks.")
    for row in rows:
        if " ".join(row["original"].split()) != " ".join(originals[row["chunk_id"]].split()):
            raise ValueError(f"Source text mismatch: {row['chunk_id']}")
        if row.get("background_lines"):
            raise ValueError("Document evaluation must not contain background hints.")
    return rows


def background_hints(edges, concepts, kind, per_concept=3, maximum=8):
    """Mirror current loader/retriever relation scope and ranking from frozen rows."""
    from src.evaluate_graph_fidelity import filter_background_rows, format_background_lines
    from src.load_background_to_neo4j import resolve_score
    if kind in {"metadata", "noise"}:
        return [], []
    # Neo4j MERGE keeps the last loaded row for a repeated directed relation.
    unique = {}
    for edge in edges:
        relation = edge["relation_type"].upper()
        if relation not in {"IS_A", "HAS_PART", "REQUIRES_UNDERSTANDING_OF"}:
            continue
        row = {"source_concept": edge["source_concept"], "target_concept": edge["target_concept"],
               "relation_type": relation, "justification": edge.get("justification", ""),
               "confidence": resolve_score(edge)}
        unique[(row["source_concept"], relation, row["target_concept"])] = row
    selected = []
    for concept in dict.fromkeys(concepts):
        candidates = [r for r in unique.values() if r["source_concept"] == concept]
        candidates.sort(key=lambda r: (-r["confidence"], r["target_concept"], r["relation_type"]))
        selected.extend(candidates[:per_concept])
    selected.sort(key=lambda r: (-r["confidence"], r["source_concept"], r["target_concept"], r["relation_type"]))
    selected = filter_background_rows(selected, unit_kind=kind)
    return selected, format_background_lines(selected, maximum)


def evaluate_arm(row, edges, source_claims, models):
    from src.evaluate_graph_fidelity import build_prompt, cosine_bow, cosine_dense, jaccard
    if row.get("bypass_llm"):
        # Preserve the original card; these rows never enter comparison statistics.
        return {**row, "claim_evaluation": {"excluded": "verbatim bypass"}}
    background_rows, background_lines = background_hints(edges, row["concepts"], row["unit_kind"])
    prompt = build_prompt(row["unit_kind"], row["concepts"], row.get("relation_lines"), background_lines,
                          row.get("key_predicate", ""), row.get("anchor_phrases"))
    generated = models.generate(prompt)
    original = row["original"]
    claims = evaluate_reconstruction(original, generated, source_claims, models)
    jac, bow = jaccard(original, generated), cosine_bow(original, generated)
    emb = cosine_dense(models.embed(original), models.embed(generated))
    if not math.isfinite(emb):
        raise ValueError("Embedding similarity is not finite.")
    threshold = row.get("scores", {}).get("threshold", .7)
    return {**row, "regenerated": generated, "used_background": bool(background_lines),
            "background_rows": background_rows, "background_lines": background_lines,
            "reconstruction_prompt": prompt, "claim_evaluation": claims,
            "scores": {"embedding_cosine": emb, "jaccard": jac, "bow_cosine": bow,
                       "lexical_combined": (jac + bow) / 2, "threshold": threshold, "pass": emb >= threshold,
                       **{key: claims[key] for key in ("source_precision", "source_coverage", "source_f1")}}}


def write_arm_results(path, rows, embedding):
    scored = [r for r in rows if "scores" in r and not r.get("error")]
    def mean(key):
        return sum(r["scores"][key] for r in scored) / len(scored) if scored else 0
    summary = {"rows": len(rows), "ok": len(scored), "errors": len(rows) - len(scored),
               "pass": sum(r["scores"]["pass"] for r in scored),
               "fail": sum(not r["scores"]["pass"] for r in scored),
               "avg_embedding_cosine": mean("embedding_cosine"), "avg_lexical_combined": mean("lexical_combined"),
               "embedding_model": embedding, "include_relations": True, "include_background": True}
    save_json(path, {"summary": summary, "results": rows})


def write_comparison_graph(out, run_id):
    manifest_path = out / "manifest.json"
    settings = read_json(manifest_path) if manifest_path.exists() else {}
    graphs = {}
    for arm in ("baseline", "factscore"):
        graph = build_graph(out / arm)
        graphs[arm] = graph
        save_json(out / arm / "graph.json", graph)
        write_graph(out / arm, f"{run_id} / {arm}" + (" / PILOT" if settings.get("pilot") else ""))
    data = {"run_id": run_id, "pilot": settings.get("pilot", False),
            "evidence_mode": settings.get("evidence_mode", "unspecified"), **graphs}
    payload = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("graph_comparison.html").read_text(encoding="utf-8")
    (out / "graph_comparison.html").write_text(template.replace("__COMPARISON_DATA__", payload), encoding="utf-8")


def get_model_details(names):
    from ollama import Client
    client = Client(timeout=30)
    details = {}
    available = client.list().models
    for name in set(names):
        info = client.show(name)
        match = next((m for m in available if m.model in {name, name + ":latest"}), None)
        details[name] = {"digest": match.digest if match else None, "details": info.details.model_dump() if info.details else {}}
    return details


def select_document_rows(filename, rows, chunk_ids, concepts):
    if filename in {"chunks.json", "extractions.json"}:
        return [r for r in rows if r.get("chunk_id") in chunk_ids]
    if filename == "mentions.json":
        return [r for r in rows if r.get("from_chunk_id") in chunk_ids]
    if filename == "relations.json":
        unit_ids = {"ku::" + cid for cid in chunk_ids}
        return [r for r in rows if r.get("ku_id") in unit_ids]
    return [r for r in rows if r.get("id") in concepts]


def run_comparison(source, out, references=None, verifier=None, models=None, progress=print, limit=0, edge_limit=0, resume=False):
    source, out = Path(source).resolve(), Path(out).resolve()
    hints = validate_source(source)
    if limit < 0 or edge_limit < 0:
        raise ValueError("Pilot limits must be nonnegative; zero means all.")
    if limit:
        hints = hints[:limit]
    selected_ids = {r["chunk_id"] for r in hints}
    selected_concepts = {c for r in hints for c in r["concepts"]}
    saved = read_json(source / "manifest.json")
    generator, embedding = saved["model"], saved["embedding_model"]
    verifier = verifier or generator
    previous = read_json(out / "manifest.json") if resume else None
    if previous:
        if previous.get("status") not in {"interrupted", "failed", "partial"}:
            raise ValueError("Resume requires an interrupted, failed or partial comparison, not a running or complete one.")
        for name, expected in previous["source_hashes"].items():
            if digest(read_json(source / name)) != expected:
                raise ValueError(f"Cannot resume: baseline {name} changed.")
        if (previous.get("chunk_limit", 0), previous.get("edge_limit", 0)) != (limit, edge_limit):
            raise ValueError("Cannot change pilot limits while resuming.")
        if (generator, verifier, embedding) != (previous["generator"], previous["verifier"], previous["embedding"]):
            raise ValueError("Cannot change models while resuming.")
        # Scoring semantics must stay fixed, even when the viewer or report changes.
        for path in [Path(__file__).with_name("factscore.py"), ROOT / "src/evaluate_graph_fidelity.py", ROOT / "src/load_background_to_neo4j.py"]:
            if digest(path.read_text(encoding="utf-8")) != previous["implementation_hashes"][path.name]:
                raise ValueError(f"Cannot resume: scoring implementation {path.name} changed. Create a new comparison.")
    passages = load_references(references or (out / "references.json" if resume else source / "chunks.json"))
    mode = previous["evidence_mode"] if previous else "external_reference_collection" if references else "input_document_only"
    if previous and digest(passages) != previous["reference_hash"]:
        raise ValueError("Cannot resume: reference evidence changed.")
    if not resume and out.exists() and any(out.iterdir()):
        raise ValueError("Comparison output must be new or empty; previous experiments are preserved.")
    details = get_model_details([generator, verifier, embedding]) if models is None else {"test_backend": True}
    if previous and details != previous["model_details"]:
        raise ValueError("Cannot resume: installed model versions changed.")
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    hashes = {}
    for arm in ("baseline", "factscore"):
        (out / arm).mkdir(exist_ok=resume)
        for filename in DOCUMENT_FILES:
            document = read_json(source / filename)
            hashes[filename] = digest(document)
            if limit:
                key = DOCUMENT_FILES[filename]
                document = {**document, key: select_document_rows(filename, document[key], selected_ids, selected_concepts)}
            save_json(out / arm / filename, document)
    for filename in ("document.json", "background_approved.json", "manifest.json"):
        shutil.copyfile(source / filename, out / ("source_" + filename))
        hashes[filename] = digest(read_json(source / filename))
    save_json(out / "references.json", {"passages": passages})
    code_files = [*Path(__file__).parent.glob("factscore*.py"), ROOT / "src/evaluate_graph_fidelity.py",
                  ROOT / "src/load_background_to_neo4j.py", Path(__file__).with_name("graph_view.py")]
    manifest = {"status": "running", "created_at": datetime.now(timezone.utc).isoformat(),
                "source_run": saved["run_id"], "source_directory": str(source), "source_hashes": hashes,
                "implementation_hashes": {p.name: digest(p.read_text(encoding="utf-8")) for p in code_files},
                "generator": generator, "verifier": verifier, "embedding": embedding, "model_details": details,
                "reference_hash": digest(passages), "reference_count": len(passages), "evidence_mode": mode,
                "reference_input": str(Path(references).resolve()) if references else None,
                "seed": 7, "temperature": 0, "retrieval": "BM25", "top_k": 5,
                "background_per_concept": 3, "max_background": 8, "approval_policy": "all_claims_supported",
                "pilot": bool(limit or edge_limit), "chunk_limit": limit, "edge_limit": edge_limit,
                "evaluated_chunks": len(hints),
                "errors": []}
    if previous:
        manifest["attempt_history"] = previous.get("attempt_history", []) + [
            {k: v for k, v in previous.items() if k != "attempt_history"}]
        manifest["reference_input"] = previous.get("reference_input")
        progress("Resuming with frozen evidence and successful cached model responses; failed calls will be retried.")
    save_json(out / "manifest.json", manifest)
    models = models or CachedModels(generator, verifier, embedding, out / "model_cache.json", details)
    errors, checked, results = [], [], {"baseline": [], "factscore": []}
    try:
        index = PassageIndex(passages)
        baseline_data = read_json(source / "background_approved.json")
        edges = baseline_data["approved_edges"]
        if limit:
            edges = [r for r in edges if r["source_concept"] in selected_concepts]
        if edge_limit:
            from src.load_background_to_neo4j import resolve_score
            edges = sorted(edges, key=lambda r: (-resolve_score(r), r["source_concept"],
                                                 r["relation_type"], r["target_concept"]))[:edge_limit]
        for i, edge in enumerate(edges, 1):
            progress(f"Background evidence {i}/{len(edges)}: {edge['source_concept']} -> {edge['target_concept']}")
            try:
                checked.append(check_background(edge, index, models))
            except Exception as exc:
                message = f"Background edge {i}: {exc}"
                errors.append(message)
                checked.append({**edge, "error": str(exc), "evidence_accepted": False})
            save_json(out / "background_checks.json", {"edges": checked})
        retained = [r for r in checked if r.get("evidence_accepted")]
        removed = [r for r in checked if not r.get("evidence_accepted")]
        # Baseline keeps every original edge; audit annotations do not alter ranking.
        save_json(out / "baseline/background_approved.json", {**baseline_data, "approved_edges": checked})
        save_json(out / "factscore/background_approved.json", {
            "approved_edges": retained, "rejected_edges": baseline_data.get("rejected_edges", []) +
            [{**r, "status": "rejected", "rejection_stage": "evidence"} for r in removed]})
        write_comparison_graph(out, saved["run_id"])
        for i, row in enumerate(hints, 1):
            progress(f"Reconstruction comparison {i}/{len(hints)}: {row['chunk_id']}")
            try:
                source_claims = [] if row.get("bypass_llm") else atomic_claims(row["original"], models)
            except Exception as exc:
                errors.append(f"Source claims {row['chunk_id']}: {exc}")
                for arm in results:
                    results[arm].append({"chunk_id": row["chunk_id"], "error": str(exc)})
                continue
            for arm, arm_edges in [("baseline", edges), ("factscore", retained)]:
                try:
                    result = evaluate_arm(row, arm_edges, source_claims, models)
                except Exception as exc:
                    errors.append(f"{arm} {row['chunk_id']}: {exc}")
                    result = {"chunk_id": row["chunk_id"], "error": str(exc)}
                results[arm].append(result)
                write_arm_results(out / arm / "fidelity.json", results[arm], embedding)
        verdicts = [v for r in checked if not r.get("error") for v in r["claim_checks"]]
        kept_verdicts = [v for r in retained for v in r["claim_checks"]]
        background = {"baseline_edges": len(edges), "retained_edges": len(retained), "removed_edges": len(removed),
                      "checked_edges": sum(not r.get("error") for r in checked),
                      "errors": sum(bool(r.get("error")) for r in checked),
                      "claims": len(verdicts), "supported_claims": sum(v["status"] == "supported" for v in verdicts),
                      "precision": precision(verdicts), "retained_claims": len(kept_verdicts),
                      "retained_supported_claims": sum(v["status"] == "supported" for v in kept_verdicts),
                      "retained_precision": precision(kept_verdicts)}
        data = {**manifest, "status": "partial" if errors else "complete", "errors": errors,
                "metrics": compare_results(results["baseline"], results["factscore"]), "background": background,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "model_calls": getattr(models, "calls", None), "cache_hits": getattr(models, "hits", None)}
        for arm in results:
            write_arm_results(out / arm / "fidelity.json", results[arm], embedding)
            subprocess.run([sys.executable, str(ROOT / "src/report_fidelity.py"), "--in", str(out / arm / "fidelity.json"),
                            "--out", str(out / arm / "fidelity.html"), "--title", arm], check=True, capture_output=True)
        write_report(out, data, results["baseline"], results["factscore"], checked)
        save_json(out / "manifest.json", data)
        progress(f"Comparison report: {out / 'report.html'}")
        return data
    except BaseException as exc:
        save_json(out / "manifest.json", {**manifest, "status": "failed", "errors": errors + [str(exc)]})
        raise
