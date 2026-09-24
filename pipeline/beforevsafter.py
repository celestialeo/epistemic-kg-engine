"""A single entry point for browsing graphs, individual reports and statistics."""
import argparse
import html
import json
from pathlib import Path
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def comparisons(root):
    entries = []
    paths = set(root.glob("*/factscore/*/comparison.json")) | set(root.glob("factscore/*/comparison.json"))
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") in {"complete", "partial"}:
                entries.append((path.parent, data))
        except (OSError, ValueError):
            continue
    return sorted(entries, key=lambda item: item[1].get("created_at", item[0].name), reverse=True)


def resolve_comparison(value, root):
    entries = comparisons(root)
    if value and value != "latest":
        direct = Path(value).expanduser().resolve()
        if (direct / "comparison.json").is_file():
            return direct, json.loads((direct / "comparison.json").read_text(encoding="utf-8"))
        if (direct / "manifest.json").is_file():
            entries = comparisons(direct)
        entries = [(p, d) for p, d in entries if value in {p.name, d.get("source_run")} or p.parent.parent == direct]
    if not entries:
        raise ValueError("No finished comparison found. Use --run RUN_ID to create one, or --list to inspect saved comparisons.")
    return entries[0]


def display_number(value, signed=False):
    return "N/A" if value is None else format(value, "+.4f" if signed else ".4f")


def write_dashboard(out, data):
    from .factscore_experiment import write_comparison_graph
    required = ["baseline/fidelity.html", "factscore/fidelity.html", "report.html",
                "baseline/background_approved.json", "factscore/background_approved.json"]
    for name in required:
        if not (out / name).is_file():
            raise ValueError(f"This comparison is missing {name}; inspect its manifest and error log.")
    # Refresh only the graph presentation. No generation, evidence checks or scores change.
    write_comparison_graph(out, data["source_run"])
    escape = html.escape
    bg = data.get("background", {})
    pilot = data.get("pilot", False)
    scope = (f"PILOT — {data.get('evaluated_chunks', '?')} chunks; up to {data.get('edge_limit', '?')} baseline edges (0 means all). "
             "This is not the full graph comparison." if pilot else
             f"FULL SAVED RUN — {data.get('evaluated_chunks', '?')} chunks. No pilot limits.")
    evidence = ("Input document only; external factual accuracy has not been established."
                if data.get("evidence_mode") == "input_document_only" else "Supplied reference collection.")
    labels = {"source_precision": "Supported-claim precision", "source_coverage": "Original-claim coverage",
              "source_f1": "Claim F1", "embedding_cosine": "Embedding similarity", "lexical_combined": "Lexical similarity"}
    rows = []
    for key, item in data.get("metrics", {}).items():
        interval = "N/A" if item.get("ci95") is None else " to ".join(display_number(v, True) for v in item["ci95"])
        values = [labels.get(key, key), str(item.get("n", 0)), display_number(item.get("baseline")),
                  display_number(item.get("factscore")), display_number(item.get("delta"), True), interval,
                  display_number(item.get("t_p")), display_number(item.get("wilcoxon_p"))]
        rows.append("<tr>" + "".join("<td>" + escape(v) + "</td>" for v in values) + "</tr>")
    template = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Before vs after — graphs and reports</title><style>
