# Debate pipeline results

Run: `run_20261120_030946_UTC-0500_dff62c9d`

Incomplete extraction in 2 chunk(s): chunk_004, chunk_005. 7 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 23. See `artifacts/unresolved_items.json`.

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
- Graph nodes: 140
- Graph edges: 64
- Accepted background proposals: 2 / 57
- Reconstruction score (0–100): not evaluated
- Domain relationships: 64
- Isolated domain nodes: 43

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.168 | 0.163 | 0.145 | 0.000 | 0.348 |
| idea_order_agreement | 0.750 | 1.000 | 0.500 | 0.000 | 1.000 |
| rouge_l_f1 | 0.686 | 0.719 | 0.123 | 0.511 | 0.793 |
| length_similarity | 0.917 | 0.912 | 0.052 | 0.862 | 0.983 |
| final_score | 44.028 | 49.233 | 18.661 | 17.202 | 60.445 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)

Evaluation incomplete: One or more chunks could not be evaluated. No complete-document score is available.
