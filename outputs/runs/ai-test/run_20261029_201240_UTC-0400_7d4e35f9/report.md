# Debate pipeline results

Run: `run_20261029_201240_UTC-0400_7d4e35f9`

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |

- Paragraphs: 1
- Sequential chunks: 1
- Graph nodes: 13
- Graph edges: 5
- Accepted background proposals: 0 / 12
- Reconstruction score (0–100): 94.952
- Domain relationships: 5
- Isolated domain nodes: 4

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 1.000 | 1.000 | n/a | 1.000 | 1.000 |
| idea_order_agreement | 1.000 | 1.000 | n/a | 1.000 | 1.000 |
| rouge_l_f1 | 0.688 | 0.688 | n/a | 0.688 | 0.688 |
| length_similarity | 0.808 | 0.808 | n/a | 0.808 | 0.808 |
| final_score | 94.952 | 94.952 | n/a | 94.952 | 94.952 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
