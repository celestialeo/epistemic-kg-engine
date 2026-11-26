# ECSE 679 — Epistemic Knowledge Graph Engine

The active inputs are `data/ai_test.txt`, `data/llm_tuning.txt`, and
`data/neurons_and_glia.txt`. The [saved-run catalog](outputs/runs/README.md) lists
one retained November 25 graph per input. LLM tuning combines its original
execution and checkpoint recovery, retaining the interruption and unresolved issues.
All older inputs, runs, database snapshots, and generated diagnostics are in the
single root [archive](archive/README.md).

For a screenshot walkthrough of the interactive interface, open the
[simple user guide (PDF)](docs/Interactive_Graph_Guide.pdf) or the
[browser guide with expandable screenshots](docs/Interactive_Graph_Guide.html).
The guide uses clearly labelled demonstration data.

The professor workspace has three left-navigation tabs: **Quiz**, **Run Insights**,
and **Class Overview**. A shared topic/version selector supports **All Topics** with
conservative overlap counting and per-topic breakdowns. Student details and grading
corrections stay inside Class Overview. Independently earned green stays across quizzes;
yellow can be practised without help to become green. Normal quizzes exclude green
facts, and failed question drafts can recover through another eligible fact. Hint/reveal
validation permits ordinary vocabulary; unsafe hints are withheld, while failed
reveals can use a display-checked, saved expected answer with assistance marking. See [workflow and metric definitions](docs/professor.md).

