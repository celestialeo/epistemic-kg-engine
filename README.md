# Epistemic Knowledge Graph Engine

One pipeline turns a prose document into a knowledge graph through
sentence-based extraction, background debate, graph construction, and reconstruction evaluation.
Two full introductory chapters are supplied: [neuronal communication](data/input.txt)
and [the water cycle](data/water_cycle.txt). The original short neuroscience
input is preserved as [sample.txt](data/sample.txt). A comparable shorter water-cycle
input is available as [water_cycle_sample.txt](data/water_cycle_sample.txt).
For a minimal input, [AI test](data/ai_test.txt) contains three sentences and fits
into one default-sized chunk; background prerequisites are inferred by the pipeline.

## Run

Start a current version of [Ollama for Windows](https://ollama.com/download/windows)
with `qwen3.5:9b` installed, then run:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter neuroscience
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter neuroscience-simplified
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter water-cycle
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter water-cycle-simplified
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter ai-test
# Or run full neuroscience and water-cycle sequentially, with separate outputs:
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter both
```

After evaluation and reporting finish, a local **graph explorer** starts and opens
in your browser. Enter a concept, statement, or question in its text console to
highlight matching concepts and relationships. Keep the terminal open while using
the explorer; press Ctrl+C to stop it. Extraction, debate, graph construction, and
evaluation use the same logic as before. With `--chapter both`, both runs finish
before the explorer opens a page where you can choose either graph.

To run only the pipeline through reconstruction evaluation and reporting:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter neuroscience --no-explorer
```

To reopen a completed graph without running the pipeline again:

```powershell
& .\.venv\Scripts\python.exe -m pipeline.explorer "outputs/runs/neuroscience/YOUR_RUN_DIRECTORY"
```

The viewer opens the full final saved graph, including background knowledge and
disconnected concepts, fitted to the canvas. Search and **Focus on selected** let
you inspect a smaller neighborhood; **Show all** clears those filters and restores
background knowledge.

Graph provenance has two categories: **Document knowledge** and **Background
additions**. Document provenance takes precedence for shared concepts and duplicate
relationships. Concept identity is the normalized English name (case, punctuation,
and singular/plural inflection), independent of definition or context. Each graph
node contains its name and one short definition, plus its ID, origin, and generic
concept type. Different senses never create suffixed nodes. A final pass merges
same-name nodes, reroutes endpoints, and collapses duplicate relationships, retaining
document evidence. Direction, conditions, and modality remain on relationships;
different qualifications do not count as duplicate edges. This rule intentionally
shares a node across contexts; differently named synonyms remain distinct.

Choose **Start a 5-question quiz** in the local explorer to map what you know:

1. Q1 asks for open recall of the concept with the most document relationships.
2. Q2–Q3 ask about its unmapped relationships to the best-connected neighbors.
3. Q4–Q5 move from the current concept to its green neighbor with the most
   unmapped relationships. Ties use total relationship count, then name and ID.

Answers are interpreted in the question's context and checked against the graph.
Matched relationships and their endpoints turn green; partial explanations are
amber and contradictions red. A name mention alone does not earn coverage. When a
node touches several assessed relationships, green takes precedence over red,
then amber; each relationship keeps its own assessment. Unmapped means not green,
so partial and contradicted relationships remain eligible for follow-up. If no
eligible neighbor or unmapped relationship exists, the question explains its
fallback to the current concept or review. An empty graph cannot start a quiz.

Hints, reveals, and answer revisions stay within the current question. **Next
question** advances after an answer or reveal. The fifth submitted answer finishes
the session automatically; revealing Q5 also allows **Finish session**. The summary
shows cumulative relationship coverage, partial/contradicted/untouched counts,
document/background coverage, and independent versus assisted matches. Reveals
alone do not earn coverage. **Continue with 5 more questions** retains the map and
starts a new five-question round. Relationship labels and details are concealed
until mapped during the quiz; **Explore freely** restores normal browsing.

Quiz actions, answers, model calls, and coverage are logged in the corresponding
run's explorer session. The latest quiz snapshot and full answer history are saved
under `explorer_sessions/explorer_<id>/quiz/<quiz_id>.json`. Reloading the same browser
tab resumes its quiz while the same server remains running. Restarting the server
requires a new quiz; previous logs and snapshots remain on disk. Opening an older
saved run normalizes its graph in memory for the explorer without rewriting its
original graph or evaluation scores.

The explorer uses FastAPI, Uvicorn, the existing Ollama integration, and the
existing graph viewer. Run `& .\.venv\Scripts\python.exe -m pip install -r requirements.txt`
after updating an older environment. It listens only on `127.0.0.1`, selecting a
free port by default; `--explorer-port 8765` selects a fixed port in the pipeline
(`--port 8765` in the standalone command). `--no-open` prints the URL without
opening the browser; it does not disable the server.

Matching first interprets your input, then checks all saved nodes and relationships
in bounded LLM batches, including definitions, direction, conditions and
negation. Green means a matching concept or a supported relationship; amber means
related; red means a conflicting relationship. A green concept alone does not
confirm your statement. The results show explanations, origins and source quotes
where available. No match produces an explicit empty result. The server validates
every returned ID and input quote. Matching is model-based, not independent fact
verification; larger graphs can take several minutes per query. This initial
version needs no additional embedding model or vector database.

Saved graphs and evaluation scores remain unchanged. Explorer logs are saved inside
the graph's source run at `RUN_DIRECTORY/explorer_sessions/explorer_<id>/events.jsonl`.
Each server session records page visits, node/edge and result selections, search and
query text edits (including unsubmitted text), filters, focus/reset/fit, node drags,
panning, zooming, scrolling, and page visibility/navigation. Drag/pan events record
the completed gesture; other controls record their changes. Submitted queries,
model requests/responses, results, and failures share the same session log. Browser
events include a page ID, client timestamp and sequence; server events include
receipt timestamps. Logs are flushed to disk as they arrive, including while a
model query is running. The page reports saving failures and retries while open.
Closing a page uses best-effort delivery; abrupt browser/server termination can
lose events not yet delivered. Offline HTML cannot save interaction logs to disk;
use the local explorer for logging. Runs marked `completed_with_issues` can also
be explored; the page displays their status and any available reconstruction score.
The saved `knowledge_graph.html` still works offline; the LLM console is available
on the local server page. The standalone command inherits the saved model settings;
use `--model NAME` or `--context-tokens 16384` to override them for exploration only.

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
UTF-8 plain text, with blank lines separating paragraphs. Custom documents may
have any number of paragraphs. No manual chunks needed. `--input` and
`--chapter` are mutually exclusive. Omitting both selects neuroscience.

Options:

| Option | Default | Purpose |
| --- | --- | --- |
| `--chunk-words` | 85 | Maximum words per chunk |
| `--chapter` | neuroscience | neuroscience, neuroscience-simplified, water-cycle, water-cycle-simplified, ai-test, or both (the two full chapters) |
| `--seed-limit` | 0 | Optional cap on concepts sent to debate; 0 means all extracted concepts |
| `--model` | qwen3.5:9b | Model used in every language role |
| `--registry-model` | same as --model | Optional different installed model for relation checks and endpoint repair |
| `--batch-size` | 4 | Items per review/seed call; all items still checked |
| `--health-window` | 10 | Recent outcomes used to detect systematic failures |
| `--health-min-samples` | 5 | Minimum observations before the early-stop check |
| `--health-max-failure-rate` | 0.5 | Stop if a step's recent failure fraction exceeds this |
| `--think` | off | Enable extended thinking on a supported model |
| `--context-tokens` | 8192 | Context window; larger values need more memory |
| `--max-output-tokens` | 4096 | Output budget per call, including thinking when enabled |
| `--document-context-tokens` | 16384 | Minimum context window for the final full-document claim alignment |
| `--document-output-tokens` | 8192 | Minimum output budget for the final full-document claim alignment |
| `--model-timeout` | 600 | Ollama request timeout in seconds |
| `--no-open` | off | Save results without opening a browser |
| `--no-explorer` | off | Stop after evaluation/reporting; do not start the local graph console |
| `--explorer-port` | 0 | Explorer port; 0 selects a free local port |
| `--output-root` | outputs/runs | Parent directory for isolated run folders |
| `--resume RUN_DIRECTORY` | none | Reuse validated responses with matching prompts and installed model digests |

Extraction sends only the current sentence and its previous sentence, adding the
next sentence when it supplies an adjacent name. Only the current sentence is
extracted; neighboring sentences help interpret it. References can resolve to a
concept named in the current sentence before it is registered. Self-relations
created by reference resolution are dropped.

Failed evidence quotes receive one targeted sentence retry with the exact
failure reason. Records that already passed are retained, and repaired records
undergo the same exact-quote and sentence-overlap checks. Remaining failures are
excluded and logged while extraction continues. Health monitoring counts final
record outcomes after repair, rather than incomplete chunks; a sentence response
with no usable output counts as one unresolved item. Service failures remain
fatal, and the default health threshold stops a stage when most recent records
fail (after the minimum sample count).

Every distinct extracted concept is sent to
background debate by default, including concepts found at either endpoint.
Descriptive phrases remain graph endpoints and are excluded from debate seeds.
The optional seed limit caps background work in source discovery order.
Legacy `--seed-threshold` and `--seed-max-words` arguments are accepted for old
commands but no longer filter concepts.

Qwen3.5 9B handles extraction, chapter scope, background proposals, criticism,
rebuttals, judging and novelty checks. Registry checks use the same model unless
`--registry-model` selects another installed model. Every regular run also
reconstructs text from the completed graph and evaluates it against the source.
No extra flag is needed. Seed selection uses the configured embedding model;
reconstruction fidelity uses claim matching and text metrics.

The final document alignment uses at least a 16K context and an 8K output budget
so both complete claim lists and the answer can fit. Other calls retain their
usual budgets. The document budgets can be increased with the two options above;
larger contexts may move part of the model onto CPU memory on an 8 GiB GPU.

The default explicitly disables extended thinking and uses temperature 0 for
schema-constrained JSON; agents still return concise explanations in `reason`
fields. This is a desktop runtime configuration, not the model's benchmark setup.
Use `--think` to experiment with extended reasoning. The output budget includes
thinking tokens, so that mode may need a larger budget and context window.
Responses stopped by the output limit are rejected and logged immediately.
Extraction splits the affected work unit at a sentence boundary and retries
smaller units; a single long sentence falls back to word boundaries. Keyed review
and novelty batches split into smaller batches. A single review item and other
roles report the output-limit error rather than repeating the identical request.
Resume keys include thinking mode and generation options.

On an 8 GiB RTX 3070, the model may partially offload to system RAM. Close
memory-heavy applications and use `ollama ps` during a run to inspect actual
GPU/CPU allocation. The configured 8K context limits memory use; it does not
request the model's full advertised context. Runtime and graph quality should
be measured on your input before a live demonstration.

## Results

Each chapter creates **one self-contained folder** at
`outputs/runs/<chapter>/<run-id>/` (`custom` for `--input`).
Using `--chapter both` creates two independent runs. Each gets fresh model
request state, cache, concept/relationship registries, seeds, fact index, graph,
logs and report. Discovered aliases/keys are never written into the other
chapter or back into the shared starting vocabulary. Neo4j data is isolated by
run ID. A failed chapter is logged and the other is still attempted; a keyboard
interrupt stops the batch.

`--chapter neuroscience-simplified` runs the original 509-word `data/sample.txt`
through the full pipeline with the same quality checks. Its results go to
`outputs/runs/neuroscience-simplified/<run-id>/`.

`--chapter water-cycle-simplified` runs the shorter `data/water_cycle_sample.txt`
through the same full pipeline, saving to
`outputs/runs/water-cycle-simplified/<run-id>/`.

```text
index.html                 Readable results, decisions and final statistics
knowledge_graph.html       Interactive graph; works offline
report.md                  Concise statistical report
statistics.json            Machine-readable counts and descriptive statistics
events.jsonl               Complete ordered application event stream
run.log                    Terminal output and errors
manifest.json              Configuration, completion status and artifact hashes
input.txt                  Exact decoded input snapshot
reconstruction.txt         Complete rebuilt text, in source chunk order
graph.cypher               Query for the exported run (when Neo4j is enabled)
artifacts/
  paragraphs.json          Paragraph text, ordering and offsets
  chunks.json              Sequential chunks with source offsets and links
  environment.json         Model metadata/digests, package versions, source hashes
  chapter_outline.json     Every segment's ideas and the combined chapter overview
  concepts.json            Normalized names, short definitions and occurrence records
  concept_reconciliation.json Name-normalization redirects before review and seed selection
  relations.json           Run-local vocabulary, inverse definitions and match decisions
  extraction_proposals.json Original normalized proposals before semantic review
  extraction_issues.json    Unresolved records/work units, with reasons and source context
  extraction_review.json   Single-reviewer decisions and gates for every quoted relation
  extraction_quality.json  Accepted, rejected and unresolved review counts per chunk
  health.json              Failing step and recent examples, if early-stop monitoring triggers
  health_warning.json      Latest recoverable health warning; all warnings remain in events.jsonl
  extractions.json         Reviewed relations, claims and source evidence
  seeds.json               Concepts for debate and excluded descriptive phrases
  debate.json              Background decisions plus document review transcripts
  graph.json               Complete final graph with stable node and edge IDs
  evaluation_progress.json Per-chunk reconstruction and scoring checkpoints
  evaluation.json          Chunk metrics, full-document alignment and final 0–100 score
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

The report contains extracted relations with their source quotes, background
decisions, graph counts, rebuilt text, reconstruction scores and model usage. Conditions and modality appear in
relation details. These judgments are not independent factual verification.

## Pipeline

The processing stages are **Extraction → Debate → Graph → Evaluation**. Input
loading and model preflight are setup. The evaluation stage includes text
reconstruction, scoring and final report generation.

1. **Extraction.** Process the sentences in source order and construct
   `concept → relation → target` assertions. Keep exact source quotes and
   character offsets. Targets may be standalone concepts or complete descriptive
   phrases, marked by `form: concept` or `form: phrase`. Each endpoint also has
   a definition and semantic kind. Retain conditions and modality/negation in
   the relation fields. Claims remain available as source annotations, but
   relations are the primary graph view.
2. **Debate.** Build the chapter context, reconcile normalized names, and review
   document relations for quote entailment. Then send every distinct extracted
   concept to the existing background proposer/critic/rebuttal/judge flow.
   There is no model-based seed ranking or word-count cutoff in this path.
   Descriptive phrases are excluded; standalone topics named inside them may
   be extracted separately and debated. Background proposals may introduce
   concepts as before and undergo chapter-wide novelty checks. Accepted
   background knowledge stays distinguishable from document assertions.
3. **Graph.** Build the graph from reviewed document relations and accepted
   background relations. Save the graph and interactive viewer, plus Neo4j when
   requested.
4. **Reconstruction and evaluation.** Reconstruct each chunk from graph claims,
   concepts and relations. Compare the rebuilt and original texts through
   independently extracted claims and one-to-one semantic alignment. The final
   score compares the complete documents and weights claim fidelity (55%), idea
   order (25%), ROUGE-L F1 (10%) and length similarity (10%). It is not the mean
   of chunk scores. The report links to `reconstruction.txt` and
   `artifacts/evaluation.json`. An unresolved evaluation produces a null overall
   score and `completed_with_issues` (exit code 2); available results are retained.

For example:

```text
Water cycle → describes → Water movement between the atmosphere,
                         land, and bodies of water
```

The target stays whole: splitting it into "movement between atmosphere" and
similar fragments would lose the connection among the places. Conversely, a
shared predicate that applies independently to every listed subject may split:

```text
Oceans      → stores → Water in reservoirs
Lakes       → stores → Water in reservoirs
Rivers      → stores → Water in reservoirs
Soil        → stores → Water in reservoirs
Groundwater → stores → Water in reservoirs
Snow        → stores → Water in reservoirs
Ice         → stores → Water in reservoirs
```

Collective actions, comparisons and "between" constructions must not be
distributed this way. These are extraction instructions, not hardcoded facts:
the source sentence and semantic review still determine which edges survive.

The starting vocabulary includes general `describes` and `stores` relations.
Other predicates may still be proposed and checked against their definitions.
Concept identity uses normalized names, including singular/plural forms.
Differently named concepts remain separate; context never splits the same name.
Qualified facts are not collapsed into unqualified triples.

Inspect `artifacts/extraction_proposals.json` for proposals,
`artifacts/extraction_review.json` for decisions, and
`artifacts/extractions.json` for retained relations. The report shows rejections
and unresolved records. Partial runs keep valid results and return exit code 2;
successful runs return 0, failures 1, and interruptions 130.

All roles use the same local model unless configured otherwise. Debate
judgments are not independent external verification. Extraction can still miss
or misinterpret an assertion, so compare the retained triples with their quotes.

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
add `--resume outputs/runs/<chapter>/<failed-run-id>` to the same single-chapter
command and input settings. The chapter and input must match; resume with
`--chapter both` is rejected. Older runs predating chapter identity cannot be
resumed by this version.
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
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3.5:9b
```

Only if using Neo4j, copy `.env.example` to `.env` and set `NEO4J_PASSWORD` to
the database's password. Existing environment variables take precedence.
`OLLAMA_HOST` selects the Ollama server. The default is `http://127.0.0.1:11434`.

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests include the 34 real extraction responses saved from the failed neuroscience
run in `tests/fixtures/previous_extractions.json`. Explicit replay migration
preserves an old specific kind in `kind_detail` and marks its unknown broad class
as `other`; it does not guess a classification or run during live generation.
Tests use model fixtures and mocks; they make no live Ollama requests. Generated
outputs are Git-ignored. Offline tests verify application behavior, not the
model's factual accuracy on a chapter.
