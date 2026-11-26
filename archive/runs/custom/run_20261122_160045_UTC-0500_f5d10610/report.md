# Debate pipeline results

Run: `run_20261122_160045_UTC-0500_f5d10610`

Incomplete extraction in 2 chunk(s): chunk_004, chunk_005. 7 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 23. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| unsupported claim | 6 |
| meaning changed | 4 |
| wrong kind | 4 |
| wrong direction | 1 |

- Paragraphs: 5
- Sequential chunks: 5
- Graph nodes: 139
- Graph edges: 63
- Accepted background proposals: 1 / 63
- Reconstruction score (0–100): not evaluated
- Domain relationships: 63
- Isolated domain nodes: 42

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.488 | 0.588 | 0.237 | 0.100 | 0.700 |
| idea_order_agreement | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 |
| rouge_l_f1 | 0.685 | 0.701 | 0.116 | 0.511 | 0.823 |
| length_similarity | 0.916 | 0.906 | 0.044 | 0.866 | 0.983 |
| final_score | 67.831 | 74.038 | 14.140 | 44.543 | 80.702 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: Document alignment reached its output/context limit; increase --document-context-tokens and --document-output-tokens. No complete-document score is available.
