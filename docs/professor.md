# Professor workspace

The left navigation has three tabs: **Quiz**, **Run Insights**, and **Class Overview**.
See the [illustrated PDF guide](Interactive_Graph_Guide.pdf) or
[HTML guide](Interactive_Graph_Guide.html). Its screenshots use clearly labelled,
isolated demonstration records, not actual student or experimental results.

## Open saved work

From the project directory:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --interact --chapter ai-test
```

This opens the latest eligible saved run without extraction or background generation.
Omit `--chapter` for the latest eligible input; use `--output-root PATH` for another
library, `--no-open` to suppress the browser, and `--explorer-port 8765` for a port.
Restart an already-running server after changing the notebook, then refresh the browser.

The existing terminal commands and notebook modes remain available:

```powershell
# Exact saved run, including an older version
python -m pipeline.explorer "PATH_TO_RUN_DIRECTORY" --no-open

# Professor workspace with a chosen library and database
python -m pipeline.professor --runs-root outputs/runs --database outputs/professor/students.sqlite3 --no-open
```

The notebook remains the implementation source: `261273237.ipynb`. Use its
`interact`, `graph`, or `professor` modes for these viewers. Saved-graph browsing
needs no extraction or model call; quiz generation, grading, hints and statement
comparison use the saved configuration's Ollama model. Full pipeline, background
replay and saved-run evaluation commands retain their existing flags.

## Three workflows

### Manual graph editing

In **Run Insights**, choose a saved run and use **Edit this knowledge graph**.
Add, edit, or delete concepts and relationships. Relationship endpoints can be any
concept in that run, including a concept just added. Conditions, modality, purpose,
timing, evidence, and contextual participants are editable. Names must be unique
within the graph. Deleting a concept also removes relationships that reference it,
including references through contextual participants, in one reversible action.

Each successful save takes effect immediately for that run's visualization,
statement comparison, new quizzes, and learning metrics, including All Topics.
Purple identifies manually added or edited relationships and added concepts.
The original `artifacts/graph.json` is never overwritten. Manual versions and their
audit trail live in `manual_graph.sqlite3` alongside that run's manifest; keep this
file when copying or backing up the run. Other runs and future pipeline generation
do not read or inherit this sidecar.

After the first save, **View original graph** opens a read-only comparison.
**View edited graph** returns to the saved working version. Switching views does
not undo edits or change the graph used for quizzes and learning metrics. Saved
pipeline quality and reconstruction scores still describe the generated graph;
they are not recomputed or presented as validation of manual assertions.

**View manual changes** lists each action with affected IDs and labels, full before
and after records, UTC timestamp displayed in the browser's local timezone, optional
reason, and professor identity when supplied. This local workspace has no login;
an entered professor name is explicitly labelled **self-reported**, and an omitted
name is recorded as unavailable. An authenticated identity is used if the hosting
application supplies one.

**Revert change** appends a compensating action and keeps the original history.
Reverting a concept deletion restores its removed relationships together. A later
edit to the same record must be reverted first; new dependent relationships must
also be removed before reverting creation of their concept. Reversions themselves
can be reverted. Concurrent edits use revision checks: if a browser is stale,
use **Reload saved graph**, inspect the latest changes, and retry.

Questions retain the graph meaning they were created against. A change to a
relationship's direction, definition, qualifications, or endpoint/participant
meaning flags affected historical answers. Their questions, answers, grades,
corrections, and assistance history remain intact, while obsolete evidence no
longer counts as mastery of the changed meaning. Exact restoration of the old
meaning makes its valid evidence applicable again. Source-reference-only changes
do not invalidate mastery. Historical answer performance remains a historical
score; current coverage uses the edited graph.

Start a new quiz after a semantic graph change. An affected unanswered question
cannot be graded against the new meaning. An answer already saved as pending can
still be retried against its pinned historical graph, without awarding mastery of
the changed fact. Older questions without a pinned snapshot use the preserved
generated graph. No model call is needed to edit, compare versions, or revert.

Validation commands (isolated fixture data; no changes to saved experimental runs):

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_manual_graph -q
& .\.venv\Scripts\python.exe -m tests.browser_manual_graph
```

