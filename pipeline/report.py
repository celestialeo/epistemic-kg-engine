"""A single readable results page, Markdown summary and machine-readable statistics."""
from collections import Counter
import html


def statistics_for(paragraphs, chunks, extractions, debate, graph, evaluation, models, trace):
    candidates = debate["candidates"]
    domain = {n["id"] for n in graph["nodes"] if n["kind"] in {"concept", "event"}}
    domain_edges = [e for e in graph["edges"] if e["source"] in domain and e["target"] in domain]
    connected = {e[k] for e in domain_edges for k in ("source", "target")}
    return {
        "run_id": trace.run_id,
        "unresolved_items": getattr(trace, "unresolved_items", []),
        "input": {"paragraphs": len(paragraphs), "chunks": len(chunks),
                  "words": sum(c["word_count"] for c in chunks), "source_coverage": 1.0,
                  "coverage_meaning": "Input word coverage only; not fact coverage"},
        "extraction": {"claims": sum(len(e["claims"]) for e in extractions),
                       "incomplete_chunks": [e["chunk_id"] for e in extractions if e.get("status") == "incomplete"],
                       "unresolved_records": sum(len(e.get("issues", [])) for e in extractions),
                       "relations": sum(len(e["relations"]) for e in extractions),
                       "reviewed": sum(r.get("review_status") != "unresolved"
                                       for r in debate.get("document_reviews", [])),
                       "review_attempted": len(debate.get("document_reviews", [])),
                       "semantic_rejections": sum(not r["accepted"] and r.get("review_status") != "unresolved"
                                                  for r in debate.get("document_reviews", [])),
                       "rejection_categories": dict(Counter(category
                           for r in debate.get("document_reviews", []) if not r["accepted"]
                           and r.get("review_status") != "unresolved"
                           for category in set(r.get("rejection_categories", []))).most_common()),
                       "unresolved_reviews": sum(r.get("review_status") == "unresolved"
                                                 for r in debate.get("document_reviews", [])),
                       "evidence_rejections": trace.counts["extraction.record_rejected"]},
        "debate": {"seeds": len(debate["seeds"]), "proposed": len(candidates),
                   "accepted": sum(bool(c["accepted"]) for c in candidates),
                   "rejected": sum(not c["accepted"] and c.get("review_status") != "unresolved" for c in candidates),
                   "unresolved": sum(c.get("review_status") == "unresolved" for c in candidates),
                   "unresolved_seeds": sum(t.get("status") == "unresolved" for t in debate.get("transcripts", [])),
                   "weights": debate["weights"], "dimensions": debate["dimensions"]},
        "graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"]),
                  "domain_nodes": len(domain), "domain_edges": len(domain_edges),
                  "provenance_edges": len(graph["edges"])-len(domain_edges), "isolated_domain_nodes": len(domain-connected),
                  "node_kinds": dict(Counter(n["kind"] for n in graph["nodes"])),
                  "edge_origins": dict(Counter(e["origin"] for e in graph["edges"]))},
        "models": {"generation": models.model, "embedding": models.embedding_model,
                   "registry": getattr(models, "registry_model", models.model),
                   "calls": models.calls, "retries": models.retries,
                   "cache_hits": models.cache_hits,
                   "embedding_calls": trace.counts["embedding.request"],
                   "prompt_tokens": models.prompt_tokens, "output_tokens": models.output_tokens},
        "fidelity": evaluation["summary"],
        "interpretation": evaluation["interpretation"]}


