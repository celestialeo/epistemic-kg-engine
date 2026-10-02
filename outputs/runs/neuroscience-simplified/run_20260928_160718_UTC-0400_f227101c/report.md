# Debate pipeline results

Run: `run_20260928_160718_UTC-0400_f227101c`

- Paragraphs: 3
- Sequential chunks: 8
- Graph nodes: 130
- Graph edges: 185
- Accepted proposals: 5 / 179
- Mean semantic similarity: 0.998

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| semantic_cosine | 0.998 | 1.000 | 0.005 | 0.987 | 1.000 |
| token_jaccard | 0.994 | 1.000 | 0.017 | 0.953 | 1.000 |
| token_cosine | 0.998 | 1.000 | 0.006 | 0.982 | 1.000 |

Reconstruction similarity, not factual accuracy. The same model serves all roles; debate judgments are not independent verification. No significance tests on one document.

Open `index.html` for the input, decisions and reconstructions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.
