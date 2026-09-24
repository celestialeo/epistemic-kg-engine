"""Paired statistics and offline HTML/Markdown reports for frozen experiments."""
import html
import json
import math
from pathlib import Path
import random
import re
import statistics
import warnings

from .factscore import save_json

METRICS = {
    "source_precision": "Supported reconstruction claims",
    "source_coverage": "Original claim coverage",
    "source_f1": "Claim precision/coverage F1",
    "embedding_cosine": "Embedding similarity",
    "lexical_combined": "Lexical similarity",
}


def paired_statistics(pairs, bootstrap_samples=2000):
    if not pairs:
        return {"n": 0, "baseline": None, "factscore": None, "delta": None, "ci95": None,
                "t_p": None, "wilcoxon_p": None, "test_note": "No valid matched pairs."}
    baseline, after = zip(*pairs)
    deltas = [b - a for a, b in pairs]
    mean = statistics.mean(deltas)
    result = {"n": len(pairs), "baseline": statistics.mean(baseline), "factscore": statistics.mean(after),
              "delta": mean, "improved": sum(d > 0 for d in deltas),
              "worsened": sum(d < 0 for d in deltas), "tied": sum(d == 0 for d in deltas),
              "ci95": None, "t_p": None, "wilcoxon_p": None, "test_note": ""}
    if len(pairs) < 2:
        result["test_note"] = "At least two matched chunks are required for uncertainty estimates."
        return result
    rng = random.Random(7)
    means = sorted(statistics.mean(rng.choices(deltas, k=len(deltas))) for _ in range(bootstrap_samples))
    result["ci95"] = [means[int(.025 * bootstrap_samples)], means[min(bootstrap_samples - 1, int(.975 * bootstrap_samples))]]
    if all(d == 0 for d in deltas):
        result.update(t_p=1.0, wilcoxon_p=1.0, test_note="All paired scores are identical.")
        return result
    from scipy.stats import ttest_rel, wilcoxon
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        if len(set(deltas)) > 1:
            value = float(ttest_rel(after, baseline).pvalue)
            result["t_p"] = value if math.isfinite(value) else None
        else:
            result["test_note"] = "Constant nonzero differences: paired t-test is undefined."
        try:
            value = float(wilcoxon(after, baseline, zero_method="wilcox").pvalue)
            result["wilcoxon_p"] = value if math.isfinite(value) else None
        except ValueError:
            pass
    return result


def compare_results(baseline, after):
    def eligible(rows):
        return {r["chunk_id"]: r for r in rows if not r.get("bypass_llm") and not r.get("error")}
    a, b = eligible(baseline), eligible(after)
    shared = sorted(a.keys() & b.keys())
    metrics = {}
    for key in METRICS:
        pairs = [(a[cid]["scores"].get(key), b[cid]["scores"].get(key)) for cid in shared]
        metrics[key] = paired_statistics([(x, y) for x, y in pairs
                                         if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)])
        metrics[key]["excluded_or_undefined"] = len(baseline) - metrics[key]["n"]
    return metrics


def number(value, signed=False):
    return "N/A" if value is None else format(value, "+.4f" if signed else ".4f")


def inline(text):
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    return re.sub(r'\[([^\]]+)\]\((https://[^\s)]+)\)', r'<a href="\2">\1</a>', text)


