# Debate pipeline results

Run: `run_20260927_195431_UTC-0400_211683cb`

- Paragraphs: 3
- Sequential chunks: 8
- Graph nodes: 132
- Graph edges: 204
- Accepted proposals: 8 / 18
- Mean semantic similarity: 0.999

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| semantic_cosine | 0.999 | 1.000 | 0.002 | 0.994 | 1.000 |
| token_jaccard | 0.990 | 1.000 | 0.027 | 0.923 | 1.000 |
| token_cosine | 0.996 | 1.000 | 0.011 | 0.968 | 1.000 |

Reconstruction similarity, not factual accuracy. The same model serves all roles; debate judgments are not independent verification. No significance tests on one document.

Open `index.html` for the input, decisions and reconstructions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.
