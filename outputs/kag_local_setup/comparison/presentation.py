"""Comparable artifact names and metrics, with KAG-specific stages labeled honestly."""
from collections import Counter
import copy
import html
import json
from pathlib import Path


def render_graph(graph):
    # Reuse the existing interactive viewer without changing its frozen source.
    # Map only display origins; evaluation always receives the unmodified projection.
    display = copy.deepcopy(graph)
    for edge in display["edges"]:
        if edge["origin"] == "kag_index":
            edge["origin"] = "background"
    for node in display["nodes"]:
        if node["kind"] not in {"concept", "event"}:
            node["origin"] = "background"
    payload = json.dumps(display, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("baseline").joinpath("graph_view.html").read_text(encoding="utf-8")
    replacements = {
        "Document knowledge": "KAG domain relations",
        "Background additions": "KAG index / schema structure",
        "Document concept used in background": "Shared concept",
        "> Background</label>": "> Index structure</label>",
        "Event nodes are marked E and connect to their objects through acts_on.": "KAG events are marked E; index and text nodes are marked T.",
        "Concepts use their names. Background facts appear as orange relationships, with explanations and scores in this panel.": "Select native KAG entities or relationships to inspect their saved properties. Orange marks index structure.",
        "Document knowledge is model-extracted from your text. Background knowledge is model-generated enrichment. Colors describe origin, not correctness. Scores are not calibrated probabilities.": "This graph displays KAG output. Orange index links and text/schema nodes are excluded from relational reconstruction. Colors do not indicate correctness.",
        "Extracted from document": "KAG domain relation",
        "Generated background knowledge": "KAG index structure",
        "In document and used in background": "Shared concept",
    }
    for before, after in replacements.items():
        template = template.replace(before, after)
    return template.replace("__GRAPH_DATA__", payload)


def statistics(graph, chunks, evaluation, models, observer, trace):
    return {
        "run_id": trace.run_id,
        "input": {"chunks": len(chunks), "words": sum(c["word_count"] for c in chunks),
                  "source_coverage": 1.0, "chunking": "upstream KAG length_splitter; zero overlap"},
        "graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
                  "node_kinds": dict(Counter(n["kind"] for n in graph["nodes"])),
                  "edge_origins": dict(Counter(e["origin"] for e in graph["edges"]))},
        "models": {"generation": models.model, "embedding": models.embedding_model,
                   "kag_generation_calls": observer.calls, "kag_embedding_calls": observer.embedding_calls,
                   "evaluation_calls": models.calls, "evaluation_retries": models.retries,
                   "prompt_tokens": observer.prompt_tokens + models.prompt_tokens,
                   "output_tokens": observer.output_tokens + models.output_tokens},
        "fidelity": evaluation["summary"], "document_metrics": evaluation["document_metrics"],
        "reconstruction_score": evaluation["final_score"], "evaluation_status": evaluation["status"],
        "evaluation_metric_version": evaluation["metric_version"], "weights": evaluation["weights"],
        "interpretation": evaluation["interpretation"],
        "debate": {"status": "not_applicable", "reason": "Native KAG construction has no baseline debate stage"},
        "unresolved_items": getattr(trace, "unresolved_items", []),
    }


def render_report(stats, evaluation):
    esc = lambda value: html.escape(str(value))
    fmt = lambda value: "not available" if value is None else f"{value:.4f}"
    metrics = evaluation.get("document_metrics") or {}
    rows = "".join(f"<tr><td>{esc(name)}</td><td>{weight:.0%}</td><td>{fmt(metrics.get(name))}</td></tr>"
                   for name, weight in evaluation["weights"].items())
    pairs = "".join(f"<details><summary>{esc(row['chunk_id'])}: {fmt(row['final_score'])}</summary>"
                    f"<div class='pair'><div><h3>Source</h3><p>{esc(row['original'])}</p></div>"
                    f"<div><h3>Reconstruction</h3><p>{esc(row['reconstruction'])}</p></div></div>"
                    f"<p>{esc(row['reason'])}</p></details>" for row in evaluation["results"])
    links = {"knowledge_graph.html": "Explore graph", "reconstruction.txt": "Reconstructed text",
             "statistics.json": "Statistics", "manifest.json": "Run manifest", "events.jsonl": "Event log",
             "artifacts/kag_graph.json": "Native KAG subgraphs", "artifacts/graph.json": "Graph projection",
             "artifacts/evaluation.json": "Detailed evaluation", "artifacts/kag_schema.json": "KAG schema",
             "artifacts/extractions.json": "Extracted relations", "run.log": "Console and KAG logs"}
    nav = " | ".join(f'<a href="{path}">{label}</a>' for path, label in links.items())
    note = ("KAG performs extraction, vectorization, post-processing, and writer normalization. "
            "A local schema provider and file transport replace the OpenSPG backend; no Docker or database is used. "
            "The evaluator is an unchanged snapshot from epistemic-kg-engine. "
            "It sees only projected chunk-local domain relations, never original text, node descriptions, "
            "knowledge-unit prose, embeddings, or index links. KAG chunk boundaries differ from the baseline's "
            "85-word chunks; the complete-document metrics and weights are the same. "
            "No debate, source-entailment review, or background expansion from the baseline is run.")
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>KAG water-cycle results</title>
<style>body{{font:16px/1.6 system-ui;margin:32px auto;padding:0 20px;max-width:1100px;background:#f4f7fa;color:#213047}}
section,details{{background:white;border:1px solid #dbe3ec;border-radius:10px;padding:18px;margin:16px 0}}
a{{color:#176394}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:8px;border-bottom:1px solid #ddd}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}summary{{cursor:pointer}}@media(max-width:650px){{.pair{{grid-template-columns:1fr}}}}</style>
<h1>KAG water-cycle results</h1><p>{esc(stats['run_id'])}</p><nav>{nav}</nav>
<section><h2>Reconstruction score: {fmt(evaluation['final_score'])} / 100</h2>
<p>Status: {esc(evaluation['status'])}. {esc(evaluation.get('reason') or '')}</p>
<p>Native model / projection issues recorded: {len(stats.get('comparison_issues', []))}.
<a href="artifacts/comparison_issues.json">Inspect issues</a>. The score measures the available projected domain relations.</p>
<table><tr><th>Metric</th><th>Weight</th><th>Complete document</th></tr>{rows}</table></section>
<section><h2>What was measured</h2><p>{esc(note)}</p><p>{esc(evaluation['interpretation'])}</p></section>
<section><h2>Graph and model usage</h2><p>{stats['graph']['nodes']} nodes; {stats['graph']['edges']} edge occurrences.</p>
<p>{stats['models']['kag_generation_calls']} KAG language-model calls; {stats['models']['kag_embedding_calls']} embedding calls;
{stats['models']['evaluation_calls']} evaluator calls.</p></section><h2>Chunk reconstructions</h2>{pairs}</html>'''
    markdown = f"# KAG water-cycle results\n\nRun: {stats['run_id']}\n\nScore: {fmt(evaluation['final_score'])} / 100\n\n"
    markdown += f"Status: {evaluation['status']}\n\n{note}\n\n"
    markdown += f"Native model / projection issues: {len(stats.get('comparison_issues', []))}. See [issue details](artifacts/comparison_issues.json).\n\n"
    markdown += "| Metric | Weight | Complete document |\n| --- | ---: | ---: |\n"
    markdown += "".join(f"| {name} | {weight:.0%} | {fmt(metrics.get(name))} |\n"
                        for name, weight in evaluation["weights"].items())
    markdown += "\n" + "\n".join(f"- [{label}]({path})" for path, label in links.items()) + "\n"
    return page, markdown
