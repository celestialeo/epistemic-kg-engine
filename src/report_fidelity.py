"""Generate an HTML report for visual analysis of graph fidelity results."""

import argparse
import json
from pathlib import Path


_UNIT_KIND_COLORS = {
    "definition": "#3b6fd4",
    "example": "#7b4fb5",
    "metadata": "#888888",
    "navigation": "#2a9d5c",
    "support": "#c47a1e",
    "noise": "#b94040",
    "other": "#555555",
}

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui, sans-serif; background: #f4f5f7; color: #1a1a2e; font-size: 14px; }

header {
  background: #1a1a2e; color: #fff;
  padding: 20px 32px; border-bottom: 3px solid #3b6fd4;
}
header h1 { font-size: 20px; font-weight: 700; }
header p  { font-size: 13px; color: #aab; margin-top: 4px; }

.summary-bar {
  display: flex; gap: 16px; flex-wrap: wrap;
  padding: 16px 32px; background: #fff;
  border-bottom: 1px solid #dde; font-size: 13px;
}
.stat { display: flex; flex-direction: column; align-items: center; min-width: 90px; }
.stat .val { font-size: 22px; font-weight: 700; color: #1a1a2e; }
.stat .lbl { color: #888; font-size: 11px; margin-top: 2px; text-transform: uppercase; letter-spacing: .04em; }
.stat.pass .val { color: #2a9d5c; }
.stat.fail .val { color: #c0392b; }

.controls {
  padding: 12px 32px; background: #fff; border-bottom: 1px solid #dde;
  display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
}
.controls label { font-size: 12px; color: #555; font-weight: 600; }
select, input[type=range] { font-size: 12px; border: 1px solid #ccc; border-radius: 4px; padding: 3px 6px; }
#threshold-display { font-weight: 700; color: #3b6fd4; min-width: 30px; display: inline-block; }

main { padding: 24px 32px; display: flex; flex-direction: column; gap: 16px; }

.card {
  background: #fff; border-radius: 8px;
  border-left: 5px solid #ccc;
  box-shadow: 0 1px 4px rgba(0,0,0,.07);
  overflow: hidden;
  transition: box-shadow .15s;
}
.card:hover { box-shadow: 0 3px 12px rgba(0,0,0,.12); }
.card.pass { border-left-color: #2a9d5c; }
.card.fail { border-left-color: #c0392b; }

.card-header {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; background: #fafbfc;
  border-bottom: 1px solid #eee; cursor: pointer;
  user-select: none;
}
.card-header:hover { background: #f0f2f5; }
.chunk-id { font-weight: 700; font-size: 13px; color: #1a1a2e; min-width: 80px; }
.badge {
  font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px;
  color: #fff; text-transform: capitalize;
}
.score-group { display: flex; gap: 10px; margin-left: auto; align-items: center; flex-wrap: wrap; }
.score-pill {
  font-size: 12px; font-weight: 600; padding: 2px 10px; border-radius: 10px;
  background: #eef; color: #334;
}
.score-pill.primary { background: #1a1a2e; color: #fff; font-size: 13px; }
.score-pill.pass  { background: #d4edda; color: #155724; }
.score-pill.fail  { background: #f8d7da; color: #721c24; }
.toggle-icon { font-size: 16px; color: #888; transition: transform .2s; }
.card.open .toggle-icon { transform: rotate(90deg); }

.card-body { display: none; padding: 16px; }
.card.open .card-body { display: block; }

.text-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px;
}
.text-block { border-radius: 6px; padding: 12px 14px; font-size: 13px; line-height: 1.6; }
.text-block.original { background: #f0f4ff; border: 1px solid #c8d8f8; }
.text-block.regenerated { background: #f5f5f5; border: 1px solid #ddd; }
.text-block h4 { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #888; margin-bottom: 6px; }

.metrics-row { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.metric { font-size: 12px; color: #555; }
.metric span { font-weight: 700; color: #1a1a2e; }

.section-title {
  font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .06em; color: #888; margin-bottom: 6px;
}

.concepts-list { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.concept-tag {
  font-size: 11px; background: #eef; color: #334;
  padding: 2px 8px; border-radius: 10px; border: 1px solid #d0d8f0;
}

.bg-lines { font-size: 12px; color: #444; }
.bg-line { padding: 3px 0; border-bottom: 1px solid #f0f0f0; }
.bg-line:last-child { border-bottom: none; }
.rel-type { font-weight: 700; color: #3b6fd4; }

.no-bg { font-size: 12px; color: #aaa; font-style: italic; }

@media (max-width: 700px) {
  .text-grid { grid-template-columns: 1fr; }
  main { padding: 12px 10px; }
  .summary-bar { padding: 12px 10px; }
  .controls { padding: 10px 10px; }
}
"""

_JS = """
function applyFilters() {
  const kind = document.getElementById('filter-kind').value;
  const result = document.getElementById('filter-result').value;
  const threshold = parseFloat(document.getElementById('threshold-slider').value);
  const cards = document.querySelectorAll('.card[data-kind]');

  cards.forEach(card => {
    const cardKind = card.dataset.kind;
    const emb = parseFloat(card.dataset.emb);
    const passes = emb >= threshold;

    card.classList.toggle('pass', passes);
    card.classList.toggle('fail', !passes);

    // update primary score pill colour
    const pill = card.querySelector('.score-pill.primary');
    if (pill) {
      pill.classList.toggle('pass', passes);
      pill.classList.toggle('fail', !passes);
    }

    const kindMatch = kind === 'all' || cardKind === kind;
    const resultMatch = result === 'all'
      || (result === 'pass' && passes)
      || (result === 'fail' && !passes);

    card.style.display = (kindMatch && resultMatch) ? '' : 'none';
  });

  // recount visible
  const visible = [...cards].filter(c => c.style.display !== 'none');
  const passing = visible.filter(c => c.classList.contains('pass')).length;
  document.getElementById('visible-count').textContent =
    visible.length + ' chunks shown, ' + passing + ' passing';
}

document.getElementById('filter-kind').addEventListener('change', applyFilters);
document.getElementById('filter-result').addEventListener('change', applyFilters);
document.getElementById('threshold-slider').addEventListener('input', function() {
  document.getElementById('threshold-display').textContent = parseFloat(this.value).toFixed(2);
  applyFilters();
});

document.querySelectorAll('.card-header').forEach(header => {
  header.addEventListener('click', () => {
    header.parentElement.classList.toggle('open');
  });
});

// open failing cards by default for easy analysis
document.querySelectorAll('.card.fail').forEach(c => c.classList.add('open'));
"""


def badge_style(unit_kind: str) -> str:
    color = _UNIT_KIND_COLORS.get(unit_kind, "#555")
    return f'background:{color}'


def score_bar(value: float, width: int = 60) -> str:
    pct = max(0.0, min(1.0, value)) * 100
    color = "#2a9d5c" if value >= 0.7 else "#e67e22" if value >= 0.5 else "#c0392b"
    return (
        f'<div style="background:#eee;border-radius:3px;height:6px;width:{width}px;display:inline-block;vertical-align:middle;">'
        f'<div style="background:{color};border-radius:3px;height:6px;width:{pct*width/100:.1f}px;"></div>'
        f'</div>'
    )


def render_card(row: dict, default_threshold: float) -> str:
    chunk_id = row.get("chunk_id", "?")
    unit_kind = row.get("unit_kind", "other")
    concepts: list = row.get("concepts", [])
    original = row.get("original", "")
    regenerated = row.get("regenerated", "")
    scores = row.get("scores", {})
    emb = scores.get("embedding_cosine", 0.0)
    jac = scores.get("jaccard", 0.0)
    bow = scores.get("bow_cosine", 0.0)
    lex = scores.get("lexical_combined", 0.0)
    passed = emb >= default_threshold
    bypass_llm = row.get("bypass_llm", False)
    used_bg = row.get("used_background", False)
    bg_lines: list = row.get("background_lines") or []
    relation_lines: list = row.get("relation_lines") or []
    policy = row.get("relation_policy", "")
    key_predicate: str = row.get("key_predicate", "")
    anchor_phrases: list = row.get("anchor_phrases") or []

    pass_class = "pass" if passed else "fail"
    pass_label = "BYPASSED" if bypass_llm else ("PASS" if passed else "FAIL")

    badge = f'<span class="badge" style="{badge_style(unit_kind)}">{unit_kind}</span>'
    bypass_badge = '<span class="badge" style="background:#888;margin-left:4px;font-size:10px;">verbatim</span>' if bypass_llm else ""
    emb_pill = f'<span class="score-pill primary {pass_class}">emb {emb:.3f}</span>'
    lex_pill = f'<span class="score-pill">lex {lex:.3f}</span>'
    result_pill = f'<span class="score-pill {pass_class}">{pass_label}</span>'

    concept_tags = "".join(f'<span class="concept-tag">{c}</span>' for c in concepts) or '<span class="no-bg">none</span>'

    bg_html = ""
    if bg_lines:
        items = "".join(
            f'<div class="bg-line">'
            f'{_fmt_bg_line(line)}'
            f'</div>'
            for line in bg_lines
        )
        bg_html = f'<div class="bg-lines">{items}</div>'
    elif used_bg:
        bg_html = '<span class="no-bg">fetched but filtered out</span>'
    else:
        bg_html = '<span class="no-bg">not used</span>'

    rel_html = ""
    if relation_lines:
        items = "".join(f'<div class="bg-line">{line}</div>' for line in relation_lines)
        rel_html = f'<div class="bg-lines">{items}</div>'
    else:
        rel_html = f'<span class="no-bg">none (policy: {policy})</span>'

    kp_html = (
        f'<div style="margin-bottom:12px;"><span class="section-title">Key predicate</span> '
        f'<span style="font-size:13px;font-style:italic;color:#3b6fd4;">{_esc(key_predicate)}</span></div>'
        if key_predicate else ""
    )
    ap_html = (
        f'<div style="margin-bottom:12px;"><span class="section-title">Anchor phrases</span> '
        + "".join(f'<span class="concept-tag" style="background:#fff3cd;border-color:#ffc107;">{_esc(a)}</span>' for a in anchor_phrases)
        + "</div>"
        if anchor_phrases else ""
    )

    return f"""
<div class="card {pass_class}" data-kind="{unit_kind}" data-emb="{emb:.4f}">
  <div class="card-header">
    <span class="chunk-id">{chunk_id}</span>
    {badge}{bypass_badge}
    <div class="score-group">
      {emb_pill}
      {lex_pill}
      {result_pill}
      {score_bar(emb)}
    </div>
    <span class="toggle-icon">▶</span>
  </div>
  <div class="card-body">
    <div class="text-grid">
      <div class="text-block original">
        <h4>Original</h4>
        {_esc(original)}
      </div>
      <div class="text-block regenerated">
        <h4>{'Stored verbatim (bypassed LLM)' if bypass_llm else 'Regenerated from graph'}</h4>
        {_esc(regenerated)}
      </div>
    </div>
    <div class="metrics-row">
      <span class="metric">Embedding cosine: <span>{emb:.4f}</span></span>
      <span class="metric">Jaccard: <span>{jac:.4f}</span></span>
      <span class="metric">BOW cosine: <span>{bow:.4f}</span></span>
      <span class="metric">Lexical combined: <span>{lex:.4f}</span></span>
    </div>
    <div class="section-title">Concepts used in prompt</div>
    <div class="concepts-list" style="margin-bottom:12px;">{concept_tags}</div>
    {kp_html}{ap_html}
    <div class="section-title">Relation hints</div>
    <div style="margin-bottom:12px;">{rel_html}</div>
    <div class="section-title">Background knowledge injected</div>
    <div>{bg_html}</div>
  </div>
</div>"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_bg_line(line: str) -> str:
    for rel in ("IS_A", "HAS_PART", "REQUIRES_UNDERSTANDING_OF"):
        if rel in line:
            line = line.replace(rel, f'<span class="rel-type">{rel}</span>')
            break
    return _esc(line).replace(f'&lt;span class=&quot;rel-type&quot;&gt;{rel}&lt;/span&gt;', f'<span class="rel-type">{rel}</span>')


def _fmt_bg_line(line: str) -> str:
    for rel in ("IS_A", "HAS_PART", "REQUIRES_UNDERSTANDING_OF"):
        if rel in line:
            before, _, after = line.partition(rel)
            return f"{_esc(before)}<span class='rel-type'>{rel}</span>{_esc(after)}"
    return _esc(line)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HTML fidelity report for visual analysis.")
    parser.add_argument("--in", dest="input", required=True, help="Fidelity JSON from evaluate_graph_fidelity.py")
    parser.add_argument("--out", default="outputs/fidelity_report.html", help="Output HTML file path.")
    parser.add_argument("--title", default="Graph Fidelity Report", help="Report title.")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    results: list = data.get("results", [])
    threshold = summary.get("threshold", 0.7) if "threshold" in summary else 0.7

    # infer threshold from first scored result if not in summary
    for r in results:
        t = r.get("scores", {}).get("threshold")
        if t is not None:
            threshold = t
            break

    total = summary.get("rows", len(results))
    passing = summary.get("pass", 0)
    failing = summary.get("fail", 0)
    avg_emb = summary.get("avg_embedding_cosine", 0.0)
    avg_lex = summary.get("avg_lexical_combined", 0.0)
    model = summary.get("embedding_model", "")
    include_bg = summary.get("include_background", False)
    include_rel = summary.get("include_relations", False)

    unit_kinds = sorted({r.get("unit_kind", "other") for r in results if "scores" in r})
    kind_options = '<option value="all">All unit kinds</option>' + "".join(
        f'<option value="{k}">{k.capitalize()}</option>' for k in unit_kinds
    )

    cards_html = "\n".join(render_card(r, threshold) for r in results if "scores" in r)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{args.title}</title>
<style>{_CSS}</style>
</head>
<body>

<header>
  <h1>{args.title}</h1>
  <p>Source: {args.input} &nbsp;|&nbsp; Model: {model} &nbsp;|&nbsp;
     Background: {'on' if include_bg else 'off'} &nbsp;|&nbsp;
     Relations: {'on' if include_rel else 'off'}</p>
</header>

<div class="summary-bar">
  <div class="stat"><span class="val">{total}</span><span class="lbl">Total chunks</span></div>
  <div class="stat pass"><span class="val">{passing}</span><span class="lbl">Passing</span></div>
  <div class="stat fail"><span class="val">{failing}</span><span class="lbl">Failing</span></div>
  <div class="stat"><span class="val">{avg_emb:.3f}</span><span class="lbl">Avg embedding</span></div>
  <div class="stat"><span class="val">{avg_lex:.3f}</span><span class="lbl">Avg lexical</span></div>
  <div class="stat"><span class="val">{passing/total*100:.0f}%</span><span class="lbl">Pass rate</span></div>
</div>

<div class="controls">
  <label>Unit kind</label>
  <select id="filter-kind">{kind_options}</select>
  <label>Result</label>
  <select id="filter-result">
    <option value="all">All</option>
    <option value="fail">Failing only</option>
    <option value="pass">Passing only</option>
  </select>
  <label>Threshold <span id="threshold-display">{threshold:.2f}</span></label>
  <input type="range" id="threshold-slider" min="0" max="1" step="0.01" value="{threshold}">
  <span id="visible-count" style="font-size:12px;color:#888;margin-left:auto;"></span>
</div>

<main>
{cards_html}
</main>

<script>{_JS}</script>
<script>applyFilters();</script>
</body>
</html>"""

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Saved report to {out_path}")


if __name__ == "__main__":
    main()
