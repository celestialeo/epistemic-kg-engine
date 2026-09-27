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
Stage order is input → preflight → extraction → debate → graph → evaluation → report.

## Event families

| Family | Recorded information |
| --- | --- |
| `run.*`, `stage.*` | Lifecycle, settings, timing, failure trace |
| `input.*` | Read bytes/hash, decoded text, paragraphs, sentence boundaries, chunks, coverage |
| `service.*` | Model availability and metadata requests/responses |
| `cache.*` | Recovery source hash, parsed model metadata, validated entries and attributed response reuse |
| `model.*` | Role, prompt, JSON schema, options, raw response, usage, duration, retry/error |
| `parse.*`, `validation.*` | Raw JSON content, parsed object, validated model |
| `extraction.*` | Exact-quotation checks, discarded records, normalization before/after |
| `seed.*` | Ranking, selected contexts, selection limit and omitted counts |
| `debate.*` | Proposal, rule gate, analogy skip/check via model role, ID coverage, verdicts, weights, final decision |
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
only accepted proposals become background graph edges. Separate edge records
preserve multiple source assertions of the same relation.

`start` and `end` are zero-based Unicode character offsets in the decoded
`input.txt` snapshot, with an exclusive end. Evidence offsets use the same
coordinate system. The pipeline preserves internal whitespace and checks exact
word coverage; whitespace between paragraphs/chunks is represented by offsets
rather than duplicated inside chunks. These are Python Unicode offsets, not
UTF-16 indexes: JavaScript consumers should use `Array.from(text)` when slicing
documents containing characters outside the Basic Multilingual Plane.

## Completion and failures

Trust `manifest.json.status` and the final `run.completed` event together.
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
