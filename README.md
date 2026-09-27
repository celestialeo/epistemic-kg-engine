# Epistemic Knowledge Graph Engine

One pipeline turns a prose document into a knowledge graph through extraction,
background proposals, agent debate, and a final reconstruction evaluation.
The supplied [input](data/input.txt) contains three connected paragraphs (509
words) about neuronal signaling, synapses, and plasticity.

## Run

Start Ollama with `llama3.2:3b` and `nomic-embed-text` installed, then run:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py
```

To include the bundled Neo4j database, start Docker Desktop and use:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --start-neo4j
```

Use `--neo4j` if the database is already running. Database export stores the
same final graph as the portable JSON/HTML outputs, isolated by run ID. Existing
database records are not cleared. All database writes commit in one transaction.
The export uses `PipelineNode` nodes and `LINK` relationships, with readable
`label`, `kind`/`origin` properties and the complete record in `properties_json`.
The generated `graph.cypher` selects only the current run.

Edit `data/input.txt` directly, or use `--input path/to/document.txt`. Input is
UTF-8 plain text, with blank lines separating paragraphs. The default input has
three paragraphs; custom documents may have any number. No manual chunks needed.

Options:

| Option | Default | Purpose |
| --- | --- | --- |
| `--chunk-words` | 85 | Maximum words per chunk |
| `--seed-limit` | 6 | Most-mentioned concepts for background debate; 0 means all |
| `--model` | llama3.2:3b | Model used in each agent role |
| `--embedding-model` | nomic-embed-text | Final semantic similarity evaluation |
| `--no-open` | off | Save results without opening a browser |
| `--output-root` | outputs/runs | Parent directory for isolated run folders |
| `--resume RUN_DIRECTORY` | none | Reuse validated responses with matching prompts and installed model digests |

Every chunk is extracted and evaluated. The seed limit controls background
expansion only. Seeds are ranked by chunk mention count, then first occurrence,
then concept name. All execution is sequential.

## Results

Each execution creates **one self-contained folder** at `outputs/runs/<run-id>/`:

```text
index.html                 Readable results, decisions and final statistics
knowledge_graph.html       Interactive graph; works offline
report.md                  Concise statistical report
statistics.json            Machine-readable counts and descriptive statistics
events.jsonl               Complete ordered application event stream
run.log                    Terminal output and errors
manifest.json              Configuration, completion status and artifact hashes
input.txt                  Exact decoded input snapshot
graph.cypher               Query for the exported run (when Neo4j is enabled)
artifacts/
  paragraphs.json          Paragraph text, ordering and offsets
  chunks.json              Sequential chunks with source offsets and links
  environment.json         Model metadata/digests, package versions, source hashes
  extractions.json         Concepts, claims, relations, evidence and explanations
  debate.json              Proposals, reviews, rebuttals, verdicts and scores
  graph.json               Complete final graph with stable node and edge IDs
  evaluation.json          Per-chunk reconstructions and similarity measures
```

Open `index.html` to read the report. Open `knowledge_graph.html` to search and
explore the graph. Enable **Source chunks** to see the document, paragraphs,
chunks, and reading-order links. The graph uses no external browser libraries.

New run folders use local time with an explicit UTC offset, for example
`run_20260923_231000_UTC-0400_ab12cd34` for September 23 at 11:10 PM in Toronto.
Older folders used UTC: `run_20260924_025509_...` started September 23 at 10:55:09 PM
in Toronto. Historical run IDs remain stable for log and database references.
Manifests include local and UTC start/finish times; new events include both
`timestamp` (UTC) and `timestamp_local`.

The final report contains graph counts, accepted/rejected proposals, model
usage, and mean/median/sample standard deviation/min/max for semantic cosine,
token cosine and token Jaccard. These are **reconstruction similarities**, not
factual accuracy scores. Evaluation receives graph claims and relationships,
not source paragraphs or evidence quotations. Extracted claims can still closely
resemble the source, so similarity is not an independent validation of the graph.

## Pipeline

1. Save the input and split paragraphs into contiguous, ordered sentence groups.
   Long sentences split at word boundaries. No chunk crosses a paragraph;
   every source word is retained exactly once. Original character offsets are saved.
2. Extract concepts, claims and directed relations from each chunk. Keep paragraph
   context for reference resolution. Reject claims/relations with quotations that
   do not occur exactly in that chunk; record every rejection.
3. Select seed concepts and propose up to three contextual background relations
   per seed. Validate structure and direction. Review child/sibling analogies when
   both exist. The critic challenges proposals, the proposer defends or withdraws,
   and the judge adjudicates the complete exchange. Responses use exact candidate
   keys enforced by JSON schemas. `part_of`/`has_part` express components, while
   `is_a`/`has_subtype` express types; agents review explicit natural-language
   statements of each relation. Debate rationales are limited to 300 characters
   and non-extraction model responses to 700 generated tokens.
4. Rank proposals using relevance, hierarchy, prerequisite and analogy scores.
   Dimension weights use the leading eigenvector of the uncentered score moment
   matrix, with a fixed fallback for insufficient/degenerate data. Apply tier
   thresholds; judge rejection and proposer withdrawal always prevent acceptance.
5. Build the final graph with document/background provenance, source evidence,
   claim nodes, reading-order edges, and accepted background additions. Export
   to Neo4j if requested.
6. Reconstruct every chunk from the final graph, calculate similarities, and
   produce one report. There are no alternate comparison pipelines.

Agent roles use separate prompts with the same local model by default. They are
not independently trained validators. Their explanations and scores are model
judgments, and background additions are explicitly labeled as inferred.

## Logs for a future simulator

Use `events.jsonl` as the replay source, ordered by `sequence`. Events include
UTC and elapsed timestamps, stage, entity ID, parent event ID, and full data.
Logs preserve model prompts, schemas, options, raw responses, exposed reasoning,
JSON parsing, schema validation, retries, exact evidence checks, normalization,
seed selection, debate decisions, graph mutations, embeddings, metric computation,
artifact writes, and database queries/parameters/results.

Explicit rationales and any reasoning returned by Ollama are recorded. Hidden
internal model thinking cannot be accessed. This is an application trace, not an
instruction-level trace of Python, the operating system, or model inference.
Credentials are not included in configuration logs. To recover after a failure,
add `--resume outputs/runs/<failed-run-id>` to the same command and input settings.
This creates a new self-contained run, revalidates saved responses, and makes
fresh calls where prompts or schemas differ. Cache hits retain full raw output
and source-run/event attribution in the new log; usage counts distinguish reuse
from new model inference.

See [the event contract](docs/events.md) for replay and ID semantics. Events flush
after every write. Failures keep their partial artifacts, full error trace, and
a failed manifest; they do not masquerade as successful runs. Model requests
retry up to three times on response/validation/transport failures. Incomplete or
duplicate debate review IDs trigger a corrective retry; persistent errors fail
the run instead of silently accepting proposals.

## Setup and tests

Python 3.10+ is required. For a new environment:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Only if using Neo4j, copy `.env.example` to `.env` and set `NEO4J_PASSWORD` to
the database's password. Existing environment variables take precedence.
`OLLAMA_HOST` selects the Ollama server. The default is `http://127.0.0.1:11434`.

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The project consists of the entry point, the `pipeline/` package, one input,
one event-contract document and focused tests. Generated outputs are Git-ignored.
