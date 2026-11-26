# Debate pipeline results

Run: `run_20261115_220514_UTC-0500_9a81c296`

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| meaning changed | 1 |
| wrong direction | 1 |

- Paragraphs: 1
- Sequential chunks: 1
- Graph nodes: 9
- Graph edges: 5
- Accepted background proposals: 3 / 8
- Reconstruction score (0–100): 78.953
- Domain relationships: 5
- Isolated domain nodes: 0

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| claim_fidelity_f1 | 1.000 | 1.000 | n/a | 1.000 | 1.000 |
| idea_order_agreement | 0.400 | 0.400 | n/a | 0.400 | 0.400 |
| rouge_l_f1 | 0.395 | 0.395 | n/a | 0.395 | 0.395 |
| length_similarity | 1.000 | 1.000 | n/a | 1.000 | 1.000 |
| final_score | 78.953 | 78.953 | n/a | 78.953 | 78.953 |

Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. Components range from 0 to 1; the weighted final score ranges from 0 to 100. Summary statistics describe chunks; final_score compares the complete texts and is null when evaluation is incomplete. A single matched idea has order agreement 1; no matches have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts and metric version fixed across runs. These scores are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.

[Complete rebuilt text](reconstruction.txt) · [Detailed evaluation scores](artifacts/evaluation.json)
