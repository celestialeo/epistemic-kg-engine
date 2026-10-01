# Event contract (version 1)

`events.jsonl` contains one JSON object per line. Its authoritative ordering is
`sequence`, which starts at 1 and increases by 1. IDs are local to a run; use
`(run_id, entity_id)` across runs. A simulator can seek by elapsed time or step
through the sequence without running models or connecting to Neo4j.

`timestamp` is UTC. New events also include `timestamp_local`, the same instant
with the computer's local UTC offset. Older events may omit that field. Run
folders now use local start time and an explicit UTC offset; historical IDs used
UTC and remain stable.

```json
{
  "schema_version": 1,
  "run_id": "run_...",
  "sequence": 42,
  "event_id": "event_000042",
  "timestamp": "2026-09-24T02:00:00+00:00",
  "elapsed_seconds": 5.123,
  "stage": "extraction",
  "event": "parse.completed",
  "entity_id": "chunk_001",
  "parent_id": "event_000040",
  "data": {"parsed": {"concepts": ["neuron"]}}
}
```

`parent_id` links an event to its initiating event, such as a model request or
stage start. It is nullable; graph entities are linked through IDs in `data`.
`entity_id` is the chunk, seed, candidate, graph node or graph edge concerned.
Stage order is input → preflight → outline → extraction → extraction_review →
seeds → debate → graph → evaluation → report. Every selected chapter has its
own trace and run ID.

## Event families

| Family | Recorded information |
| --- | --- |
| `run.*`, `stage.*` | Lifecycle, settings, timing, failure trace |
| `input.*` | Read bytes/hash, decoded text, paragraphs, sentence boundaries, chunks, coverage |
| `service.*` | Model availability and metadata requests/responses |
| `cache.*` | Recovery source hash, parsed model metadata, validated entries and attributed response reuse |
| `model.*` | Role, prompt, JSON schema, options, explicit thinking flag, raw response, usage, duration, retry/error |
| `parse.*`, `validation.*` | Raw JSON content, parsed object, validated model |
| `extraction.*` | Exact quotes, adaptive unit splits, endpoint repairs, unresolved records and normalized output |
| `outline.*` | Segment summaries and their source chunk IDs |
| `registry.*` | Concept identity, contextual relation matches and verified new definitions |
| `health.failed` | Failing step, recent failure fraction, examples and early-stop reason |
| `health.warning` | Recoverable extraction/review failures; recent examples, without stopping execution |
| `seed.*` | All-concept assessment count, threshold, selected contexts, optional limit and omitted counts |
| `debate.*` | Proposal, ID coverage, chapter-wide novelty, semantic gates, verdict conflicts and final decision |
| `graph.*` | Full node additions/updates, full edge additions, endpoint validation |
| `embedding.*` | Input text, model, raw vectors, dimension validation and errors |
| `evaluation.*` | Reconstruction context, individual metrics and aggregate statistics |
| `database.*` | Connections, queries/parameters/results/counters, transaction commit/rollback |
| `process.*` | Docker Compose command and captured output, when requested |
| `artifact.written` | Relative path, SHA-256, UTF-8 byte size |
| `presentation.*` | Browser opening result |

The complete Ollama response is retained, including reasoning fields when the
provider exposes them. A `reason` field is an explicit explanation, not a record
of private internal cognition. One `model.request` can have several subsequent
events; retries create new requests rather than overwriting unsuccessful output.
New `model.request` events include `data.think` (false by default). Historical
events without this field used the server default. Cache keys distinguish those
requests from explicit true/false settings and include the generation options.
Responses with `done_reason: "length"` raise `OutputLimitError` immediately;
their raw content is retained even if it happens to be syntactically valid JSON.
They are never cached as validated or retried with the same prompt.
The extractor handles this error by splitting its work unit into smaller parts.
`extraction.unit_split` records the original unit, absolute boundary, parent
chunk and boundary method. The original chunk/paragraph IDs remain unchanged.
Completed leaf units and their source ranges are saved in each extraction's
`units` array. Record counts have no schema cap.

`extraction.endpoint_repair_requested`, `extraction.endpoint_repair_completed`
and `extraction.endpoint_repair_failed` record targeted metadata repair.
The isolated model role is `concept_endpoint_repair`. The initial relation
schema embeds endpoint objects; missing metadata is allowed only at the wire
boundary in historical runs. Current generation requires full endpoint metadata,
uses the same kind enum as Concept, and keeps domain-specific labels in
`kind_detail`; normal live output does not need kind/definition repair.
`extraction.unresolved` preserves records that cannot be recovered.
`artifacts/extraction_issues.json` aggregates these records across chunks.
Malformed extraction or normalization responses are isolated to the affected
work unit or record after bounded retries. Failed review batches emit
`extraction.review_batch_failed` and split to isolate individual candidates.
A candidate without a validated review has `review_status: unresolved` and
`accepted: false`; no verdict is fabricated. It makes the owning chunk incomplete.
Ordinary semantic rejections have `review_status: completed` and are never
counted as fatal processing failures. Every decision is saved immediately to
`extraction_review.json`; reviewed extractions and per-chunk counts are also
checkpointed. `extraction.chunk_review_summary` and `extraction_quality.json`
distinguish accepted, rejected and unresolved outcomes per chunk.
`health_warning.json` holds the latest warning; every warning and its recent
examples remain in the event stream. Service failures can still stop execution.
Normalized extraction events record the merged result; original responses
remain available in the model/parse events for each extraction work unit.

## Replaying the graph

