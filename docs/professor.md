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

Question grading runs first. Whole-graph matching is a separate assessment. If its
bounded citation repairs fail, the valid question grade is saved and graph matching
is labelled **unresolved**. Relationship progress stays unchanged. Under **Class
Overview → student → Inspect answers**, use **Retry graph matching** to retry only
that stage. Failed retries retain the grade; successful retries cannot create a
second submission. Conflicting question and graph judgments require retry or
professor review before changing relationship progress.

A correct term can score 100% for a component question while leaving the
relationship yellow. Green requires an independently answered full-relationship
question, complete rubric evidence, and a validated demonstration of the connection
(or an explicit professor correction of that full-scope assessment). Matching still
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

```powershell
python -m unittest tests.test_assessment_contract tests.test_quiz_statement_review tests.test_quiz_help tests.test_adaptive_quiz tests.test_professor_scope tests.test_professor tests.test_learning_views tests.test_explorer tests.test_quiz_rubric tests.test_quiz_grading tests.test_submission -q
python -m tests.browser_professor_workspace
python -m tests.browser_assessment_contract
python tools/validate_submission.py
python tools/create_ui_guide.py
```

Browser/guide checks require installed Chrome and Playwright. Legacy browser commands
`python -m tests.browser_professor` and `python -m tests.browser_learning_views`
forward to the current three-tab workflow test.

The expanded quiz and interface suite passed 149 tests. The Chrome test exercises all tabs, student/topic/
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
