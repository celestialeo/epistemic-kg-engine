# Debate pipeline results

Run: `run_20261004_202728_UTC-0400_389ecba2`

Incomplete extraction in 5 chunk(s): chunk_001, chunk_002, chunk_004, chunk_006, chunk_007. 7 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 7. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| wrong direction | 13 |
| meaning changed | 11 |
| unsupported claim | 6 |
| wrong kind | 4 |
| contradiction | 1 |

- Paragraphs: 3
- Sequential chunks: 7
- Graph nodes: 132
- Graph edges: 55
- Accepted background proposals: 7 / 161
- Domain relationships: 55
- Isolated domain nodes: 50


Extraction → Debate → Graph. Document relations retain source quotes; background relations are model knowledge. Review decisions are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.
