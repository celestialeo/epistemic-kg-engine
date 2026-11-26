# Debate pipeline results

Run: `run_20261004_202728_UTC-0400_389ecba2`

Incomplete extraction in 5 chunk(s): chunk_001, chunk_002, chunk_004, chunk_006, chunk_007. 7 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 7. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| wrong direction | 13 |
| meaning changed | 11 |
| unsupported claim | 6 |
| wrong kind | 4 |
| contradiction | 1 |

- Paragraphs: 3
- Sequential chunks: 7
- Graph nodes: 132
- Graph edges: 55
- Accepted background proposals: 7 / 161
- Reconstruction score (0–100): not evaluated
- Domain relationships: 55
- Isolated domain nodes: 50

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.941 | 1.000 | 0.132 | 0.645 | 1.000 |
| idea_order_agreement | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 |
| rouge_l_f1 | 0.994 | 1.000 | 0.014 | 0.962 | 1.000 |
| length_similarity | 0.988 | 1.000 | 0.027 | 0.926 | 1.000 |
| final_score | 96.565 | 100.000 | 7.350 | 80.308 | 100.000 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

Reconstruction score (0–100): None

[Rebuilt text](reconstruction.txt)
