# Debate pipeline results

Run: `run_20261123_114953_UTC-0500_b3126241`

Incomplete extraction in 2 chunk(s): chunk_004, chunk_005. 6 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 18. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| unsupported claim | 5 |
| meaning changed | 2 |
| wrong kind | 1 |
| wrong direction | 1 |

- Paragraphs: 5
- Sequential chunks: 5
- Graph nodes: 120
- Graph edges: 64
- Accepted background proposals: 4 / 54
- Reconstruction score (0–100): 52.637
- Domain relationships: 64
- Isolated domain nodes: 24

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.358 | 0.480 | 0.295 | 0.000 | 0.625 |
| idea_order_agreement | 0.800 | 1.000 | 0.447 | 0.000 | 1.000 |
| rouge_l_f1 | 0.686 | 0.683 | 0.071 | 0.594 | 0.785 |
| length_similarity | 0.946 | 0.953 | 0.019 | 0.923 | 0.967 |
| final_score | 55.995 | 67.139 | 25.651 | 15.532 | 76.750 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
