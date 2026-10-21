# Debate pipeline results

Run: `run_20261002_104618_UTC-0400_b7692622`

Incomplete extraction in 3 chunk(s): chunk_002, chunk_005, chunk_007. 3 unresolved records are retained for inspection. Valid records were preserved; these results do not represent complete extraction.

Unresolved items: 4. See `artifacts/unresolved_items.json`.

## Extraction rejection categories

Categories can overlap; unresolved reviews are separate.

| Category | Relations |
| --- | ---: |
| meaning changed | 9 |
| wrong kind | 6 |
| wrong direction | 6 |
| unsupported claim | 3 |

- Paragraphs: 3
- Sequential chunks: 7
- Graph nodes: 160
- Graph edges: 227
- Accepted background proposals: 15 / 207
- Domain relationships: 53
- Isolated domain nodes: 42


Extraction → Debate → Graph. Document relations retain source quotes; background relations are model knowledge. Review decisions are not external factual verification.

Open `index.html` for the input, relations and decisions. Use `events.jsonl` for simulation and `artifacts/graph.json` for the final graph.