def report_lines(data):
    yield "# FActScore comparison"
    yield ""
    yield f"Source run: `{data['source_run']}`. Status: **{data['status']}**."
    yield ""
    if data.get("pilot"):
        yield (f"PILOT SAMPLE: {data['evaluated_chunks']} chunks; chunk limit {data['chunk_limit']}, "
               f"background edge limit {data['edge_limit']} (0 means all). Edges are selected by the existing usefulness "
               "score before evidence checking. This sample does not represent the complete graph or establish full-run improvements.")
        yield ""
    yield "## What changed"
    yield ""
    yield ("Both arms use identical saved document artifacts, current reconstruction prompts, models, seed and hint limits. "
           "The baseline uses the original approved background edges. The FActScore arm keeps an edge only when its "
           "relationship and every extracted justification claim are supported by retrieved evidence. Existing usefulness "
           "scores and ranking are retained. This measures evidence filtering, not a new candidate generator.")
    yield ""
    yield ("The baseline is a controlled replay of the current logic from saved artifacts; it may differ from historical "
           "with_background.json, which queried a shared live database. Identical prompts reuse the same cached reconstruction. "
           "Historical outputs are preserved in the source run.")
    yield ""
    yield "## Evidence and models"
    yield ""
    yield f"Background evidence: **{data['evidence_mode']}**, {data['reference_count']} passages."
    yield f"Reference SHA-256: `{data['reference_hash']}`. Frozen passages: `references.json`."
    yield f"Generator: `{data['generator']}`. Verifier: `{data['verifier']}`. Embeddings: `{data['embedding']}`."
    yield ""
    if data["evidence_mode"] == "input_document_only":
        yield ("This run uses the input document as its background reference. Unsupported additions may be true but absent "
               "from the document. This is a source-support experiment, not independent external fact verification.")
        yield ""
    yield ("Reconstruction precision checks generated atomic claims against the original chunk. Coverage checks original "
           "claims against the reconstruction. Coverage and their F1 are extensions to FActScore. This is a reconstruction "
           "proxy for graph fidelity, not a direct proof that all knowledge is encoded in the graph. An empty generated "
           "claim set has undefined precision, not 100%; metric-specific valid pair counts are reported.")
    yield ""
    yield "## Matched chunk results"
    yield ""
    yield "| Metric | Pairs | Baseline | FActScore | Change | 95% change interval | t-test p | Wilcoxon p |"
    yield "| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |"
    for key, row in data["metrics"].items():
        ci = "N/A" if row["ci95"] is None else " to ".join(number(v, True) for v in row["ci95"])
        yield (f"| {METRICS[key]} | {row['n']} | {number(row['baseline'])} | {number(row['factscore'])} | "
               f"{number(row['delta'], True)} | {ci} | {number(row['t_p'])} | {number(row['wilcoxon_p'])} |")
    yield ""
    for key, row in data["metrics"].items():
        direction = "not estimable" if row["delta"] is None else "increased" if row["delta"] > 0 else "decreased" if row["delta"] < 0 else "unchanged"
        yield f"- {METRICS[key]}: {direction}; {row['excluded_or_undefined']} chunks excluded or undefined. {row['test_note']}"
    yield ""
    yield ("Intervals are deterministic paired percentile bootstrap intervals (2,000 resamples; seed 7). Tests are two-sided "
           "and exploratory, without multiple-comparison correction. Metadata/noise copied verbatim and errors are excluded. "
           "Chunks are the resampling unit; chunks from one document may be dependent. These are within-run estimates, "
           "not evidence of generalization across documents or repeated model runs. A small p-value does not measure effect size.")
    yield ""
    yield "## Background graph changes"
    yield ""
    bg = data["background"]
    yield f"- Baseline edges: {bg['baseline_edges']}; retained: {bg['retained_edges']}; removed: {bg['removed_edges']}."
    yield f"- Successfully checked edges: {bg['checked_edges']}; checker errors: {bg['errors']}."
    yield f"- Baseline supported claims / checked claims: {bg['supported_claims']} / {bg['claims']} ({number(bg['precision'])})."
    yield f"- Retained supported claims / checked claims: {bg['retained_supported_claims']} / {bg['retained_claims']} ({number(bg['retained_precision'])})."
    yield ""
    yield ("The retained background score is a selection diagnostic: it uses the same judgments that filtered the edges, "
           "so its increase is expected by construction and is not independent proof of improved factual accuracy. "
           "Inspect retained counts and reconstruction coverage alongside precision. Judge errors are not counted as false claims. "
           "Validate a sample of decisions with human labels or an independent evaluator before making accuracy claims.")
    yield ""
    yield "## Audit and limitations"
    yield ""
    yield ("This local Ollama/BM25 implementation adapts the atomic-claim/evidence method from "
           "[Min et al. (2023)](https://arxiv.org/pdf/2305.14251); it does not reproduce the paper's released estimator, "
           "biography benchmark, or reported accuracy. Exact evidence citations are validated, but entailment judgments "
           "and claim decomposition can still be wrong. Retrieval can miss evidence, especially synonyms. "
           "No background recall score is claimed because there is no gold set of missing background facts.")
    yield ""
    yield ("Saved artifacts: `baseline/`, `factscore/`, `background_checks.json`, `comparison.json`, `manifest.json`, "
           "`references.json`, and `model_cache.json`. Open `graph_comparison.html` to inspect both graphs; open each arm's "
           "`fidelity.html` for reconstruction details. The source snapshot and implementation fingerprint are recorded in the manifest.")
    if data["errors"]:
        yield ""
        yield "## Errors requiring review"
        yield ""
        for error in data["errors"]:
            yield "- " + error.replace("\n", " ")