**Quiz:** Select a student, inspect their learning graph, and start a quiz from a
source run. The starting concept can be recommended from progress or chosen.
Each quiz belongs to exactly one student and one run. In All Topics, suggested sources
prioritize remaining unique gaps; exact overlapping evidence avoids retesting known
facts. Review mode includes independently known facts. Questions stay grounded in
the chosen source, target requested facts, and normally stop after five questions
or when eligible facts are exhausted. Hints and reveals mark subsequent answers to
that question as assisted. They do not themselves create assessed evidence.

Normal quizzes never target green facts. Independent mastery persists across quizzes,
restarts and exact, unambiguous matches in other saved graphs. A later partial,
incorrect or assisted answer keeps its own score without erasing earned green.
Yellow facts remain eligible; answering them correctly in a later quiz without hints
or a reveal turns them green. Optional review of green facts is explicit.

Question generation prefers document-supported facts within the chosen focus, audits
disputed answer-leak rejections, and rejects near-identical rewrites. If one fact's
drafts fail, it tries up to two other eligible facts. Deferred facts retain their
previous state and remain eligible in a later quiz. If none succeeds, the interface
offers **Try another concept**, without claiming an assessment was saved. Pending
submitted answers still use the existing durable grading/retry workflow.

Hints and reveals allow normal subject words such as **source**, **relationship**
and **conditions**. Their display checks reject internal identifiers, private field
names and serialized graph records instead of applying a word blacklist. Validation
retries name the offending identifier, field or formatting and explain how to repair it.
Hints are checked for verbatim and paraphrased answer disclosure; a hint that cannot
be generated or checked is not shown and does not change quiz state.

If Reveal generation fails, including when its model cannot initialize, the app can
show the saved expected answer that passed the original grounded question review.
It rechecks that answer's display safety first and labels the fallback **Saved validated
answer**. An absent or unsafe fallback produces a reveal-specific error. Hints never
use this fallback. Successful reveals retain normal assistance marking and idempotent
persistence; failure messages distinguish help problems from assessment-save failures.

All Topics quizzes also retain their original progress-source IDs in the checkpoint,
so restarts or newer runs cannot silently replace that context. Corrections to those
original answers are reflected when the quiz resumes.

Resume from saved history, including after a server/browser restart. A pending
grading request retains its answer and original request ID; retrying does not create
a duplicate submission. Switching student or topic hides an out-of-scope active quiz
without deleting it. Returning restores it. Unsubmitted text is preserved during
ordinary view switching but is not durable assessment evidence.

New quizzes use **question-aware semantic grading** (`contextual_v3`). One scoped
assessment per requested fact reads the entire learner answer in question context,
instead of scanning every graph edge separately for every sentence. Synonyms,
paraphrases, clear abbreviations, minor typos, pronouns and short contextual answers
can receive full credit. The graph's meaning, direction and qualifications still
apply. The question can supply referents or stated conditions; it cannot supply a
missing explanation. Exact quotes from the learner and any question passage used
to resolve context are stored separately, with the met criterion indices.

Green requires a complete, independently demonstrated full relationship. Partial
substantive explanations and correct assisted answers are yellow. Contradictions
and answers that do not demonstrate the requested meaning are red, with distinct
labels. Unassessed edges remain gray. Mere keyword lists, unrelated facts, requests
for help and demands for full credit do not earn credit. An explicit uncorrected
contradiction takes precedence; a clearly retracted mistake followed by a correction
is judged by the final corrected claim. Previously earned independent green still
persists across later attempts, with answer scores recorded separately.

New single-fact practice questions use neutral relationship/role prompts rendered
from the selected concept pair. The model writes the expected answer; consistent
meaning-based criteria assess the connection, direction, conditions and claim strength.
Internal relation labels and abstract definitions are not phrases to recite;
a focused answer check verifies direction, support and qualifications before the
complete question/specification review. Source quotations and concept definitions
can contain several facts, so they are excluded from the question-writing payload.
The selected relationship fields alone define its scope. Questions are reviewed
for full-relationship scope. They must not repeat the entire fact and
then demand an internal mechanism absent from the graph. The expected answer is an
example, not an exact-wording requirement. Model failures preserve a pending answer
without assigning a default grade. This is prompt and application-logic refinement,
not retraining the underlying model. Partial and contradictory judgments receive
a second semantic review of the original answer, without the first rationale.

