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
| claim_fidelity_f1 | 0.510 | 0.600 | 0.260 | 0.091 | 0.857 |
| idea_order_agreement | 0.690 | 1.000 | 0.413 | 0.000 | 1.000 |
| rouge_l_f1 | 0.503 | 0.458 | 0.163 | 0.327 | 0.842 |
| length_similarity | 0.708 | 0.659 | 0.224 | 0.387 | 0.966 |
| final_score | 57.416 | 53.482 | 22.166 | 23.791 | 90.219 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: Document alignment reached its output/context limit; increase --document-context-tokens and --document-output-tokens. No complete-document score is available.
