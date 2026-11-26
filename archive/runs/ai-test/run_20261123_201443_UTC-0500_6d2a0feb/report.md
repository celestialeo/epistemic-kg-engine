# Debate pipeline results

Run: `run_20261123_201443_UTC-0500_6d2a0feb`

Incomplete extraction in 1 chunk(s): chunk_001. 1 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 2. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| unsupported claim | 1 |
| meaning changed | 1 |

- Paragraphs: 1
- Sequential chunks: 1
- Graph nodes: 14
- Graph edges: 8
- Accepted background proposals: 1 / 16
- Reconstruction score (0–100): 78.526
- Domain relationships: 8
- Isolated domain nodes: 5

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.727 | 0.727 | n/a | 0.727 | 0.727 |
| idea_order_agreement | 1.000 | 1.000 | n/a | 1.000 | 1.000 |
| rouge_l_f1 | 0.641 | 0.641 | n/a | 0.641 | 0.641 |
| length_similarity | 0.712 | 0.712 | n/a | 0.712 | 0.712 |
| final_score | 78.526 | 78.526 | n/a | 78.526 | 78.526 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