Negative rubric constraints (for example, "avoid claiming production") do not
require an explicit disclaimer in the learner's answer. The constraint is met
when the prohibited claim is absent. Internal relation labels are never required
wording; their meaning is what matters.

Older saved questions keep their version-2 evidence policy and retry workflow
described below. Standalone **Explore / compare statements** remains a separate
whole-graph semantic exploration tool; it never writes student mastery.

Grading checks the information the question actually asks for. A short answer may
be complete without repeating context already supplied in the question. Statements
initially labelled non-assertions receive a separate classification review using
the exact learner words and question, without the expected answer. Reviewed answer
fragments can earn question credit but do not manufacture whole-graph matches.
Questions and help requests remain ineligible as evidence. Every credited quote
must still occur verbatim in the saved answer; retry feedback distinguishes an
unknown statement ID, an ineligible statement, and a quotation mismatch. Failed
classification or grading leaves the submission pending rather than assigning a
default score. The durable pending record is labelled **unresolved** after a failed
attempt and retains its error, exact answer and original request ID.

Every new question has a reviewed **assessment specification**: the fact ID,
information requested, context already given, required criteria, and either
`component` or `full_relationship` scope. The generator and reviewer check that the
question and expected answer agree with this specification. Grading uses the same
saved specification; mastery updates cannot expand its scope. Legacy active
questions acquire a reviewed specification before grading, without rewriting their
question or answer. Existing historical grades and earned progress are retained.

For older version-2 questions, question grading runs first. Whole-graph matching is a separate assessment. If its
bounded citation repairs fail, the valid question grade is saved and graph matching
is labelled **unresolved**. Relationship progress stays unchanged. Under **Class
Overview → student → Inspect answers**, use **Retry graph matching** to retry only
that stage. Failed retries retain the grade; successful retries cannot create a
second submission. Conflicting question and graph judgments require retry or
professor review before changing relationship progress.

A correct term can score 100% for a component question while leaving the
relationship yellow. Green requires an independently answered full-relationship
question, complete rubric evidence, and a validated demonstration of the connection
(or an explicit professor correction of that full-scope assessment). Version-2 matching still
requires distinct source/target quotations and a connection quotation from the
learner's unchanged words. Partial answers earn 50% only with substantive correct
evidence and an identified missing criterion. Incidental matches outside the
question's specification remain diagnostic and do not change mastery. Corrections
to component questions cannot promote the whole relationship to green.

**Run Insights:** Select a saved run to inspect the generated source graph, graph
counts, extraction/validation results and available quality metrics. All Topics shows
aggregate unique graph counts plus a source breakdown, with one run selected for
detailed inspection. Original/reconstructed text, validation records, stage timings
and configuration are expandable. Missing measurements say Unavailable. There is no
invented cross-run quality score. Pipeline fidelity is separate from student learning.

Expand **Review background facts for quizzes** to inspect generated claims and
record a professor approval or revocation with a reason/reference. A generated
`evidence` field or agreement among models is not independent support. This version
conservatively requires explicit professor approval for every background fact;
automatic external-source verification is not implemented. Approval is stored
separately from the saved run and bound to its version and exact fact fingerprint.
Unapproved background facts cannot generate questions, grades, hints or reveals.
Revocation blocks further use without deleting historical progress. Existing pending
answers can be retried after approval. The standalone graph explorer excludes
unapproved background material; use the professor workspace for this review workflow.

**Class Overview:** See equally weighted class metrics, observed strengths/difficulties,
and searchable student cards with mini learning graphs. A card opens that student's
graph, results, history and grading corrections within Class Overview.
**Back to Class** returns to the class; **Quiz This Student** preserves the student and
topic while opening Quiz. Miniatures preview at most 30 concepts and 60 relationships;
their metrics cover the full selected scope.

