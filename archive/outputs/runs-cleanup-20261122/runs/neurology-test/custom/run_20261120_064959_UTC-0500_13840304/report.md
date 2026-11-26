# Debate pipeline results

Run: `run_20261120_064959_UTC-0500_13840304`

Incomplete extraction in 3 chunk(s): chunk_001, chunk_002, chunk_005. 8 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 17. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| unsupported claim | 8 |
| meaning changed | 3 |
| wrong direction | 1 |
| contradiction | 1 |

- Paragraphs: 5
- Sequential chunks: 5
- Graph nodes: 140
- Graph edges: 78
- Accepted background proposals: 1 / 17
- Reconstruction score (0–100): not evaluated
- Domain relationships: 78
- Isolated domain nodes: 26

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.443 | 0.452 | 0.161 | 0.207 | 0.615 |
| idea_order_agreement | 1.000 | 1.000 | 0.000 | 1.000 | 1.000 |
| rouge_l_f1 | 0.696 | 0.655 | 0.097 | 0.591 | 0.833 |
| length_similarity | 0.853 | 0.841 | 0.076 | 0.793 | 0.984 |
| final_score | 64.853 | 64.694 | 9.520 | 50.225 | 73.472 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: Document alignment reached its output/context limit; increase --document-context-tokens and --document-output-tokens. No complete-document score is available.