**Run Insights → Edit this knowledge graph** supports adding, editing, and deleting
concepts and relationships, with run-local persistence, an untouched original view,
and reversible audit history. Quizzes and learning metrics use the edited graph.
Historical grades are preserved; evidence for changed relationship meanings is
flagged and excluded from current mastery. New pipeline runs stay independent.
See [manual graph editing](docs/professor.md#manual-graph-editing) for details.

Questions carry a shared, reviewed assessment specification. New quizzes use scoped,
question-aware semantic grading: clear paraphrases, pronouns and short contextual
answers count without requiring the graph's exact wording. Criterion checks and
verbatim learner evidence govern green/yellow/red states; unrelated answers do not
earn credit. Older questions retain their whole-graph matching/retry workflow. Correct
component answers do not establish full-relationship mastery. Background facts
require professor approval under Run Insights before quiz use. See the workflow
documentation for evidence requirements, corrections and unresolved retries.

Full generation and background replay build the graph directly from the existing
source-extraction reviews and background debate decisions. The added post-graph
review and repair process is no longer part of either pipeline. Runs record
`graph_acceptance_policy=document_review_and_background_debate` and
`graph_quality_status=not_run`; they do not claim that the extra review passed.
Reconstruction evaluation remains a measurement stage, and background quiz approval
remains a separate professor control. Custom texts use the same logic via `--input`.

Background explanations are planned as factual sentences and constructed together
with explicit planned endpoint pairs and a shared concept table. Each assertion must
begin with its named source and explicitly name its target. Invalid members are rejected
individually; they and missing bridges remain available as feedback for whole-group repair.
They cannot supply paths for admission. Semantic review still checks roles and meaning.
Construction receives fixed node identities and endpoint pairs, and
generates only their semantic details. Every link references explicit nodes;
intermediate concepts cannot supply a connection merely through their definitions. Canonical
concept resolution is shared within each explanation, while external aliases still
require semantic verification. Predicate reuse, including an identical stored
label and definition, checks the qualified occurrence before accepting its meaning.

Explanation repair can rebuild the entire explanation and add necessary bridge
relationships. It retains all member decisions, original gaps, anchored evidence,
qualifications and known connections. Each proposed replacement or bridge passes
the existing representation, novelty, debate and counterexample checks. Connectivity
is checked again using only admitted links, so a rejected bridge cannot leave an
accepted but disconnected explanation. Previously accepted members can be superseded
only by a complete validated replacement; a failed replacement retains the prior accepted group. Original
decisions remain in the audit. Duplicate proposals stay rejected; existing verified
relationships can supply their graph connections without publishing another copy.
When there are no accepted originals to supersede, a repair may retain its validated,
connected subset even if an optional extension fails. Rejected bridges still cannot
support admission of disconnected links.
The configurable `review.explanation_repair_max_attempts` defaults to three total
attempts. A further attempt requires improved validation stages for the original
questions or more distinct, fully validated connected links, without regressing
question-level progress. Repeated failure patterns stop early. Later failed attempts
retain the best validated repair, subject to the same complete-replacement rules.
Proposed counterexamples receive an independent check of their premises and whether
they refute the exact qualified link. An invalid objection triggers a bounded review
retry; it does not establish the truth of the original assertion.
The final factual check sees the literal qualified link without the intended sentence
or predicate definition, so those descriptions cannot silently repair a wrong assertion.

Repair requests retain essential evidence and topology at every budget reduction;
supplemental context may be removed and repeated prose referenced losslessly. If
the minimum request cannot fit, repair remains unresolved under the unchanged
health policy. Per-attempt estimates are saved in `artifacts/repair_budgets/`.
Whole-explanation repairs use the configured general output allowance, while legacy
single-link repairs retain their smaller dedicated allowance. Group repairs can
need more context than single-link repairs; use
`--context-tokens` to provide sufficient capacity rather than dropping evidence.

The existing graph-refinement command is an explicitly invoked diagnostic tool.
The review and repair behavior described below applies only when that command (or
notebook `MODE="refine"`) is requested. It is not a prerequisite for normal runs.
In that optional workflow, each concept and relationship receives an edit and
verification, followed by a
consistency review over bounded groups of relationships and their neighbors.
Source coverage is checked chunk by chunk. Predicate labels preferably use one to three
words; the configurable safety limits allow six words and 80 characters when needed
to preserve meaning. Included facts must pass review; unresolved source claims stop publication.
Document assertions receive a context-preserving edit even when their labels are
already short. Concise background assertions are verified before rewriting. Missing assertions are
recovered from source passages, rather than inventing links for isolated nouns.
Each proposed edge is first read without its source quotation or predicate contract;
verification then compares that displayed meaning with the evidence and contract.
This helps expose labels or missing qualifiers that a reviewer might otherwise
silently repair by reading the source.
A rejected assertion must change in graph content before it can count as a repair;
changing only its explanation or quotation is insufficient.
Rejected background enrichment is excluded and recorded. The audit is saved as
`artifacts/graph_quality.json`. This checks source fidelity and model judgments,
not independent factual truth. Existing graphs can be refined into a new version
without changing historical student records:

```powershell
python -m pipeline.graph_quality outputs/runs/ai-test/<saved-run-id>
```

Use `--resume-review <interrupted-review-directory>` to reuse exact validated model
responses. The new completed version is discovered by the professor workspace.
Legacy versions remain available for inspection and their original assessment history.
Resume also preserves recorded output-limit failures for identical requests. They
remain failures; changing the prompt, model digest or budget requires a fresh call.

Inference and grading prompts do not embed facts from the bundled topics. Custom
topics use the same pipeline through `--input`; adding a text does not require
adding a chapter alias or changing prompts. Semantic repairs infer participants
from the supplied assertion rather than matching a list of sentence patterns.
The graph review's `ReviewPolicy` exposes batch sizes, repair attempts, and
candidate-retrieval limits. Retrieval similarity proposes candidates only; it
never establishes equivalence. These resource and schema constraints are general
processing rules, not topic knowledge. The paged reviews are checks, not an
exhaustive proof of global consistency or external factual truth.
Review calls default to direct structured output (`review.reasoning=false`) to avoid
spending the output budget on hidden reasoning before producing a decision. Enable
reasoning in configuration when the selected model and budget support it. Its output
ceiling follows the configured model output budget and available input headroom.
When enabled, `review.reasoning_fallback` permits a direct retry after reasoning
exhaustion, using the same verification criteria. Failed checks never become approval.
Source rejection blocks publication; rejected or failed background checks withhold
the addition. Debate acceptance alone is never sufficient for publication.
Coverage checks one sentence per request, retaining its paragraph as context,
and maps its assertions to actual edge IDs without treating an
edge's quotation as graph content. Background assertions also face a separate
counterexample and qualification check.
Node review retrieves other source mentions as well as incident quotations, so a
shared concept is not defined only by one use. Recovered assertions are verified
one at a time, followed by a check that the revision closes a reported gap without
losing existing source claims.

Reviewed graph schema 4 records additional participants as node references with a
semantic role and scope, plus separate `purpose` and `timing` fields. Ownership,
pronouns and shared actors are resolved from source context; unresolved ambiguity
must remain qualified. Participants are added only when needed for an assertion,
not to meet a node quota. The graph view shows these roles and qualifications in
selectable relationship cards; dotted connectors denote roles, not extra assertions.
Predicate definitions cannot supply a missing participant or reverse an arrow.
Local verification checks one focused assertion; the separate mandatory coverage
gate checks every source sentence, including other assertions sharing its quotation.
Before relationship editing, source-role analysis focuses on one existing entity
at a time. Two independent readings select its source-attributed owner or actor
from runtime canonical names, which code maps to existing node IDs. Disagreement
requires a separate source-based adjudication within the configured repair budget.
The exact supplied source is retained as provenance. Agreement is model evidence,
not a guarantee of correctness; the subsequent fact and source-coverage gates still
check the actual graph. Ambiguous references cannot acquire invented participants.
Bindings identify the referent and its property/action by existing node IDs. A
programmatic check requires the bound owner or actor on the corresponding assertion
with the correct participant scope; a positive model verdict cannot override a
missing identity link. Properties/actions cannot be bound to their actor's own ID.
This analysis guides editing but is not graph content and is never supplied to the
reconstructor. Goal and temporal scope are checked on the actual graph assertions,
both individually and by source coverage. Background objections are also checked independently for applicability
to the actual qualified claim. Dismissing an invalid objection never replaces the
subsequent factual and literal-direction verification.
Background falsification receives named identities and their definitions to preserve
the intended meaning. A contextual description does not redefine every member of
a named class.
Counterexamples must be instances of that subject and satisfy the stated scope.

Reconstruction uses source occurrence order and only structured document facts,
including participant roles, goals and timing; it never receives evidence quotations.
Evaluation version `reconstruction_fidelity_v2_context` independently reviews each
candidate claim match for participant identity, ownership, purpose versus outcome,
temporal scope, direction, and qualifications. A failed dimension removes that match
before scoring. Scores from the previous metric version are not directly comparable.
`python tools/render_saved_graph.py RUN` refreshes a completed run's portable view
without inference or changing graph facts; it records the renderer revision and new
HTML hash in the manifest.

If relation generation proposes an existing relationship name, the registry checks
the stored definition against the current assertion, keeping its endpoints and
qualifiers. Reuse requires verified meaning, direction, and compatible endpoint
types; it never overwrites the stored definition, symmetry, or inverse. A rejected
check is retained for that occurrence, and a later occurrence is checked separately.
The verifier compares complete assertions in source context; differences in
definition wording or generality alone are insufficient to reject equivalence.
A rejection must identify a concrete claim added, lost, or changed.

Concept names retain their spelling and number; automatic singularization is not
used to decide identity. Singular/plural variants and synonyms can merge only
after contextual checks. Identity and predicate matching start with 16 retrieved
candidates, or the configured `--identity-candidates` initial window. Uncertain
searches and rejected independent matches expand the window, visiting only unseen
candidates in budgeted pages. A verified match or conclusive distinction stops the
search; expanding retrieval never authorizes a merge without verification.

Reference resolution starts with three preceding sentences. If the referent remains
ambiguous, it adds relevant earlier sentences, including earlier paragraphs, only
when the complete request still fits the existing context and output budget. Source
offsets and added antecedent evidence are retained for downstream review; the
current assertion and its original quotation stay unchanged. Ambiguity remains
unresolved when no additional context fits or the source still does not identify a referent.

Runtime policy is centralized in [`pipeline_settings.json`](pipeline_settings.json),
with the same defaults embedded in the portable notebook. Set `EKG_SETTINGS` to a
partial JSON override file before starting a process; unknown keys and invalid
budgets fail early. Existing CLI options override their corresponding settings.

- `workload`: null defaults derive chunk/page sizes from input density and model
  budgets. Identity retrieval starts with 16 candidates; source facts, seeds and
  background proposals have no default content quota. Explicit limits remain
  available as deliberate operating choices.
- `model`, `review`, `health`, `operations`: token, time, retry and service budgets.
  These are explicit configured resource policies, not automatic hardware detection.
- `evaluation_weights`, `assessment_weights`: normalized evaluation weights and
  rubric credit. Saved answer weights preserve historical grading.
- `metrics`: class-level shared-knowledge threshold.
- `ui`, `text`, `labels`: display, transport and field limits. Quiz round size
  derives from eligible facts unless overridden; thumbnails default to all items.

Paged processing visits all input items. An indivisible request that cannot fit the
configured context fails explicitly; it is neither truncated nor treated as verified.
Necessary mathematical constants, schema/protocol values and historical format
compatibility values remain explicit. Configuration is recorded in run artifacts.

Only the original AI test is being validated for this change. The larger fixtures
below are available for separate testing; they are not evidence of current live-model
accuracy across topics.

Two three-paragraph validation inputs are under `archive/inputs/validation`. When testing
these separately, use the same configured resource policy:

```powershell
python run_pipeline.py --input archive/inputs/validation/ai_three_paragraphs.txt --output-root outputs/runs/generalization-validation --no-open --no-explorer
python run_pipeline.py --input archive/inputs/validation/neuron_three_paragraphs.txt --output-root outputs/runs/generalization-validation --no-open --no-explorer
python -m unittest tests.test_topic_independence tests.test_graph_quality -q
```

Optional CLI content limits apply only when explicitly requested. The neuron fixture was checked against OpenStax's
[neuron anatomy](https://openstax.org/books/biology-2e/pages/35-1-neurons-and-glial-cells)
and [neural communication](https://openstax.org/books/biology-2e/pages/35-2-how-neurons-communicate)
chapters. Fixtures are evaluation data and are never inserted into inference
prompts as examples for another input. The topic-independence tests include a
third-topic endpoint repair, prompt checks, and bounded source-review coverage;
these deterministic tests do not measure live-model accuracy.

[261273237.ipynb](261273237.ipynb) is the submission and the single source of the
implementation for student **261273237**. It contains
problem/background discussion, setup and embedded data, methodology and implementation,
execution controls, evaluation/results, limitations, conclusions and references.

The notebook runs independently of project `.py` files. Its visible
`%%pipeline_module` cells register Python modules in memory; `%%project_asset` cells
supply browser assets and bundled inputs. No source files are generated. Edit the
implementation in the notebook, restart the kernel and run all cells. The only Python
files retained under `pipeline/` and at the root are terminal adapters. Tests and
validation utilities remain separate development tools. No source backups were created.

## Notebook setup

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-notebook.txt
& .\.venv\Scripts\python.exe -m notebook 261273237.ipynb
```

Use Python 3.11+ for the pinned notebook toolchain; validation uses Python 3.12.
The terminal runtime still supports Python 3.10+ with `requirements.txt` alone.
The notebook also contains its direct
runtime dependency list and an opt-in installation cell for use when copied alone.
Choose the virtual environment's kernel. Restart and Run All with the default controls
for a deterministic offline demonstration. Those displayed checks use synthetic inputs
and are explicitly not extraction-quality measurements.

For actual inference, install/start Ollama separately and download the selected models:

```powershell
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
```

No cloud API key is used by the current local backend. Configure `OLLAMA_HOST` through
the environment or a private `.env` (default `http://127.0.0.1:11434`). Optional Neo4j
export uses `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` and `NEO4J_DB`; see `.env.example`.
The notebook offers a non-echoing password prompt. Never put secrets in cells, output,
URLs or command arguments. A provider API key does not enable an unimplemented cloud
backend. Existing environment variables take precedence over `.env`.

## Execution options

In the notebook, edit the execution-controls cell and run it after all implementation
cells. `SAVED_RUN` must identify the exact run directory, not its parent.

| Mode | Behavior |
| --- | --- |
| `offline` | Synthetic ingestion, graph rendering and metric checks; no model calls |
| `ingest` | Split embedded AI-test text into paragraphs/chunks; `execute(..., input_path=...)` accepts a custom file |
| `full` | Run all pipeline stages with `PIPELINE_ARGS`; server startup is deferred to the graph controls |
| `background` | Replay background expansion from `SAVED_RUN`; `STAGE_ARGS` accepts `--reuse-seeds` and `--output-root` |
| `refine` | Review and repair `SAVED_RUN` into a new graph version, preserving the source run and student history |
| `evaluate` | Evaluate the saved graph and update that run's report; `STAGE_ARGS` accepts evaluation options |
| `render` | Display saved `artifacts/graph.json` in an isolated static viewer; no inference |
| `graph` | Start an interactive console for exactly `SAVED_RUN`; never reruns extraction |
| `interact` | Open the latest eligible run in the combined graph/quiz/professor view; `execute(..., saved_run=...)` selects an exact run |
| `professor` | Launch the professor/student dashboard for `RUNS_ROOT` |

Notebook servers bind to loopback and run in a managed thread. Follow the printed URL;
call `stop_server()` or set `STOP_SERVER=True` in the cleanup cell to stop one. The
server ends when the kernel exits. LLM graph matching and quiz grading can still require
Ollama even though opening a saved graph does not.

`load_saved(path)` reads available intermediate artifacts without inference, reports
missing files, and checks available manifest hashes. The results cell displays saved
scores and provenance only when a run is selected. A missing score remains `None`.

## Preserved terminal commands

Run from the repository root. These commands import their implementation directly from
the notebook, without executing notebook experiments. Renaming the notebook to your ID
works if it remains the sole `.ipynb` in the root, beside `run_pipeline.py`.

```powershell
# Full pipeline, then exit without starting a server
python run_pipeline.py --chapter ai-test --no-open --no-explorer
python run_pipeline.py --input path/to/chapter.txt --no-open --no-explorer
python run_pipeline.py --input "data/llm_tuning.txt" --context-tokens 24576 --no-open --no-explorer

# Completely fresh inference, including repeated requests within the run
python run_pipeline.py --input "data/neurons_and_glia.txt" --output-root outputs/runs/neurons-and-glia --context-tokens 24576 --no-model-cache --no-open --no-explorer

# Exact-response cache reuse: same chapter and unchanged input; new complete run
python run_pipeline.py --chapter ai-test --resume RUN_DIRECTORY --no-open --no-explorer

# Open one exact saved run, including an older run, without extraction
python -m pipeline.explorer RUN_DIRECTORY --no-open
# Multiple saved graphs are also accepted
python -m pipeline.explorer RUN_DIRECTORY OTHER_RUN_DIRECTORY --port 8765 --no-open

# Latest eligible graph with student/professor controls; optional chapter/input filter
python run_pipeline.py --interact --chapter ai-test --no-open
python run_pipeline.py --interact --input path/to/chapter.txt --output-root outputs/runs --no-open
python -m pipeline.professor --runs-root outputs/runs --database outputs/professor/students.sqlite3 --no-open

# Independently supported model stages
python -m pipeline.replay_background RUN_DIRECTORY --reuse-seeds
python -m pipeline.evaluate_saved_run RUN_DIRECTORY
python -m pipeline.evaluate_saved_run RUN_DIRECTORY --resume-evaluation EVALUATION_TRACE_DIRECTORY

# Profile saved traces without model calls (the report destination must be new)
python tools/profile_run.py RUN_DIRECTORY --output outputs/diagnostics/run-profile.json
# Compare multiple traces; compare equivalent completed work before judging speed
python tools/profile_run.py RUN_DIRECTORY OTHER_RUN_DIRECTORY --top 12

# Optional database export (Docker required only for --start-neo4j)
python run_pipeline.py --chapter ai-test --start-neo4j --no-open --no-explorer
```

Each command retains `--help`. Full-run flags include:

- Inputs: `--input`, `--chapter` (neuroscience, neuroscience-simplified, water-cycle,
  water-cycle-simplified, ai-test, both), `--output-root`, `--chunk-words`.
- Models: `--model`, `--registry-model`, `--embedding-model`, `--think`, `--batch-size`,
  `--model-timeout`, `--context-tokens`, `--max-output-tokens`,
  `--document-context-tokens`, `--document-output-tokens`.
- Expansion/recovery: `--seed-limit`, `--background-proposal-limit`, `--resume`,
  `--health-window`, `--health-min-samples`, `--health-max-failure-rate`.
- Presentation/export: `--neo4j`, `--start-neo4j`, `--no-open`, `--no-explorer`,
  `--explorer-port`, `--interact`.

Document token budgets default to the configured regular context/output budgets.
Legacy hidden seed flags and `--new` remain accepted as before. There is no general
`--stage` or extraction-only CLI. `--resume` restores completed extraction, source-review,
seed-selection and background-item checkpoints when input, code, settings and model
identities match. Otherwise it revalidates matching cached responses and makes new
model calls on misses. Checkpoints and validated response files are published atomically;
an incomplete final event after a crash is ignored, but malformed complete events fail.
Graph-view HTML changes are rendered after checkpoint restoration and do not discard
saved inference; logic, prompts, settings, input and model changes still invalidate it.
For the pinned counterexample-validator update, `tools/resume_debate_checkpoint.py
RUN_DIRECTORY --output-root RECOVERY_ROOT` restores a complete debate checkpoint
without invoking earlier stages or completed seeds. It verifies the original artifact
hash and signature, unchanged input/settings/models, and the exact two code transitions
in `tools/counterexample_checkpoint_migration.json`; all other changes fail closed.
Use `--verify-only` to check restoration without generation. Recovery outputs are
separate, all subsequent model responses are fresh, and prior decisions and health
history are preserved. There is no fallback to earlier-stage replay.
`--no-open` alone does not disable the server. The normal full terminal command still
launches the combined dashboard unless `--no-explorer` is specified.

Background replay requires saved chunks, reviewed extractions, chapter outline,
concepts, reconciliation, relations and source paragraphs/text. It writes a separate
background experiment and leaves its source intact; it does not run reconstruction or
produce a complete full-run report. Evaluation requires a completed/partial-completed
manifest, graph, chunks, paragraphs, debate, input, statistics and prior report files.
It updates evaluation/report outputs while preserving the graph and original event log.
Existing evaluation trace/provenance behavior is retained.

Registry retrieval ranks names and definitions and starts with a configurable shortlist
(`workload.retrieval_candidates`, default 16), expanding when matching remains uncertain.
Retrieval never authorizes a merge:
identity/scope and relation equivalence checks still apply. Relation verification
checks an exact named built-in contract before searching for alternatives. It
compares complete qualified assertions; a context-specific draft definition need
not use identical wording to a general reusable contract. Unmatched concepts stay
separate, so retrieval can leave duplicate aliases. A surface predicate with a
different meaning can receive a separately named, verified contract; existing
contracts are never overwritten to make a new occurrence fit. Source extraction uses open
predicates. Source and background generation explicitly preserve additional
actions, results and participants in argument_qualifiers, separately from if/when
conditions. These fields remain visible through review, deduplication, graph display
and reconstruction. A bounded quoted-argument completion is available for legacy records.
Up to two model-generated coverage-repair passes then account for each source
assertion against cited graph edges. The audit cites sentence IDs resolved to exact
source spans; an objection must address the affected edge's own evidence. It can
quarantine unsupported accepted edges while preserving their history. Edges with
potentially lost conditions, timing, negation, contrasts, action complements or
renamed directional prepositions also receive two short checks with the same model:
a source reading made without the candidate, followed by a comparison with the
literal qualified edge. Short evidence quotes expand to their complete enclosing
source sentences, preserving exact occurrence offsets; repaired assertions receive
this check too. A related edge cannot supply a missing condition for an unqualified
occurrence claim. These requests disable extended thinking and cap output at
1,536 tokens. An unchanged failed check is not repeated during the same run.
Its objections are checked against the other accepted edges so a valid partial
assertion is not rejected for meaning already represented elsewhere. Failed checks remain explicit unresolved items. `artifacts/source_coverage.json` records remaining gaps; model agreement is
not independent accuracy verification. Gap planning processes every source passage
with its concept anchors, organizing missing explanations across the passage instead
of commissioning questions separately for every concept. Questions are checked
against the whole source; case-specific unknowns and exclusions remain recorded.
Later background questions are checked against already admitted facts before
proposing another explanation. Ambiguous double-encoded negation receives a targeted
model correction, followed by the same semantic admission checks.

Background link construction receives the intended sentence without a seed endpoint
hint. Representation reviewers must copy the saved literal link, including qualifiers,
so they cannot silently replace an incorrect target with the intended one. Otherwise
accepted additions receive a concise counterexample check before publication; a
failure enters the existing bounded repair process. These are model checks, not
independent evidence that a background assertion is true.

Keyed batches budget their complete prompt and response schema, retain semantically
valid siblings when one item needs repair, and split oversized requests without
discarding items. Exact repeated evidence is referenced losslessly in prompts.
Registry decisions use `model.registry_output_tokens` (default 768). Transient Ollama
5xx/429 and transport failures receive at most `model.service_retries` retries
(default 2), with bounded backoff; permanent request errors stop immediately.
Run manifests record new model calls, cache hits, restored checkpoints and resume
provenance. Cached/resumed timings must not be presented as fresh-run performance.

Evaluation preserves exact quotation evidence and identifies conflicting quote
assignments in retry feedback. Claim alignment sends indexed claim text without
duplicating quotations, then independently checks proposed pairs against both full
passages. Code selects a maximum one-to-one set from verified pairs; competing
alternatives remain in the audit instead of causing repeated index-bookkeeping
requests or inflating match counts. This policy is recorded as
`reconstruction_fidelity_v3_verified_matching`.
Each context review assesses its selected pair only: an unrelated reconstruction
error must not reject otherwise equivalent claims elsewhere in the document.

Validation on 2026-11-20: the full `data/AI Chapter.txt` workflow finished with
`qwen3.5:9b`, including all five chunks and document evaluation. It published 62
source edges and three background additions, with remaining gaps reported explicitly.
The final cache-assisted pass took 497.7 seconds (164 new model requests, 1,129 cache
hits). A same-code resume took 14.2 seconds, restored four checkpoints, and reproduced
the identical graph with one new evaluation request and 117 cache hits. These are
not fresh-run benchmarks. All 112 focused tests passed; the broader comparison kept
the same 22 baseline failures/errors and introduced none. Chrome checks confirmed
that all saved qualifications appear in the 65 relationship captions. See
[the final audit and remaining issues](outputs/diagnostics/optimization_results.json)
and [per-role costs](outputs/diagnostics/optimization-final-profile.json).

## Outputs and interpretation

Full runs write `outputs/runs/<chapter>/<run-id>/`: `manifest.json`, `events.jsonl`,
`input.txt`, `statistics.json`, `index.html`, `report.md`, `knowledge_graph.html`,
`reconstruction.txt`, and intermediate JSON in `artifacts/`. The manifest and environment
artifact record input provenance, settings, model metadata/digests, package versions
and hashes of the actual notebook implementation, not the thin terminal adapters.

Exit codes remain 0 (completed), 2 (completed with issues), 1 (failed), and 130
(interrupted). Partial results are retained. The final document score weights claim
fidelity 55%, idea order 25%, ROUGE-L F1 10%, and length similarity 10%; it is not the mean
of chunk scores. A missing/unresolved document evaluation is not assigned a substitute
score. Model judgments are not independent factual verification.

Interaction logs and student records may contain private text. They are not embedded
in the submission notebook. Existing run data is retained in place. See
[the event contract](docs/events.md), [professor workflow](docs/professor.md), and
[input provenance](data/README.md).

## Validation and known limitations

```powershell
python tools/validate_submission.py
python -m unittest discover -s tests -p test_submission.py -v
python -m unittest discover -s tests -q
node --test tests/explorer_logging.test.cjs
python -m unittest tests.test_contextual_grading tests.test_graph_metrics tests.test_assessment_contract tests.test_quiz_statement_review tests.test_quiz_help tests.test_adaptive_quiz tests.test_professor_scope tests.test_professor tests.test_learning_views tests.test_explorer tests.test_quiz_rubric tests.test_quiz_grading tests.test_submission -q
python -m tests.browser_professor_workspace
python -m tests.browser_assessment_contract
```

The validator uses a fresh kernel in an empty temporary directory, with no project
Python modules or input files, and writes actual successful outputs back to the same
notebook. It also checks all five preserved command entry points. No second notebook
is created. The validator defaults to `261273237.ipynb`.

Validation performed on November 8, 2026:

- Fresh-kernel execution passed in an empty directory, with no local project Python
  modules or data files. Actual offline outputs are saved in the notebook.
- All five preserved CLI entry points passed `--help` checks.
- All 10 new submission tests passed: imports, embedded inputs, full orchestration and
  resume with synthetic stage fixtures, background replay/source preservation, stage
  dispatch, saved-result integrity, static rendering, and live loopback graph/dashboard
  servers. Viewer tests block extraction and model construction on startup.
- The original 198-test baseline reported 14 failures and 21 errors. After relocation,
  the 206-test run (including the initial eight submission tests) reported the exact same
  35 failing entries, with no new failures. Two additional orchestration tests then passed
  in the focused 10-test submission suite. Existing failures include schema/fixture and
  semantic-expectation mismatches; resolving them would change scope and may change
  application behavior. The existing suite is **not green**.
- A live one-sentence Ollama smoke test passed preflight and entered extraction, then
  failed with `ModelServiceError` after the deliberately bounded 60-second request timeout.
  It returned exit code 1 and retained diagnostic artifacts. **A completed live full run
  and a real reconstruction score were not verified.** The normal CLI timeout remains
  600 seconds. Logs are in `outputs/submission-*.log`; the failed smoke run is under
  `outputs/submission_validation/` and is not embedded as an experimental result.
- The professor-interface, graph-metric and adaptive-quiz regression set passed 169 tests; all four JavaScript
  logging checks passed using Playwright's bundled Node runtime. A real Chrome workflow
  passed navigation, student/topic/version switching, quiz resumption, pending-answer
  retry after browser/server restart, grading corrections, statement comparison and
  mobile layout checks with no JavaScript errors. UI screenshots were inspected.
  The illustrated guide was regenerated as an eight-page PDF with demonstration data.
- Optional Docker/Neo4j export was not run. Local model availability does not establish
  model quality or reproducibility across hardware, mutable tags or dependencies.

No course rubric was supplied. Resolve
the documented empirical/testing gaps before claiming a fully reproduced research result.