## Shared topic and version rules

- A topic represents an input document/chapter; a run is one saved graph version.
  The selected topic/version applies across tabs, metrics, graphs and history.
- **All Topics** selects one latest registered version per input topic, including
  retained snapshots whose source directories no longer exist. Exact recorded
  relationships count once across topics. Source run IDs remain attached.
- Identity requires matching endpoint labels, definitions and kinds, direction and
  all non-provenance relation fields (including conditions and modality). Quotes,
  origin, generated IDs and confidence alone do not create another fact. No synonym
  matching is inferred. Semantic paraphrases may remain separate.
- Topic breakdowns describe each source separately. Rows can overlap and must not
  be added or averaged to calculate aggregate coverage.
- A specific topic allows selection of a historical version. History includes every
  version of that topic and labels sessions outside the current metric scope.
  Resuming an older quiz explicitly selects its original topic and run.
- Saved grades are never copied into fabricated answer scores. An independently
  correct demonstration transfers only over an exact, unambiguous semantic match,
  retaining its source run, fact, answer and timestamp. Other states retain the
  earlier same-topic transfer rule. Current answers replace provisional states;
  earned independent mastery persists. Corrections recompute this state from all
  effective answers: green is revoked only when no valid independent demonstration
  remains. Original grades, later mistakes and all overrides stay in history.

## Evidence, colors and denominators

Learning states distinguish **unassessed**, **incorrect/contradicted**, **not
demonstrated**, **partial**, **assisted correct**, and **independently correct**.
The graph uses green for independent, amber for partial/assisted, red for incorrect/
not-demonstrated, and gray for unassessed. Counts and history distinguish states
sharing a color. Unassessed is never treated as an incorrect answer.

| Metric | Definition |
| --- | --- |
| Known without help | Independently correct unique relationships / all unique relationships in scope. |
| Checked | Unique relationships with resolved relationship assessments (including partial demonstrations) / all unique relationships. Unresolved matching does not add coverage. |
| Answer performance | Mean latest answer per distinct session/question on included versions; revisions count once. Includes assisted answers, also reported separately. Different questions can test the same fact; this is not unique-fact coverage. |
| Question score | Average grade over the specification's requested facts: correct 1, partial 0.5, contradiction/not demonstrated 0. Component correctness is distinct from relationship mastery. Unresolved grading has no score, not zero. |
| Class averages | Equal weight per roster member. Coverage includes unassessed students; answer averages exclude unavailable scores and show n. |
| Relationship proportions | Independently knowledgeable students / full roster; assessed count shown separately. |
| Connected understanding | Mastered endpoint concepts in the largest undirected mastered component / all mastered endpoint concepts. |
| Fragmentation | Number of mastered components and singleton mastered concepts; a singleton can only result from a self-relationship. |
| Concentration | Sum of squared mastered-fact shares across deterministic graph communities (HHI); near 1 means concentrated. Communities are distinct from input topics. |
| Progress | Recomputed per source version after each answer; corrections reflected retrospectively and transfers shown as a baseline. Versions are never joined into a synthetic trend. |

Advanced learning metrics, version-specific progress charts, exact trend values and
graph-community results remain available in an expandable section. Connectivity and
concentration are unavailable without mastered evidence, rather than fabricated zeros.
Common strengths/difficulties report observed evidence and sample counts; unassessed
material is not labelled a weakness.

Circle color summarizes all connected facts: green requires every incident link to
be independently known. Mixed known/unknown links produce a yellow circle, and the
remaining links may be quizzed. Connectivity metrics count endpoints of known links;
they do not count only completely green circles. Dated progress excludes evidence
earned later in other quizzes, while corrections apply retrospectively.

## Exploration and corrections

### Class Overview graph metrics

The **Viewing** selector switches between **Class overview** and a named student.
Section links jump to the summary, metrics, student roster, graph, or quiz history.
Student cards and the expandable comparison table open the same individual view.
An individual view always displays that student's learning graph; the class view
displays prevalence across the roster. These displays cannot silently exchange roles.

