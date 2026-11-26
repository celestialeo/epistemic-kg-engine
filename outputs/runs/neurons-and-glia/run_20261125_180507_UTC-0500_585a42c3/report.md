# Debate pipeline results

Run: `run_20261125_180507_UTC-0500_585a42c3`

Unresolved items: 15. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| wrong direction | 1 |
| meaning changed | 1 |

- Paragraphs: 5
- Sequential chunks: 5
- Graph nodes: 68
- Graph edges: 54
- Accepted background proposals: 26 / 161
- Reconstruction score (0–100): 54.720
- Domain relationships: 54
- Isolated domain nodes: 9

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.357 | 0.500 | 0.230 | 0.000 | 0.533 |
| idea_order_agreement | 0.800 | 1.000 | 0.447 | 0.000 | 1.000 |
| rouge_l_f1 | 0.762 | 0.804 | 0.171 | 0.467 | 0.889 |
| length_similarity | 0.900 | 0.920 | 0.096 | 0.750 | 1.000 |
| final_score | 56.238 | 68.684 | 24.611 | 13.417 | 71.575 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
