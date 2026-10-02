# Debate pipeline results

Run: `run_20260930_210144_UTC-0400_2bd37c70`

Incomplete extraction in 1 chunk(s): chunk_005. 1 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 1. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| meaning changed | 30 |
| wrong direction | 25 |
| unsupported claim | 24 |
| wrong kind | 15 |
| event link missing | 3 |

- Paragraphs: 3
- Sequential chunks: 7
- Graph nodes: 105
- Graph edges: 116
- Accepted proposals: 0 / 36
- Mean semantic similarity: 0.976

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| semantic_cosine | 0.976 | 0.996 | 0.040 | 0.898 | 1.000 |
| token_jaccard | 0.818 | 0.984 | 0.276 | 0.413 | 1.000 |
| token_cosine | 0.934 | 0.992 | 0.109 | 0.727 | 1.000 |

Reconstruction similarity, not factual accuracy. The same model serves all roles; debate judgments are not independent verification. No significance tests on one document.

Open `index.html` for the input, decisions and reconstructions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.