The metric explorer groups twelve metric families into **Breadth**, **Connections**,
and **Topic structure**, with **All 12** available. Every card includes a plain-language
question and an expandable definition. Structural cards include a reference comparison;
reference topology is descriptive, not independent validation of generated content.

| Family | Definition and interpretation |
| --- | --- |
| Relationship coverage | Independent unique facts / reference facts. |
| Assessment coverage | Unique facts with resolved assessments / reference facts. |
| Concept reach and completeness | Reach: endpoints of independent facts / reference concepts. Completeness: average independently known incident-fact fraction over concepts with reference facts. Reach alone is not concept mastery. |
| Average degree | Distinct undirected neighbors per demonstrated concept; the concept table also shows incoming/outgoing distinct-neighbor degrees. |
| Density | Simple undirected connections / possible connections among demonstrated concepts. Small graphs can be dense despite low coverage. |
| Connected components | Separate groups of demonstrated endpoints, with the largest group's share of those endpoints. |
| Clustering coefficient | Mean local triangle-closure fraction over demonstrated endpoints; degree below two contributes zero. |
| Cross-community connections | Independent reference facts between communities / all reference facts between communities. No reference bridges means not applicable. Communities are not input topics. |
| Global efficiency | Mean inverse shortest-path distance across all reference concepts, with unreachable pairs contributing zero. Measures structural integration, not thinking speed. |
| Communities and modularity | Number of fixed reference communities and modularity at resolution 1 of the demonstrated topology using that partition. Higher is not automatically better. |
| Knowledge concentration | HHI of mastered-fact shares across fixed reference communities and explicit bridge groups. Near one means concentrated; group sizes affect available opportunities. |
| Connection strength | Mean independently known incident facts per reference concept. For the class, this equals summing fact prevalence around concepts and averaging. Completeness supplies the normalized comparison. |

Topology collapses parallel facts and excludes self-links. Semantic coverage and
strength retain distinct facts, direction, and qualifications. Self-facts can establish
a demonstrated endpoint but do not create a structural link. Reference topology includes
isolated concepts. Student degree, density, clustering and components use demonstrated
endpoints; efficiency always retains the full reference node set. The deterministic
reference partition is reused for all students, with self-links excluded during partitioning.
No mastered evidence gives unavailable structural metrics; coverage can still be zero.
Undefined denominators remain unavailable. A recorded mastery is a retained independent
demonstration, not a claim about present retention or the student's entire mental model.

Class cards show equal-student means, medians, ranges, and contributing sample sizes.
They summarize individual graphs, never the topology of their union. **Shared core**
is coverage known by at least 80% of the entire roster; **Collective coverage** is known
by at least one student. A connected class path may combine different students' facts.
Empty-roster metrics are unavailable. No observed difficulty is inferred from missing evidence.

**Explore concept degrees, strength & completeness** offers name filtering, sorting,
exact degree/assessment counts, and a degree-distribution chart. Class degree charts
count student–concept pairs among demonstrated concepts; individual charts count that
student's demonstrated concepts. Each student has separate independent-strength,
observed-support, and unassessed panels. The existing source-topic breakdown and
version-specific progress views remain available.

Metric validation: `python -m unittest tests.test_graph_metrics -q` checks known graph
shapes, direction, parallel/self-links, disconnected paths, missing evidence and class
aggregation. `python -m tests.browser_graph_metrics` exercises all twelve cards,
filters, concept exploration, switching, reload and mobile layout using isolated,
explicitly labelled demonstration data.

Select circles/arrows for definitions and evidence; drag, zoom, search, focus and fit
the graph as before. **Explore / compare statements** on one source enables temporary
model matching and does not write student grades. The aggregate graph retains every
source reference; open a source topic for statement comparison. An active quiz returns
the graph to the student's learning state and clears temporary exploration.

Use **Inspect answers** in history for original grading, submitted text, expected
answer and evidence. Correct each requested fact's mark and provide feedback/reason.
Original results, revisions and every correction remain in the audit trail. Assisted
status is retained, and corrections update metrics and future recommendations.

