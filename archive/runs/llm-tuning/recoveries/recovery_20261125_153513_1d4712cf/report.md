# Debate pipeline results

Run: `recovery_20261125_153513_1d4712cf`

Incomplete extraction in 4 chunk(s): chunk_001, chunk_003, chunk_004, chunk_005. 5 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 32. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| meaning changed | 11 |
| unsupported claim | 9 |
| wrong kind | 6 |
| wrong direction | 3 |

- Paragraphs: 6
- Sequential chunks: 6
- Graph nodes: 134
- Graph edges: 88
- Accepted background proposals: 9 / 128
- Reconstruction score (0–100): not evaluated
- Domain relationships: 88
- Isolated domain nodes: 39

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.285 | 0.294 | 0.132 | 0.087 | 0.444 |
| idea_order_agreement | 0.900 | 1.000 | 0.245 | 0.400 | 1.000 |
| rouge_l_f1 | 0.611 | 0.608 | 0.128 | 0.433 | 0.800 |
| length_similarity | 0.847 | 0.855 | 0.085 | 0.750 | 0.969 |
| final_score | 52.757 | 52.769 | 10.619 | 39.281 | 65.116 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: Model reached its output limit; increase --max-output-tokens (and --context-tokens if needed), or disable --think. No complete-document score is available.
