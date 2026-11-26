# Debate pipeline results

Run: `run_20261122_132722_UTC-0500_6765d1cf`

Incomplete extraction in 1 chunk(s): chunk_001. 2 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 6. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| meaning changed | 2 |

- Paragraphs: 1
- Sequential chunks: 1
- Graph nodes: 16
- Graph edges: 9
- Accepted background proposals: 4 / 22
- Reconstruction score (0–100): 62.206
- Domain relationships: 9
- Isolated domain nodes: 5

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.444 | 0.444 | n/a | 0.444 | 0.444 |
| idea_order_agreement | 1.000 | 1.000 | n/a | 1.000 | 1.000 |
| rouge_l_f1 | 0.657 | 0.657 | n/a | 0.657 | 0.657 |
| length_similarity | 0.619 | 0.619 | n/a | 0.619 | 0.619 |
| final_score | 62.206 | 62.206 | n/a | 62.206 | 62.206 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
