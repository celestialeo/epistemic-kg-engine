# Debate pipeline results

Run: `run_20261001_200823_UTC-0400_2a7d84f5`

Incomplete extraction in 2 chunk(s): chunk_001, chunk_004. 6 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 2. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| unsupported claim | 14 |
| meaning changed | 12 |
| wrong direction | 11 |
| wrong kind | 11 |
| quote too short | 1 |

- Paragraphs: 3
- Sequential chunks: 7
- Graph nodes: 130
- Graph edges: 161
- Accepted proposals: 6 / 74
- Text reconstruction similarity: 0.994
- Domain relationships: 26
- Isolated domain nodes: 48

| Metric | Mean | Median | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: |
| semantic_cosine | 0.994 | 1.000 | 0.014 | 0.964 | 1.000 |
| token_jaccard | 0.956 | 1.000 | 0.108 | 0.712 | 1.000 |
| token_cosine | 0.979 | 1.000 | 0.049 | 0.868 | 1.000 |

Reconstruction similarity, not factual accuracy. The same model serves all roles; debate judgments are not independent verification. No significance tests on one document.

Open `index.html` for the input, decisions and reconstructions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.