def render_report(stats, paragraphs, chunks, debate, evaluation):
    esc = lambda value: html.escape(str(value))
    metric = lambda value: f"{value:.3f}" if value is not None else "not evaluated"
    summary = stats["fidelity"]["semantic_cosine"]
    cards = [("Paragraphs", stats["input"]["paragraphs"]), ("Sequential chunks", stats["input"]["chunks"]),
             ("Graph nodes", stats["graph"]["nodes"]), ("Graph edges", stats["graph"]["edges"]),
             ("Accepted proposals", f"{stats['debate']['accepted']} / {stats['debate']['proposed']}"),
             ("Text reconstruction similarity", metric(summary["mean"]))]
    if "domain_edges" in stats["graph"]:
        cards.extend([("Domain relationships", stats["graph"]["domain_edges"]),
                      ("Isolated domain nodes", stats["graph"]["isolated_domain_nodes"])])
    incomplete = stats["extraction"]["incomplete_chunks"]
    quality_note = (f"Incomplete extraction in {len(incomplete)} chunk(s): " + ", ".join(incomplete) +
                    f". {stats['extraction']['unresolved_records']} unresolved records are retained for inspection. "
                    "Valid records were preserved; these results do not represent complete extraction.") if incomplete else ""
    quality_html = ('<section><h2>Incomplete extraction</h2><p>' + esc(quality_note) +
                    '</p><a href="artifacts/extraction_issues.json">Inspect unresolved records</a></section>') if incomplete else ""
    unresolved = stats.get("unresolved_items", [])
    if unresolved:
        quality_html += ('<section><h2>Unresolved items</h2><p>' + str(len(unresolved)) +
            ' items could not finish after recovery. They were excluded, and other items continued.</p>'
            '<a href="artifacts/unresolved_items.json">Inspect item failures</a></section>')
    category_counts = stats["extraction"].get("rejection_categories", {})
    rejection_html = ('<section><h2>Extraction rejection categories</h2><p>Completed semantic reviews only; '
        'one relation can have multiple causes. Unresolved reviews are counted separately.</p><table>'
        '<tr><th>Category</th><th>Relations</th></tr>' + ''.join(
            f'<tr><td>{esc(category.replace("_", " "))}</td><td>{count}</td></tr>'
            for category, count in category_counts.items()) +
        '</table><a href="artifacts/extraction_rejections.json">Inspect categorized rejections</a></section>')
    card_html = "".join(f'<div class="card"><strong>{esc(value)}</strong><span>{label}</span></div>' for label, value in cards)
    metric_rows = "".join(f"<tr><td>{esc(name.replace('_', ' '))}</td>" +
        "".join(f"<td>{values[k]:.3f}</td>" if values[k] is not None else "<td>n/a</td>"
                for k in ("mean", "median", "sample_stddev", "min", "max")) + "</tr>"
        for name, values in stats["fidelity"].items())
    paragraph_html = "".join(f'<p><b>{p["order"]+1}.</b> {esc(p["text"])}</p>' for p in paragraphs)
    chunk_html = "".join(f'<details><summary>{esc(c["id"])} · {esc(c["paragraph_id"])} · {c["word_count"]} words · '
        f'characters {c["start"]}–{c["end"]}</summary><p>{esc(c["text"])}</p></details>' for c in chunks)
    debate_html = ""
    for c in debate.get("document_reviews", []) + debate["candidates"]:
        label = "Unresolved" if c.get("review_status") == "unresolved" else "Accepted" if c["accepted"] else "Rejected"
        body = f'<p><b>Origin:</b> {esc(c.get("origin", "background"))}</p><p><b>Proposal:</b> {esc(c["reason"])}</p>'
        if c.get("evidence"):
            body += f'<p><b>Quote:</b> {esc(c["evidence"])}</p>'
        if c.get("duplicate_of"):
            body += f'<p>Combined with equivalent fact {esc(c["duplicate_of"])}; evidence retained.</p>'
        for key in ("reviewer", "critic", "rebuttal", "judge"):
            if c.get(key):
                body += f'<p><b>{key.title()}:</b> {esc(c[key]["reason"])}</p>'
        if c.get("score") is not None:
            if c.get("origin") == "background":
                body += f'<p>Chapter relevance score {c["score"]:.3f} (descriptive). Related topic: {esc(c.get("judge", {}).get("related_topic"))}. All semantic and chapter-relatedness gates must pass.</p>'
            else:
                body += f'<p>Chapter relevance {c["score"]:.3f}; minimum {c["threshold"]:.2f}. All semantic gates must pass.</p>'
        body += f'<p><b>Decision:</b> {esc(c["decision_reason"])}</p>'
        if c.get("gates"):
            body += '<p>' + esc(", ".join(k + ": " + ("pass" if v else "fail") for k, v in c["gates"].items())) + '</p>'
        debate_html += f'<details><summary><span class="{label.lower()}">{label}</span> · {esc(c["source"])} '
        debate_html += f'→ {esc(c["relation"])} → {esc(c["target"])}</summary>{body}</details>'
    reconstructions = "".join(f'<details><summary>{esc(r["chunk_id"])} · semantic similarity {metric(r["semantic_cosine"])}</summary>'
        f'<div class="pair"><div><h3>Original</h3><p>{esc(r["original"])}</p></div><div><h3>Reconstruction</h3>'
        f'<p>{esc(r["reconstruction"])}</p><p>{esc(r["reason"])}</p></div></div></details>' for r in evaluation["results"])
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Debate pipeline · Results</title><style>
:root{{color-scheme:light}}body{{font:16px/1.65 system-ui,sans-serif;color:#23324a;background:#f3f6fa;margin:0}}
main{{max-width:1120px;margin:40px auto;padding:0 24px}}h1{{font-size:38px;margin-bottom:0}}h2{{margin-top:36px}}
.muted{{color:#617187}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}
.card,section,details{{background:white;border:1px solid #dce3eb;border-radius:12px;padding:18px}}
.card strong{{display:block;font-size:30px;color:#185c86}}.card span{{color:#617187;font-size:14px}}
section{{margin-top:20px}}a{{color:#165e99}}nav{{display:flex;gap:20px;flex-wrap:wrap;margin:20px 0 28px}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #e4e9ef}}
details{{margin:10px 0}}summary{{cursor:pointer;font-weight:600}}.accepted{{color:#19724b}}.rejected{{color:#a74c30}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}@media(max-width:650px){{.pair{{grid-template-columns:1fr}}table{{font-size:12px}}}}
</style></head><body><main><p class="muted">DOCUMENT → CHUNKS → EXTRACTION → DEBATE → GRAPH</p>
<h1>Debate pipeline results</h1><p class="muted">{esc(stats['run_id'])}</p>
<nav><a href="knowledge_graph.html">Explore graph</a><a href="events.jsonl">Complete event log</a>
<a href="statistics.json">Statistics JSON</a><a href="report.md">Markdown report</a><a href="manifest.json">Run manifest</a></nav>
<div class="cards">{card_html}</div>
{quality_html}
{rejection_html}
<section><h2>Final statistical report</h2><table><thead><tr><th>Metric</th><th>Mean</th><th>Median</th><th>Sample SD</th><th>Min</th><th>Max</th></tr></thead>
<tbody>{metric_rows}</tbody></table><p>{esc(stats['interpretation'])}</p>
<p>{stats['models']['calls']} live model calls; {stats['models']['cache_hits']} reused responses; {stats['models']['retries']} retries; {stats['models']['prompt_tokens']:,} new prompt tokens; {stats['models']['output_tokens']:,} new output tokens.
{stats['extraction']['evidence_rejections']} extraction records rejected by evidence or structural validation.</p></section>
<section><h2>The input document</h2>{paragraph_html}<h3>Sequential chunks</h3>{chunk_html}</section>
<section><h2>Extraction and background review</h2><p>Extracted relations: one evidence reviewer. Background knowledge: proposer, critic, rebuttal and independent judge. These roles use {esc(stats['models']['generation'])}.
Isolated registry checks use {esc(stats['models']['registry'])}. Background knowledge need not appear in the chapter.
Every accepted relation passes semantic gates; model judgments are not external factual verification.
Open a decision to inspect its quote, arguments and checks.</p>{debate_html}</section>
<section><h2>Final graph reconstruction</h2>{reconstructions}</section>
<section><h2>Simulation data</h2><p><a href="events.jsonl">events.jsonl</a> is ordered by sequence and contains full requests, responses, parsing,
validation, decisions and graph mutations. Each event identifies its stage, entity, parent event and elapsed time.
The log captures explicit explanations and any reasoning the provider exposes; hidden internal thinking is unavailable.</p>
<p><a href="artifacts/graph.json">Final graph</a> · <a href="artifacts/debate.json">Debate transcripts</a> ·
<a href="artifacts/chunks.json">Chunks and source offsets</a> · <a href="artifacts/evaluation.json">Evaluation</a> ·
<a href="artifacts/relations.json">Relation registry</a> · <a href="artifacts/concepts.json">Concept aliases</a> ·
<a href="artifacts/chapter_outline.json">Chapter segments</a> · <a href="artifacts/seeds.json">Seed assessments</a> ·
<a href="artifacts/extraction_review.json">Extraction reviews</a> ·
<a href="artifacts/extraction_quality.json">Review counts by chunk</a> ·
<a href="artifacts/extraction_issues.json">Unresolved extraction records</a></p></section>
</main></body></html>'''
    markdown = f"# Debate pipeline results\n\nRun: `{stats['run_id']}`\n\n"
    markdown += (quality_note + "\n\n") if quality_note else ""
    if unresolved:
        markdown += f"Unresolved items: {len(unresolved)}. See `artifacts/unresolved_items.json`.\n\n"
    markdown += "## Extraction rejection categories\n\nCategories can overlap; unresolved reviews are separate.\n\n"
    markdown += "| Category | Relations |\n| --- | ---: |\n"
    markdown += "".join(f"| {category.replace('_', ' ')} | {count} |\n" for category, count in category_counts.items()) + "\n"
    markdown += "\n".join(f"- {name}: {value}" for name, value in cards) + "\n\n"
    markdown += "| Metric | Mean | Median | Sample SD | Min | Max |\n| --- | ---: | ---: | ---: | ---: | ---: |\n"
    for key, values in stats["fidelity"].items():
        markdown += "| " + key + " | " + " | ".join(f"{values[k]:.3f}" if values[k] is not None else "n/a"
                      for k in ("mean", "median", "sample_stddev", "min", "max")) + " |\n"
    markdown += "\n" + stats["interpretation"] + "\n\nOpen `index.html` for the input, decisions and reconstructions. "
    markdown += "Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.\n"
    return page, markdown