def write_report(out, data, baseline, after, checked):
    save_json(out / "comparison.json", data)
    lines = list(report_lines(data))
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # A small, escaped renderer keeps the report standalone without dependencies.
    body, in_table = [], False
    for line in lines:
        if line.startswith("| "):
            if line.startswith("| ---"):
                continue
            if not in_table:
                body.append("<table>")
                in_table = True
            body.append("<tr>" + "".join("<td>" + html.escape(c.strip()) + "</td>" for c in line.strip("|").split("|")) + "</tr>")
        else:
            if in_table:
                body.append("</table>")
                in_table = False
            tag = "h1" if line.startswith("# ") else "h2" if line.startswith("## ") else "p"
            body.append(f"<{tag}>{inline(line.lstrip('# '))}</{tag}>")
    if in_table:
        body.append("</table>")
    chart = []
    for key, row in data["metrics"].items():
        chart.append(f"<p><b>{html.escape(METRICS[key])}</b></p>")
        for arm, color in [("baseline", "#2877cc"), ("factscore", "#26734d")]:
            value = row[arm]
            chart.append(f'<div>{arm}: {number(value)} <meter min="0" max="1" value="{max(0, value or 0)}" style="accent-color:{color}"></meter></div>')
    details = ["<h2>Per-chunk claim audit</h2>"]
    for arm, rows in [("Baseline", baseline), ("FActScore", after)]:
        for row in rows:
            details.append(f"<details><summary>{arm}: {html.escape(row['chunk_id'])}</summary><pre>{html.escape(json.dumps(row, indent=2, ensure_ascii=False))}</pre></details>")
    details.append("<h2>Background evidence decisions</h2>")
    for edge in checked:
        name = f"{edge['source_concept']} {edge['relation_type']} {edge['target_concept']}"
        label = "retained" if edge.get("evidence_accepted") else "checker error" if edge.get("error") else "removed"
        details.append(f"<details><summary>{html.escape(name)} — {label}</summary><pre>{html.escape(json.dumps(edge, indent=2, ensure_ascii=False))}</pre></details>")
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>FActScore comparison report</title><style>body{font:16px system-ui;max-width:1200px;margin:35px auto;padding:20px;color:#17283e;line-height:1.6}'
            'table{border-collapse:collapse;display:block;overflow:auto}td{padding:8px;border:1px solid #ccd5df}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6fa;padding:16px}'
            'meter{width:220px}details{margin:10px 0}summary{cursor:pointer}a{color:#175bc1}</style>'
            '<nav><a href="graph_comparison.html">Compare graphs</a> · <a href="report.md">Download Markdown report</a> · '
            '<a href="comparison.json">Statistics JSON</a> · <a href="baseline/fidelity.html">Baseline reconstruction</a> · '
            '<a href="factscore/fidelity.html">FActScore reconstruction</a></nav>'
            + "".join(body) + "<h2>Mean scores</h2>" + "".join(chart) + "".join(details) + "</html>")
    (out / "report.html").write_text(page, encoding="utf-8")
