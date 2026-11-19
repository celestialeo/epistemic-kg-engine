# Debate pipeline results

Run: `run_20261117_171329_UTC-0500_53240531`

Unresolved items: 1. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |

- Paragraphs: 1
- Sequential chunks: 1
- Graph nodes: 17
- Graph edges: 11
- Accepted background proposals: 7 / 24
- Reconstruction score (0–100): 15.880
- Domain relationships: 11
- Isolated domain nodes: 2

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.000 | 0.000 | n/a | 0.000 | 0.000 |
| idea_order_agreement | 0.000 | 0.000 | n/a | 0.000 | 0.000 |
| rouge_l_f1 | 0.612 | 0.612 | n/a | 0.612 | 0.612 |
| length_similarity | 0.976 | 0.976 | n/a | 0.976 | 0.976 |
| final_score | 15.880 | 15.880 | n/a | 15.880 | 15.880 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
