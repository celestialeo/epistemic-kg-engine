# Epistemic Knowledge Graph Engine

One pipeline turns a prose document into a knowledge graph through extraction,
background proposals, agent debate, and a final reconstruction evaluation.
Two full introductory chapters are supplied: [neuronal communication](data/input.txt)
and [the water cycle](data/water_cycle.txt). The original short neuroscience
input is preserved as [sample.txt](data/sample.txt). A comparable shorter water-cycle
input is available as [water_cycle_sample.txt](data/water_cycle_sample.txt).

## Run

Start a current version of [Ollama for Windows](https://ollama.com/download/windows)
with `qwen3.5:9b` and `nomic-embed-text` installed, then run:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter neuroscience
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter neuroscience-simplified
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter water-cycle
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter water-cycle-simplified
# Or run full neuroscience and water-cycle sequentially, with separate outputs:
& .\.venv\Scripts\python.exe .\run_pipeline.py --chapter both
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
UTF-8 plain text, with blank lines separating paragraphs. Custom documents may
have any number of paragraphs. No manual chunks needed. `--input` and
`--chapter` are mutually exclusive. Omitting both selects neuroscience.

Options:

| Option | Default | Purpose |
| --- | --- | --- |
| `--chunk-words` | 85 | Maximum words per chunk |
| `--chapter` | neuroscience | neuroscience, neuroscience-simplified, water-cycle, water-cycle-simplified, or both (the two full chapters) |
| `--seed-threshold` | 0.7 | Minimum importance, direct relevance AND expansion usefulness |
| `--seed-limit` | 0 | Optional cap after scoring every concept; 0 means all eligible |
| `--seed-max-words` | 4 | Maximum words in a seed name; longer graph concepts/claims are retained |
| `--model` | qwen3.5:9b | Model used in every language role |
| `--registry-model` | same as --model | Optional different installed model for isolated relation/concept checks |
| `--batch-size` | 4 | Items per review/seed call; all items still checked |
| `--health-window` | 10 | Recent outcomes used to detect systematic failures |
| `--health-min-samples` | 5 | Minimum observations before the early-stop check |
| `--health-max-failure-rate` | 0.5 | Stop if a step's recent failure fraction exceeds this |
| `--think` | off | Enable extended thinking on a supported model |
| `--context-tokens` | 8192 | Context window; larger values need more memory |
| `--max-output-tokens` | 4096 | Output budget per call, including thinking when enabled |
| `--model-timeout` | 600 | Ollama request timeout in seconds |
| `--embedding-model` | nomic-embed-text | Final semantic similarity evaluation |
| `--no-open` | off | Save results without opening a browser |
| `--output-root` | outputs/runs | Parent directory for isolated run folders |
| `--resume RUN_DIRECTORY` | none | Reuse validated responses with matching prompts and installed model digests |

Every chunk is extracted and evaluated. The seed limit controls background
expansion only. Every segment is summarized. Seed candidates are normalized and
reconciled for exact identity first. Quantified phrases and names longer than
`--seed-max-words` are excluded from expansion, without deleting graph knowledge.
The selector rejects vague words, redundant aliases and sentence fragments in
chapter context. A seed needs a specific unanswered background question, a
chapter topic, and importance, relevance and expansion usefulness above the
threshold in at least one segment group. Eligible concepts are ranked by their lowest dimension, with a
name tie-breaker. Frequency is not the selection criterion. All execution is
sequential. Full chapters and semantic checks involve substantially more model
calls than the original short demonstration.

Qwen3.5 9B handles outlines, extraction, seed assessment, proposals, criticism,
rebuttals, judging, novelty checks, and reconstruction. It also handles isolated
registry checks unless `--registry-model` selects another installed model.
`nomic-embed-text` remains the embedding model.
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
graph.cypher               Query for the exported run (when Neo4j is enabled)
artifacts/
  paragraphs.json          Paragraph text, ordering and offsets
  chunks.json              Sequential chunks with source offsets and links
  environment.json         Model metadata/digests, package versions, source hashes
  chapter_outline.json     Every segment's ideas and the combined chapter overview
  concepts.json            Canonical meanings, aliases and occurrence decisions
  concept_reconciliation.json Verified global alias redirects before review and seed selection
  relations.json           Run-local vocabulary, inverse definitions and match decisions
  extraction_proposals.json Original normalized proposals before semantic review
  extraction_issues.json    Unresolved records/work units, with reasons and source context
  extraction_review.json   Single-reviewer decisions and gates for every quoted relation
  extraction_quality.json  Accepted, rejected and unresolved review counts per chunk
  health.json              Failing step and recent examples, if early-stop monitoring triggers
  health_warning.json      Latest recoverable health warning; all warnings remain in events.jsonl
  extractions.json         Reviewed relations, claims and source evidence
  seeds.json               All concept assessments, thresholds and selected seeds
  debate.json              Background decisions plus document review transcripts
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
2. Summarize every segment, then combine summaries hierarchically. Extract
   concept meanings, claims and directed relation proposals from each current
   chunk. Each relation carries full source and target objects (name, definition,
   kind). The standalone concept list is optional in content and may be empty;
   endpoints do not have to be repeated in it. There is no count cap on extracted
   concepts, claims or relations. Reject quotations that do not occur exactly
   in its source evidence context or that do not overlap the extraction unit.
3. Canonicalize concept identity using isolated model matching and verification.
   Merge true aliases/plurals, not related subtypes or parts. Resolve predicates
   against the same registry used by background proposals.
4. Review every extracted relation with a single evidence reviewer, in batches. The
   quote must entail its exact meaning, direction, endpoints and qualifications.
   An exact substring or endpoint co-occurrence alone is insufficient.
   Its evidence schema permits only `supported` or `unsupported`; `not_applicable`
   is unavailable for document facts. This does not force a positive decision.
5. Assess all concepts against the segment/topic map and select seeds by the
   threshold. Propose up to three useful unstated background facts per seed.
   Check duplicates across all seeds and accepted document/background facts,
   including inverses and symmetric forms. Compare against every chapter chunk
   and every accepted fact in bounded batches for semantic repetition and
   contradiction, including statements not extracted as edges.
6. Apply the full critic/rebuttal/judge debate to novel background proposals, in batches. General knowledge is
   permitted without a source quote, but must be sound, directly relevant and
   consistent with the chapter. The judge sees arguments but no critic scores,
   critic boolean verdicts, proposer confidence or defend/withdraw label.
   Semantic validity, direction, endpoint types, certainty, no contradiction
   and resolved objections are mandatory. Background review uses the whole
   chapter overview, exact topic list and canonical chapter concept names, without
   a seed paragraph or document-only evidence rules. It must identify a related
   chapter topic; numeric relevance is descriptive, not a cutoff. Extracted
   relations additionally require quote entailment. Scores cannot
   compensate for a failed gate; a withdrawal alone does not decide truth.
   Reasons allow up to 1,200 characters. Contradictory verdict/gate outputs are logged.
7. Build the final graph with document/background provenance, source evidence,
   claim nodes, reading-order edges, and accepted background additions. Export
   to Neo4j if requested.
8. Reconstruct every chunk from the final graph, calculate similarities, and
   produce its chapter report.

The editable starting relationship list is in [pipeline/relations.py](pipeline/relations.py).
Happenings are explicit event concepts. For example, `action potential causes
channel opening` and `channel opening acts_on calcium channel` preserve both
the action and its object when both are supported. Causal endpoints may be events
or processes. A process and its defining transformation must not become two
artificially connected events. An `acts_on` companion is optional. Event/object
identity merges are forbidden, and the graph marks event nodes with **E**.
Extracted event-object links are reviewed with the same evidence checks as
other relations; the pipeline does not invent them automatically from labels.

Before proposing background knowledge, the proposer receives every currently
accepted fact involving its seed in either direction, plus its unanswered
background question. Background proposals may reuse the relation registry or
propose a precise new predicate subject to the same meaning checks. The seed
may be either endpoint; an omitted or null source means the seed itself.
They have no `event_objects` field. If that obsolete field appears in any
model response it is dropped with a logged warning; other fields and explicit
extracted event relations retain strict validation.

New predicates have a key, a precise SOURCE-to-TARGET definition, optional inverse,
and symmetry flag. A resolver proposes exact equivalence and a separate stateless
verification call checks it. New definitions and inverse claims also require
verification. `enables` cannot be collapsed into the established `causes` key.
`has-a` is checked per occurrence: ownership, location and structural parthood
are different meanings. No ambiguous surface label becomes a global alias.
Verified new keys extend only the current run's registry and are saved in
`artifacts/relations.json`. Inspect those before manually adding a useful
domain-independent contract to the starting list.
Extraction can introduce precise predicates such as `affects_rate_of` rather
than forcing a rate influence into `enables` or `causes`. Background expansion
uses the same dynamic vocabulary.

Inverse predicates stay distinct vocabulary keys but identify the same fact
after swapping endpoints: `neuron has_part axon` equals `axon part_of neuron`.
Repeated extracted evidence is attached to the first accepted fact. Structural
document links such as paragraph containment are presentation metadata, not
model-extracted domain relations.

Agent roles use separate prompts with the same local model by default. They are
not independently trained validators. Their explanations and scores are model
judgments, and background additions are explicitly labeled as inferred.

Generation requires a nonempty definition and a schema-enforced broad `kind`
for every endpoint and standalone concept. Domain labels such as `cell_type`
or `system` go in the separate `kind_detail` field. This prevents the former
kind-mismatch repair loop while retaining the specific description. The older
targeted repair helper remains only as a defensive path for legacy/incomplete
in-memory records; normal schema-valid live output needs no metadata repair.

Identity lookup retrieves at most eight likely candidates using names, aliases,
abbreviations, and definition overlap. Retrieval only proposes comparisons:
resolver and verifier must still agree on exact identity before any merge.
Retrieval can miss a synonym, leaving distinct nodes; it never justifies a merge
on similarity alone. Context-specific validated identity results are reused.
Identical model requests also reuse validated responses in memory, with schema
and semantic validation run again on every cache hit.

Extracted relation review, seed assessment, background debate, and novelty
comparisons use batches. Background novelty still covers every source chunk
and accepted fact; accepted peers within a batch receive an additional novelty
check before admission. No validity gate or source coverage is removed.

Rejected relations are completed reviews, not processing failures. They remain
excluded from the graph regardless of rejection rate. Every review decision is
saved immediately; `extraction_quality.json` records counts separately for each
chunk. A summary sentence can legitimately yield a claim and no relation edges.

Malformed extraction/review responses, invalid quotations, and unresolved
metadata produce logged warnings and local issues instead of aborting the run.
Failed review batches split to isolate problematic candidates; an individual
candidate that still lacks a valid review is marked unresolved and excluded.
Model retries remain bounded. Valid records survive, later chunks continue,
and the final report identifies incomplete extraction/review with exit code 2.
Ordinary semantic rejections alone do not mark extraction incomplete.

Malformed model output is isolated to the affected item across outline, seed
selection, background generation/review, and reconstruction as well. Failures
are saved in `artifacts/unresolved_items.json`; valid items remain usable.
Unreachable model services and systematic item failures stop the run.
With defaults, fatal health monitoring stops after more than half of a step's
final items fail, once five item outcomes exist, using a rolling window of ten.
Retries and split batch attempts never count as additional failed items.
`health.json` saves fatal diagnostics, and `events.jsonl` retains every attempt.
These controls do not relax individual edge acceptance requirements.

Adaptive splitting changes extraction work units, not the original chapter
chunks. Quotes retain original character offsets and all resulting proposals
retain their parent chunk ID. A work unit that still cannot be extracted is
recorded as incomplete. Evidence context includes the immediately adjacent
sentences within the same paragraph. A continuous exact quote may span two
sentences and must overlap the current unit; unrelated neighboring facts are
not extraction targets. Semantic review checks the whole supporting span.

`artifacts/extraction_rejections.json`, `statistics.json`, the HTML report, and
the Markdown report show rejection categories (meaning changed, quote too
short, wrong direction, wrong kind, and other explicit causes). Categories can
overlap; unresolved reviews are reported separately from semantic rejections.

Runs with unresolved items still generate a graph and report for
their retained data. They visibly report **incomplete extraction**, use manifest
status `completed_with_issues`, and return exit code 2. Ordinary successful runs
return 0; failures return 1; interrupts return 130. The two-chapter command
continues after incomplete extraction. Chunks without grounded claims are not
reconstructed or assigned similarity scores.

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
ollama pull nomic-embed-text
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