Start with empty ordered node and edge maps. For `graph.node_added` and
`graph.node_updated`, assign `nodes[entity_id] = data.node`. For
`graph.edge_added`, assign `edges[entity_id] = data.edge`. At `graph.validated`,
these maps match `artifacts/graph.json` exactly, excluding its run-level header.
Updates preserve insertion order. Every relationship endpoint exists before its
edge event. Source and target refer to graph node IDs, never display names.

Paragraph and chunk IDs are sequential. Concept IDs are deterministic hashes of
normalized labels. Claim IDs include their chunk ID; candidates include their
seed and source chunk IDs in their records. Decisions retain rejected proposals;
only accepted proposals become background graph edges. Extracted relationships
also require semantic review before graph insertion. Equivalent source
assertions are combined into one edge with additional `supporting_evidence`.
Inverse and symmetric forms are compared using the run's relation registry.
Concept IDs hash canonical names after identity resolution; aliases are retained.
Graph schema version 2 includes the final `relation_registry` in its header.
Explicit happenings now use node `kind: event` and `semantic_kind: event`;
event nodes retain deterministic concept IDs. `acts_on` connects an event to
its affected object. Causal endpoints may be events or processes; an object link
is optional and never synthesized. Historical `debate.event_link_rejected`
events remain replayable, but new runs do not apply that blanket dependency.
Replayers use the latest decision per candidate ID.

`registry.concepts_merged` records independently verified global alias merges;
`concept_reconciliation.json` records redirects. Orthographic normalization
handles case, whitespace, underscores and hyphens before identity checks.
Plural variants retrieve potential aliases but never authorize a merge alone.
`registry.alias_unresolved` records an unsuccessful reconciliation response.
`seed.filtered` records quantified/overlong names excluded from expansion;
`seeds.json` retains these exclusions and all model assessments. Eligible seeds
must identify an unanswered background question and a chapter topic.

New model roles include `segment_summarizer`, `chapter_summarizer`,
`seed_selector`, `extraction_reviewer`, `novelty_checker`, and isolated `concept_*` / `relation_*`
resolver and verifier roles. All calls are stateless. Registry roles may use
`--registry-model`; each request records the actual model. Role separation does
not make the underlying models statistically independent. No learned registry
state is shared between chapters. Background edges use
`verification_basis: model_knowledge`, not an external citation claim.

The extraction reviewer replaces the three-role debate for document facts,
using all the same evidence/semantic gates. Background facts retain all three
roles. Batched responses are keyed by item ID and validated per item. Novelty
checks still log every reference batch checked for each proposal.
Background critics/judges use a separate policy and chapter-level payload:
overview, exact topic list, and canonical chapter concepts, without source
chunks or quotes. They return `chapter_related` and `related_topic`; the latter
must name a supplied topic when the former is true. Numeric relevance is
descriptive. The proposer receives `known_seed_facts` in both directions.
Background proposals use the dynamic relation registry and may propose new
predicates. An optional source endpoint supports incoming seed relationships;
null or omitted source means the seed. The proposer schema has no `event_objects`.
`model.unused_field_dropped` warns when this obsolete field appears anywhere
in a response; the raw response and discarded value remain in the log.
Explicit extraction `acts_on` records still undergo their usual checks.

`item.completed` and `item.unresolved` record final work-item outcomes after
recovery. Only these outcomes drive health monitoring; `model.attempt_failed`
and `model.retry` do not. `artifacts/unresolved_items.json` is checkpointed
before a majority-failure stop and included in the report. Failed background
seeds and candidate decisions are also saved in `debate_progress.json`.

`extraction_rejections.json` counts semantic rejections by category, including
`meaning_changed`, `quote_too_short`, `wrong_direction`, and `wrong_kind`.
Categories can overlap. Malformed/unresolved reviews are counted separately.
Evidence may include the immediately adjacent source sentences, provided the
exact continuous quote overlaps its extraction work unit. Original character
offsets are preserved and semantic entailment still must pass.
`registry.identity_candidates` records the shortlist and full registry size;
`registry.identity_reused` records a validated context-specific identity reuse.
Memory cache hits include the source event/run just like resumed cache hits.

`start` and `end` are zero-based Unicode character offsets in the decoded
`input.txt` snapshot, with an exclusive end. Evidence offsets use the same
coordinate system. The pipeline preserves internal whitespace and checks exact
word coverage; whitespace between paragraphs/chunks is represented by offsets
rather than duplicated inside chunks. These are Python Unicode offsets, not
UTF-16 indexes: JavaScript consumers should use `Array.from(text)` when slicing
documents containing characters outside the Basic Multilingual Plane.

## Completion and failures

Trust `manifest.json.status` and the final `run.completed` event together.
Status `completed_with_issues` means the pipeline finished with incomplete
extraction and returned exit code 2; it is not a fully successful extraction.
The manifest lists `incomplete_extraction_chunks`, and the report links to the
unresolved records. `evaluation.skipped` identifies chunks without grounded
claims; these have null similarity metrics and are excluded from averages.
`run.failed` carries the full traceback and the run closes with failure status.
A stopped run can contain useful partial events and artifacts but no final graph
or report. A forced process kill may leave status `running`; no completion event
means the run is incomplete. Each event is flushed, but this is not a guarantee
against disk failure or power loss. Discard an incomplete trailing JSONL line
when inspecting a forcibly terminated process.

The manifest hashes saved artifacts, except itself and the live event/console
logs. `event_counts_before_finalization` explicitly excludes the final manifest
write and closing event. Read the stream for exact final event counts. Console
output is in `run.log`; structured model and database data is in `events.jsonl`.
