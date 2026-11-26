# Debate pipeline results

Run: `run_20261020_213236_UTC-0400_36bf60bd`

Incomplete extraction in 5 chunk(s): chunk_002, chunk_004, chunk_005, chunk_006, chunk_007. 8 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 10. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| meaning changed | 14 |
| wrong direction | 9 |
| wrong kind | 7 |
| unsupported claim | 5 |

- Paragraphs: 3
- Sequential chunks: 7
- Graph nodes: 126
- Graph edges: 42
- Accepted background proposals: 2 / 63
- Reconstruction score (0–100): not evaluated
- Domain relationships: 42
- Isolated domain nodes: 67

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.499 | 0.558 | 0.285 | 0.154 | 0.800 |
| idea_order_agreement | 0.944 | 1.000 | 0.136 | 0.667 | 1.000 |
| rouge_l_f1 | 0.524 | 0.535 | 0.136 | 0.286 | 0.652 |
| length_similarity | 0.527 | 0.598 | 0.143 | 0.280 | 0.643 |
| final_score | 61.534 | 60.519 | 17.504 | 42.588 | 81.950 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: One or more chunks could not be evaluated. No complete-document score is available.