Grading evidence must come verbatim from the learner statement. Failed validation
repairs leave the answer pending; they do not award credit or silently assign zero.

## Persistence and limits

Existing SQLite storage at `outputs/professor/students.sqlite3` remains authoritative
for students, graph snapshots, quiz checkpoints, answers, receipts and corrections.
No schema migration or replacement of existing progress is required. Aggregate
summaries are computed read-only. Quiz writes keep checkpoint, answer and receipt
atomic. Stored request signatures remain compatible with pre-scope requests.

Graph interactions continue using saved-run `explorer_sessions`; pipeline artifacts
are unchanged. This is a local professor-operated app bound to localhost, without
separate authenticated student accounts. Grading inherits model limitations and
can need professor review. No controlled learning-benefit claims are made.

## Verification

### Graph admission and optional refinement

Full generation and background replay publish the existing source-review and
background-debate decisions directly. The additional graph-quality review and repair
stage has been removed from both pipelines. New manifests explicitly record that
it did not run; the dashboard can load these completed runs without a quality
certificate. Background facts still require professor approval for quiz use.
Evaluation measures reconstruction quality separately and does not certify facts.

The following behavior belongs only to the explicitly invoked graph-refinement
command and historical runs that required it. In that optional workflow, concepts
receive explicit identity and definition reviews; relationships receive literal
direction, evidence, endpoint, and qualification checks. An edit and its verification
are separate model requests. A separate reading of the displayed edge excludes its
source quotation and predicate contract; verification must compare that reading
with the source and contract rather than silently supply missing meaning.
Verified corrections to conditions and modality replace inherited values; omitted
values retain the previous scope for verification. `ReviewPolicy` controls bounded retries, batch sizes,
and candidate retrieval. Source coverage is checked per chunk. Missing or
misrepresented assertions can receive a proposed repair, a separate evidence and
meaning check, and a new source-coverage check before acceptance. Healthy records
survive a failed neighboring record. An already concise assertion is verified before
any rewrite; accepted node decisions remain fixed while failed neighbors are repaired.
Node edits update their existing IDs. Identity merges cannot collapse the participants
of a source relationship into a self-link. Source recovery receives the specific missing
claims, protects healthy assertions, and must demonstrate progress before application.
Recovered assertions are verified individually before checking the revision's scope
and progress. Scope verification receives the complete resulting assertions after
removals and replacements, with removed assertions marked as historical context.
Node review includes other source mentions as well as incident evidence
within its context budget. Verification receives the proposed content without the
editor's explanation, keeping the two decisions separate.
Recovered concepts use their verified definitions rather than stale descriptions from
unlinked mentions; mention-only provenance retains names and IDs without such definitions.
Final consistency review uses bounded edge
batches with shared-endpoint context, rather than one unbounded graph prompt.
These checks are not an exhaustive proof of global consistency.
Within each chunk, the coverage reviewer checks one sentence per request, with the
paragraph as context. It enumerates that sentence's assertions
and maps them to graph edges. Evidence quotations are omitted from this comparison
so a quoted but unrepresented assertion cannot masquerade as graph content.
Source coverage, background challenges, final consistency and source recovery use
reasoning mode by default, recorded in the review policy
and model requests, and restores the caller's setting afterward. Failed node
batches can receive bounded individual repairs with merging disabled; each still
requires independent verification. Background facts receive a separate attempt to
find counterexamples, incompatible participant roles, or missing qualifications.
Reasoning checks have a separate bounded output budget, reduced using an input-size
estimate. Exhausting the budget for optional background knowledge withholds that
candidate. Required source and consistency checks can retry once as direct structured
checks with unchanged criteria; the audit records these in `direct_fallbacks`.
Later checks of the exhausted role use direct mode for the rest of that review,
avoiding repeated budget exhaustion while still requiring each verdict.
A rejected verdict or failed retry still blocks publication. Disable this retry with
`ReviewPolicy.reasoning_fallback=False` for reasoning-only checks.
Resume can replay an identical recorded output-limit failure without repeating
inference. It remains rejected, and changes to the request or model invalidate reuse.
Unresolved source claims, node reviews, service failures, and final
consistency failures stop publication. Rejected optional background enrichment is
excluded and recorded in the audit. Isolated nouns do not trigger attachment generation:
source-coverage recovery adds only missing assertions, while mere mentions remain in provenance.

