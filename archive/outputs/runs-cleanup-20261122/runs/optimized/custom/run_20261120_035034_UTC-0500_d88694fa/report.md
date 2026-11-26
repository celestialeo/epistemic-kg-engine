# Debate pipeline results

Run: `run_20261120_035034_UTC-0500_d88694fa`

Incomplete extraction in 2 chunk(s): chunk_004, chunk_005. 7 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 21. See `artifacts/unresolved_items.json`.

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
- Graph nodes: 141
- Graph edges: 65
- Accepted background proposals: 3 / 58
- Reconstruction score (0–100): 42.377
- Domain relationships: 65
- Isolated domain nodes: 43

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 0.198 | 0.200 | 0.159 | 0.000 | 0.435 |
| idea_order_agreement | 0.800 | 1.000 | 0.447 | 0.000 | 1.000 |
| rouge_l_f1 | 0.679 | 0.701 | 0.107 | 0.511 | 0.793 |
| length_similarity | 0.907 | 0.893 | 0.051 | 0.862 | 0.983 |
| final_score | 46.756 | 50.043 | 17.789 | 17.202 | 65.227 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
