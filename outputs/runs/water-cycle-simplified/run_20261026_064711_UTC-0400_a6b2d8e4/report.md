# Debate pipeline results

Run: `run_20261026_064711_UTC-0400_a6b2d8e4`

Incomplete extraction in 4 chunk(s): chunk_001, chunk_004, chunk_006, chunk_007. 10 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 12. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| wrong direction | 13 |
| meaning changed | 10 |
| wrong kind | 5 |
| unsupported claim | 4 |

- Paragraphs: 3
- Sequential chunks: 7
- Graph nodes: 112
- Graph edges: 61
- Accepted background proposals: 11 / 210
- Reconstruction score (0–100): not evaluated
- Domain relationships: 61
- Isolated domain nodes: 36

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.552 | 0.546 | 0.209 | 0.286 | 0.870 |
| idea_order_agreement | 0.706 | 0.917 | 0.417 | 0.000 | 1.000 |
| rouge_l_f1 | 0.507 | 0.534 | 0.105 | 0.345 | 0.636 |
| length_similarity | 0.704 | 0.745 | 0.155 | 0.467 | 0.857 |
| final_score | 60.116 | 58.869 | 18.759 | 33.450 | 86.698 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: One or more chunks could not be evaluated. No complete-document score is available.