Relation keys contain at most three words and 32 characters. Detailed definitions,
evidence, conditions and modality remain available separately. A property is not
interchangeable with its reduction: that distinction must appear in the actual
endpoints and predicate. Source-only mentions receive a supported connection where
one is explicitly stated; otherwise they remain in provenance as unlinked mentions,
outside the assessable concept count. No edge is invented just to increase connectivity.

The graph carries a content fingerprint. The loader rejects a reviewed graph whose
content changed after review, or a new run missing its required quality result.
Older runs remain inspectable; they do not acquire a quality certification by loading.
Model review is not independent factual verification, and background-fact approval
for quizzes is still required.

`python -m pipeline.graph_quality <saved-run>` creates a new version beside the source
run. The original graph and student records are preserved, and no old reconstruction
score is attached to the changed graph. `--resume-review <review-run>` reuses exact
validated responses after an interrupted review. The notebook exposes the same action
as `MODE = "refine"`. Inspect `artifacts/graph_quality.json` for all decisions and
`artifacts/graph_before_review.json` for the input graph.

```powershell
python -m unittest tests.test_graph_quality tests.test_submission -q
python tools/verify_graph_quality.py outputs/runs/ai-test/<reviewed-run-id>
python -m unittest tests.test_topic_independence -q
```

The browser check uses an isolated student database, verifies that background facts
still require approval, and checks graph rendering, details, reload, and JavaScript
errors in Chrome. It never modifies the live student roster.

Custom subjects use `--input path/to/text.txt` with the same extraction, background,
review, evaluation, and professor workflows. The implementation contains no examples
about the validation topics in its inference/grading prompts. English sentence-pattern
repairs specific to the earlier AI-test issues have been removed; participant repairs
use the assertion's meaning and require verification. Built-in chapter names remain
optional file-selection shortcuts. General schema limits and semantic relation
contracts remain explicit; they are not a closed topic vocabulary.

The two three-paragraph validation inputs and their independent source-claim checklist
are in `archive/inputs/validation`. The checklist is evaluation data and is never read by the
pipeline. `tools/validate_topic_runs.py RUN_A RUN_B --output REPORT.json` checks that
saved runs used identical code/model settings, passed review/evaluation, retain valid
quotes and artifact hashes, and emits their assertions for a separate meaning audit.
Reconstruction scores are model estimates, not independent accuracy percentages.

The graph's relationship list follows source order and exposes participant roles,
intended purpose, timing and other qualifications. Select a card or an arrow for its
source quote and predicate meaning. Dotted connectors attach additional participants
to an assertion; they are not independently asserted causal or ownership arrows.
Search and quiz material include those participants. A purpose remains an intention,
not evidence of an achieved result. Background budget exhaustion can use one recorded
direct verification fallback with the same criteria; counterexamples and uncertain
claims still prevent acceptance, and professor approval is still required for quizzes.

### Synthetic AI-test class

`tools/seed_ai_class.py` creates ten named synthetic learners, with four
completed sessions each. Profiles include independent understanding, topic-specific
strengths, improvement, partial answers, explicit contradictions, unrelated answers
and success after an answer reveal. Answers are authored scenarios graded by the
real local model; scenario labels are never supplied to the grader and no professor
grade overrides are used. Adaptive sessions can end early when all facts are mastered.

The tool stages its records and resumes interrupted work. `--publish` replaces
student and assessment records only after all forty sessions complete; graph
snapshots remain intact. Use a fresh work directory to create a new exercise.
The AI-test graph is used as the exercise reference, including its background facts;
this explicitly recorded exercise approval does not verify their external correctness.

```powershell
python tools/seed_ai_class.py --run outputs/runs/ai-test/run_20261030_100931_UTC-0400_8ae6bd9d --work outputs/professor_checks/ai_demo_20261111 --database outputs/professor/students.sqlite3 --publish
python tools/verify_demo_class.py --run outputs/runs/ai-test/run_20261030_100931_UTC-0400_8ae6bd9d --database outputs/professor/students.sqlite3 --output outputs/professor_checks/ai_demo_20261111/browser
```