*{box-sizing:border-box}body{margin:0;font:15px system-ui;background:#f5f7fb;color:#17283e}header{padding:20px 24px;background:white}h1{margin:0;font-size:27px}p{line-height:1.5}.scope{padding:10px;border-left:5px solid #c47a1e;background:#fff7df}.links,nav{display:flex;flex-wrap:wrap;gap:12px;align-items:center}a{color:#175bc1}button{padding:11px 17px;border:1px solid #aebdce;background:white;border-radius:6px;color:#17283e;cursor:pointer}button[aria-selected=true]{background:#17283e;color:white}nav{margin-top:18px}iframe{width:100%;height:85vh;border:0;background:white}.reports{display:grid;grid-template-columns:1fr 1fr;gap:2px}.reports h2{font-size:20px;padding:0 18px}.reports iframe{height:80vh}section[hidden]{display:none}#summary{padding:24px;overflow:auto}table{border-collapse:collapse;background:white}th,td{padding:10px;border:1px solid #ccd5df;text-align:left}caption{text-align:left;margin:10px 0;font-weight:bold}.muted{color:#52647a}@media(max-width:800px){.reports{grid-template-columns:1fr}}
</style><header><h1>Before vs after: graphs and reports</h1><p>__RUN__ · __STATUS__</p>
<p class="scope">__SCOPE__</p><p>Background edges: <b>__BEFORE__ before → __AFTER__ after</b>; __REMOVED__ removed. Evidence: __EVIDENCE__</p>
<div class="links"><a href="graph_comparison.html#all" target="_blank" rel="noopener">Graphs in a separate tab</a><a href="baseline/fidelity.html" target="_blank" rel="noopener">Before report</a><a href="factscore/fidelity.html" target="_blank" rel="noopener">After report</a><a href="report.html" target="_blank" rel="noopener">Full statistical report and claim audit</a><a href="report.md">Markdown document</a></div>
<nav role="tablist" aria-label="Comparison views"><button id="tab-graphs" role="tab" aria-selected="true" aria-controls="graphs" data-tab="graphs">1. Side-by-side graphs</button><button id="tab-reports" role="tab" aria-selected="false" aria-controls="reports" data-tab="reports">2. Before / after reports</button><button id="tab-summary" role="tab" aria-selected="false" aria-controls="summary" data-tab="summary">3. Statistics and what changed</button></nav></header>
<section id="graphs" role="tabpanel" aria-labelledby="tab-graphs"><iframe src="graph_comparison.html#all" title="Complete saved before and after graph snapshots"></iframe></section>
<section id="reports" role="tabpanel" aria-labelledby="tab-reports" hidden><div class="reports"><div><h2>Before: current logic</h2><iframe loading="lazy" src="baseline/fidelity.html" title="Baseline fidelity report"></iframe></div><div><h2>After: evidence-filtered background</h2><iframe loading="lazy" src="factscore/fidelity.html" title="FActScore fidelity report"></iframe></div></div></section>
<section id="summary" role="tabpanel" aria-labelledby="tab-summary" hidden><h2>Did the measured scores improve?</h2><p>Compare the same chunk IDs in the individual reports. Positive changes below mean higher measured scores; check coverage as well as precision. These are automated estimates, not proof of factual correctness.</p>
<table><caption>Matched chunk comparisons (after minus before)</caption><thead><tr><th>Metric</th><th>Pairs</th><th>Before</th><th>After</th><th>Change</th><th>95% change interval</th><th>t-test p</th><th>Wilcoxon p</th></tr></thead><tbody>__ROWS__</tbody></table>
<p>Small samples, dependent chunks and verifier mistakes limit these exploratory statistics. An interval including zero does not establish a directional change; a small p-value alone does not establish practical usefulness. Filtering with the same checker that scores retained edges is not independent validation.</p>
<p><a href="report.html" target="_blank" rel="noopener">Read the full method, error audit, evidence decisions and limitations</a></p><iframe loading="lazy" src="report.html" title="Detailed statistics and claim audit"></iframe></section>
<script>const tabs=[...document.querySelectorAll('[data-tab]')];function show(button){for(const tab of tabs){const selected=tab===button;tab.setAttribute('aria-selected',String(selected));document.getElementById(tab.dataset.tab).hidden=!selected}}for(const [index,button]of tabs.entries()){button.onclick=()=>show(button);button.onkeydown=event=>{if(event.key==='ArrowRight'||event.key==='ArrowLeft'){event.preventDefault();const next=tabs[(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length];next.focus();show(next)}}}</script></html>'''
    values = {"RUN": escape(str(data["source_run"])), "STATUS": escape(str(data.get("status", "unknown"))),
              "SCOPE": escape(scope), "BEFORE": str(bg.get("baseline_edges", "?")),
              "AFTER": str(bg.get("retained_edges", "?")), "REMOVED": str(bg.get("removed_edges", "?")),
              "EVIDENCE": escape(evidence), "ROWS": "".join(rows)}
    # Single-pass replacement prevents inserted source text from being treated as a template.
    import re
    page = re.sub(r"__([A-Z]+)__", lambda m: values[m[1]], template)
    target = out / "beforevsafter.html"
    target.write_text(page, encoding="utf-8")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description="View before/after graphs and reports together, or run a full saved-run comparison.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--view", nargs="?", const="latest", metavar="COMPARISON_OR_RUN", help="Open a saved comparison (default: latest). No services needed.")
    mode.add_argument("--run", metavar="RUN_ID_OR_DIRECTORY", help="Run a FULL comparison of a completed baseline, then open the dashboard. Requires Ollama.")
    mode.add_argument("--resume", metavar="COMPARISON_DIRECTORY_OR_ID", help="Resume an interrupted/failed/partial comparison with its frozen settings and model cache.")
    mode.add_argument("--list", action="store_true", help="List saved comparisons and whether they are pilot or full.")
    parser.add_argument("--reference", type=Path, help="With --run: reference passage JSON. Default: input-document support only.")
    parser.add_argument("--verifier", help="With --run: installed Ollama verification model.")
    parser.add_argument("--no-open", action="store_true", help="Generate the dashboard and print its path without opening a browser.")
    args = parser.parse_args(argv)
    try:
        root = ROOT / "outputs/runs"
        if (args.reference or args.verifier) and not args.run:
            raise ValueError("--reference and --verifier require --run RUN_ID.")
        if args.list:
            entries = comparisons(root)
            for path, data in entries:
                print(f"{'PILOT' if data.get('pilot') else 'FULL'} | {data.get('status')} | "
                      f"{data.get('evaluated_chunks', '?')} chunks | {data.get('source_run')} | {path.name}")
            if not entries:
                print("No completed or partial comparisons yet. Run with --run RUN_ID.")
            return 0
        result = 0
        if args.resume:
            from .factscore_experiment import run_comparison
            from dotenv import load_dotenv
            out = Path(args.resume).expanduser().resolve()
            if not (out / "manifest.json").exists():
                matches = list(root.glob("*/factscore/" + args.resume + "/manifest.json"))
                if len(matches) != 1:
                    raise ValueError("Provide the directory of the interrupted comparison.")
                out = matches[0].parent
            saved = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            load_dotenv(ROOT / ".env", override=False)
            data = run_comparison(Path(saved["source_directory"]), out, verifier=saved["verifier"],
                                  limit=saved.get("chunk_limit", 0), edge_limit=saved.get("edge_limit", 0), resume=True)
            result = 0 if data["status"] == "complete" else 1
        elif args.run:
            from .cli import main as pipeline_main
            from .saved_runs import resolve_run
            source = resolve_run(args.run, root)
            old_paths = {path for path, _ in comparisons(source)}
            command = ["--compare-factscore", args.run, "--no-open"]
            if args.reference:
                command += ["--factscore-reference", str(args.reference)]
            if args.verifier:
                command += ["--factscore-verifier", args.verifier]
            print("Running ALL saved chunks and ALL approved background edges; no pilot limits. This can take hours on a local model.", flush=True)
            result = pipeline_main(command)
            # A failed run must not silently open an old pilot as if it were new.
            fresh = [(p, d) for p, d in comparisons(source) if p not in old_paths]
            if not fresh:
                return result or 1
            out, data = fresh[0]
        else:
            out, data = resolve_comparison(args.view, root)
        page = write_dashboard(out, data)
        from .cli import update_comparison_links
        update_comparison_links(out.parent.parent)
        print(f"{'PILOT' if data.get('pilot') else 'FULL'} comparison: {page}")
        if data.get("pilot"):
            print("This saved result is a pilot. To create full graphs, use --run RUN_ID without pilot limits.")
        if not args.no_open and not webbrowser.open(page.resolve().as_uri()):
            print("Open the printed HTML file manually.")
        return result
    except (OSError, ValueError, KeyError, webbrowser.Error) as exc:
        print(f"Before/after viewer: {exc}", file=sys.stderr)
        return 1
