# Local KAG water-cycle experiment

Run from PowerShell:

```powershell
cd C:\Users\miche\Desktop\KAG-water-cycle
.\.venv\Scripts\python.exe -u .\run_water_cycle.py
```

The default input is `comparison/data/water_cycle_sample.txt`, an unchanged copy
of the simplified water-cycle document from `epistemic-kg-engine`.
Ollama must be running with `qwen3.5:9b` and `nomic-embed-text` installed.
No Docker, OpenSPG server, database, or cloud API is used.

For a new installation, run `setup_water_cycle.ps1 -PythonVersion 3.11` first.
Use `--check-only` to verify model availability, embedding dimensions, schema,
component initialization and coverage of the complete input without extraction
or scoring. Check artifacts go into `outputs/checks/`.

## Processing

1. Native KAG TXTReader and LengthSplitter (500 characters, no overlap).
2. Native KnowledgeUnitSchemaFreeExtractor: entity recognition, knowledge units,
   conditional triples and graph assembly using KAG's original prompts/parsers.
3. Native BatchVectorizer with local Ollama embeddings.
4. Native KAGPostProcessor filtering, with database similarity search disabled.
5. Native KGWriter normalization with a local file transport replacing GraphClient.
6. Separate projection of domain relations for reconstruction and visualization.
7. The unchanged baseline reconstruction and evaluation code from your original
   project, including chunk scores and full-document fidelity scoring.

The tracked upstream `kag/` and `knext/` source remains unchanged at commit
`fdab15b3929d2ee40dfcdd388f90233096a6afc9`. Local adaptations live in `comparison/`.
This is a KAG builder with local storage, not an execution of the OpenSPG backend
or KAG's question-answering solver. No baseline debate stage is added.

The schema is parsed using the upstream parser's `with_server=False` mode from
the upstream default template and index-manager definitions. Inherited `id`
and `name` properties are supplied locally (`name` is vectorized). Schema bindings
are scoped to single-threaded component initialization and restored afterward.
All schema definitions and effective configuration are exported per run.

KAG's Ollama client normally omits generation options. The local observer applies
temperature 0, seed 7, thinking disabled, 8192 context tokens and 4096 output tokens
to actual KAG calls; prompts and parsers are unchanged. The evaluator has the same
settings, with 16384/8192 tokens for full-document alignment. Actual requests,
responses, returned reasoning, retries and errors are logged. The local adapter
also supplies JSON output schemas matching the native English response shapes
(including comma-separated Core Entities and four-string conditional triples).
It preserves upstream prompt text and parsing, validates the parsed structures,
and propagates invalid/truncated responses into KAG's existing retry mechanism.
Effective response schemas are saved in `artifacts/kag_response_schemas.json`.
The local Ollama embedding subclass keeps one event loop for the client's full
lifetime. This fixes the upstream synchronous path's closed-loop failure on its
second embedding batch; embedding generation and batching are inherited unchanged.

## Results and later pipeline visualization

Every launch creates `outputs/runs/water-cycle-simplified/<UTC timestamp>_<id>/`:

| Artifact | Contents |
| --- | --- |
| `events.jsonl` | Ordered application events; replay by `sequence` with stage, entity, parent event, UTC/local time and full data |
| `run.log` | Console messages and upstream KAG logs |
| `manifest.json` | Configuration, status, input identity and artifact hashes |
| `input.txt` | Exact decoded source snapshot |
| `artifacts/chunks.json`, `kag_chunks.json` | Source ordering/offsets and native chunks |
| `artifacts/schema/`, `kag_schema.json` | Local schema definitions |
| `artifacts/kag/chunk_*/` | Extractor, vectorizer, postprocessor and writer snapshots |
| `artifacts/kag/writes/` | Persisted graphs from the file transport |
| `artifacts/kag_graph.json` | Complete collection of native subgraphs |
| `artifacts/kag_graph_occurrences.json` | Every native node and edge occurrence |
| `artifacts/graph.json` | Graph projection with stable typed node IDs and chunk provenance |
| `artifacts/extractions.json` | Relations and endpoints supplied to reconstruction |
| `reconstruction.txt` | Reproduced text, joined in source order |
| `artifacts/evaluation.json` | Detailed comparison, matched claims and final 0–100 score |
| `statistics.json`, `report.md`, `index.html` | Counts, scores and readable reports |
| `knowledge_graph.html` | Optional offline graph viewer; never opened automatically |
| `artifacts/environment.json` | Packages, model metadata/digests and adapter source hashes |
| `artifacts/comparison_issues.json` | Model and unresolved endpoint issues |

Component events include full input/output, and model events include actual
prompts and responses. The trace is application-level, not internal model execution.
Artifacts are flushed throughout a run. Failed runs retain `error.txt`, diagnostics,
available snapshots and a failed manifest. Each run has independent checkpoints.
Source/template hashes are verified before running. Existing results are retained.

Reconstruction sees only chunk-local domain relations, endpoint identities/types,
conditions and modality. Original prose, descriptions, knowledge-unit text and
embeddings are excluded; the evaluator receives original text for comparison.
The final document score weights claim fidelity 55%, idea order 25%, ROUGE-L 10%,
and length similarity 10%. It is not the average of the chunk scores.

Native occurrences are retained rather than simulating database upserts. Endpoint
type mismatches are reported, not silently repaired. Inspect issue counts beside
the score. Model judgments are not independent factual verification.

Exit codes: 0 completed (or readiness passed), 1 failed, 2 incomplete evaluation,
130 interrupted. Use `--input PATH` or `--output-root PATH` for optional overrides.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest comparison.test_local_pipeline -v
.\.venv\Scripts\python.exe -u run_water_cycle.py --check-only
```

The unit/integration fixtures exercise native graph construction and file output
with network access prohibited. They do not assert the factual quality of live models.
The check command contacts local Ollama and performs a small embedding probe.