The saved `positive_audit.json` checks correct paraphrases against both question
variants for each of the twelve relationships. `behavior_audit.json` checks twelve
answer behaviors, including pronouns, typos, unrelated facts, keyword lists,
contradictions and self-corrections. These are targeted checks of the local model,
not a general accuracy benchmark. The final browser verification checks all ten
students, their histories, individual metrics, class navigation and mobile layout.

### Regression checks

```powershell
python -m unittest tests.test_contextual_grading tests.test_graph_metrics tests.test_assessment_contract tests.test_quiz_statement_review tests.test_quiz_help tests.test_adaptive_quiz tests.test_professor_scope tests.test_professor tests.test_learning_views tests.test_explorer tests.test_quiz_rubric tests.test_quiz_grading tests.test_submission -q
python -m tests.browser_professor_workspace
python -m tests.browser_assessment_contract
python tools/validate_submission.py
python tools/create_ui_guide.py
```

Browser/guide checks require installed Chrome and Playwright. Legacy browser commands
`python -m tests.browser_professor` and `python -m tests.browser_learning_views`
forward to the current three-tab workflow test.

The expanded quiz, metric and interface suite passed 169 tests. The Chrome test exercises all tabs, student/topic/
version switching, active quiz context, hints, browser/server restart, pending-answer
retry idempotence, history, corrections, statement comparison and mobile layout with
no JavaScript errors, plus generation-failure recovery and yellow-to-green persistence.
Fixtures use isolated databases and deterministic model responses; they do not claim
live-model quality. The previously failing background fact also generated an accepted
question with local qwen3.5:9b in a read-only student-data check (two model calls).
This single successful generation is not a broader quality benchmark.
The previously failing Reveal also passed with local qwen3.5:9b while using the word
“source”; a hint passed the new disclosure review in the same three-call check.
Neither live check wrote student records. Seventeen help-focused regressions cover
precise retries, ordinary language, internal formatting, withheld unsafe hints,
reveal fallback, model startup failure, restart persistence and standalone routes.
Screenshots/logs remain under ignored outputs.
See README for broader pre-existing suite failures and inference limitations.
## Student-contributed knowledge

After an answer's grade is saved, the workspace checks its factual claims in a separate request. Extraction processes short passages with the full answer as reference context, preserves exact quotes, and proposes subject–predicate–object relationships. Each candidate receives a factual review and a second challenge covering correctness, relevance, semantic novelty, educational value, and fidelity to the quote. The application checks connection to existing concepts directly. The complete current graph participates in novelty review, compacted into context-sized pages with bounded review responses.

Accepted contributions appear in **pink** in the regular **Explore** graph. The Student contributions panel shows the student, original answer, exact quote, model decisions, publication status, and professor review history. These are model knowledge reviews, not external source verification. Uncertain or disputed candidates stay outside the graph for professor review. Duplicates and rejected claims remain inspectable.

Contribution checking never changes a quiz grade or grants mastery. Existing quizzes keep their original graph snapshot. Added relationships need separate professor approval under **Run Insights → Review background and student facts for quizzes** before future quizzes can assess them.

Use **Undo graph addition** with a professor name and reason to remove a published contribution. Undo preserves concepts used by later relationships and refuses to overwrite later edits to the relationship itself. Grades remain unchanged. Student records and pending checks persist in `outputs/professor/students.sqlite3`; graph additions and their edit history persist in each run's `manual_graph.sqlite3`. Back up both to preserve a complete workspace. A failed or interrupted check can be retried from the contributions panel after restart.

The generic runtime lives in the notebook's `pipeline.contributions` module and extends the existing student store, graph edit log, and professor routes. AI-specific answer examples exist only in `tools/demo_student_contributions.py`, a resumable demo utility that backs up and clears student records on its first invocation. It uses real quiz grading and contribution checks; its scenario labels do not determine scores.
