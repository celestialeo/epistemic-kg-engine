# Debate pipeline results

Run: `run_20261120_021541_UTC-0500_ae26f7eb`

Incomplete extraction in 2 chunk(s): chunk_004, chunk_005. 7 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 18. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| unsupported claim | 6 |
| wrong kind | 4 |
| meaning changed | 4 |
| wrong direction | 1 |

- Paragraphs: 5
- Sequential chunks: 5
- Graph nodes: 147
- Graph edges: 73
- Accepted background proposals: 11 / 57
- Reconstruction score (0–100): not evaluated
- Domain relationships: 73
- Isolated domain nodes: 40

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.108 | 0.125 | 0.101 | 0.000 | 0.200 |
| idea_order_agreement | 0.667 | 1.000 | 0.577 | 0.000 | 1.000 |
| rouge_l_f1 | 0.680 | 0.737 | 0.149 | 0.511 | 0.793 |
| length_similarity | 0.913 | 0.893 | 0.063 | 0.862 | 0.983 |
| final_score | 38.556 | 48.424 | 18.511 | 17.202 | 50.043 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: One or more chunks could not be evaluated. No complete-document score is available.
