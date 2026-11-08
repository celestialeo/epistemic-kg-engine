# Professor dashboard

Launch from the project directory with Ollama running and the saved run's model
installed:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --interact --chapter ai-test
```

This **Interacting with graph** step prints one localhost URL and opens the latest
completed AI-test graph, quiz and professor controls on the same page. Use
`--no-open` to suppress the browser, `--explorer-port 8765` to choose a port, or
`--output-root PATH` for another run library. Omit `--chapter` to select the latest
completed run across inputs. No extraction or background generation is started.

A normal full pipeline run also opens this combined page at the end; add
`--no-explorer` to stop after reporting. For a separate class database, the
standalone `python -m pipeline.professor --database PATH` remains available, with
`--runs-root PATH`, `--port 8765` and `--no-open` options.

## Workflow

1. Add students to the roster. Each gets a distinct ID, even if names match.
2. Select a student and input topic. Refresh topics to discover newly completed
   runs. Failed and unfinished runs are excluded. Runs completed with issues are
   available with their status visible. The shared run picker also lists historical
   versions. Use **Professor** or **Run Results** to switch views without restarting.
   Run Results reads saved timings, counts, scores and original/reconstructed text;
   absent measurements say unavailable. It does not show detailed logs.
3. Use the recommended starting concept or choose one explicitly. Recommendations
   identify assessed gaps and unassessed material. Question selection prioritizes
   unassessed facts, then other facts without independent mastery, and can connect
   a known concept to an unknown relationship. Independently correct facts are
   excluded unless **Review independently mastered facts** is checked.
4. Click **Start quiz**, choose who is taking it from the created students, then
   click **Begin quiz**. This explicit choice links the new assessment to that
   student, even if a different student's overview was open. Canceling creates
   no assessment. The student's name stays visible during the quiz; resuming
   keeps its original student. The existing quiz generates and reviews
   graph-grounded questions, grades statements, supplies hints and reveals, and
   adapts subsequent questions to coverage. The examiner explicitly identifies
   which supplied facts the question asks for; context-only facts are not scored.
   Quizzes ask up to five questions and stop when eligible facts are covered.
   Enable review mode, choose another topic, or start a new round for remaining gaps.
5. Inspect answers in assessment history. A professor can override each assessed
   fact's grade, add feedback and explain the decision. The original model result,
   every answer revision, and every override remain in the audit history.
6. Resume unfinished assessments from history, including after restarting the
   dashboard. A delivery retry uses the original request ID so an answer is not
   counted twice. A model failure leaves the last saved question intact.
   Failed grading also retains the submitted answer. Resume that assessment and
   use **Retry pending request**; the original request is restored from the server
   even in a fresh browser, so retrying does not create another submission.
7. The full interactive graph stays at the bottom. Its display picker switches
   between exploration, student knowledge and class proportions. Exploration is
   temporary and never writes student evidence. Beginning a quiz clears it, including
   late query responses, and loads the selected student's saved knowledge. Green
   means independently correct, amber partial or assisted, red incorrect/not
   demonstrated, and gray unassessed. Reveals and hints alone earn no mastery.

## Scores, coverage and trends

- Correct facts earn 1, partial facts 0.5, and contradictions or facts not
  demonstrated earn 0. Missing an answer fact is not labeled a contradiction.
- A question score is the average over its requested facts. A session score is
  the average of its answered, scorable questions. Only the latest attempt at
  each question counts toward the score; attempt counts include all submissions.
- Questions without factual rubrics are unscored. Starting a quiz, receiving a
  hint, or revealing an answer alone does not create an assessed score.
- Evidence must come verbatim from the exact learner statement being graded,
  never from the question or reference fact. Invalid-citation repairs identify
  the offending fields and require a reassessed judgment with evidence selected
  from numbered learner-text spans. The server copies those exact spans and
  validates them before accepting the judgment. Exhausted repairs leave the
  answer pending; they never award credit or assign a default zero.
- Assisted answers count toward scores and are explicitly marked. Coverage
  separately counts independently correct and assisted correct facts. Coverage
  uses the most recent answered judgment per fact, including professor overrides.
- An assessment count is a session with at least one scored answer. Started and
  completed counts are also shown; an unfinished assessment can have a score.
- In the optional latest-input-topics table, a topic score is the latest assessed
  session for that exact graph version.
  Class scores average each assessed student's latest score, giving students
  equal weight. Unassessed students are excluded from averages and counted
  separately. Class trends show this evolving average at each assessment.
- Strongest and weakest are relative ranks among assessed input topics. With one
  assessed topic it is both. Review suggestions list assessed topics with less
  than full credit; unassessed topics appear separately as candidates to assess.
- Trend points retain the exact run used. Scores and coverage never silently combine
  different graph versions. Historical sessions and their run links are preserved.
- Overrides recalculate analytics and future recommendations. Original model
  grades remain available; the trend displays the current corrected scores.

## Class Overview and selected-student metrics

Click **Class overview** for the comparison table. Selecting a student opens their
metrics and saved graph. All main metrics use the selected run, with class means
weighted equally per student and unavailable observations excluded with `n` shown.
Coverage includes roster members who have not answered; answer performance does not.

| Metric | Definition |
| --- | --- |
| Knowledge coverage | Independently correct relationships / all relationships in this version. |
| Assessment coverage | Relationships with an assessed answer / all relationships. Unassessed is not incorrect. |
| Answer performance | Mean latest answer per question, with independent and assisted means and sample sizes separately. |
| Topic coverage | Knowledge coverage in deterministic graph communities; cross-community facts form bridge topics. Labels are representative concepts. |
| Connected understanding | Mastered concepts in the largest undirected mastered component / all mastered concepts. A mastered concept is an endpoint of an independently correct relationship. |
| Fragmentation | Number of mastered components and singleton mastered concepts. With endpoint-derived mastery, a singleton can only arise from a self-relationship. |
| Topic concentration | Sum of squared shares of mastered facts across topics (HHI). Near 1 indicates concentration; smaller values indicate broader topic distribution. This is distinct from graph connectivity. |
| Progress | Cumulative coverage and latest-per-question performance after each answer on this version; transferred knowledge is the starting baseline. Corrections are reflected retrospectively. |

Class topics show strongest/weakest **assessed** scores, unassessed relationship
counts and assessment sample sizes. Class trends use the current roster as a fixed
cohort. The class graph colors and widths show independently knowledgeable students
divided by the whole roster; hover for `known / students` and `assessed / students`.
The expandable relationship list exposes the same counts without relying on color.

Knowledge transfer requires a unique exact semantic match in an earlier run of the
same input: endpoint labels and definitions, directed relation, conditions, modality
and other semantic fields must agree. IDs and provenance alone do not establish a
match. Ambiguous or changed facts remain unassessed. Transferred records retain
their source run, fact and answer; local evidence supersedes transfers. Historical
answer scores are not copied into the new version's performance averages.

## Persistence and scope

The SQLite database at `outputs/professor/students.sqlite3` stores students,
versioned graph snapshots, quiz checkpoints, answers, scores, feedback, request
receipts and override history. Updates to a quiz, its answer and retry receipt
commit together. Keep this file to retain history. Back it up while the dashboard
is stopped. Existing graph exploration/model logs continue under each run's
`explorer_sessions`; the original graph and pipeline result files are unchanged.

The dashboard is a local professor-operated application bound to localhost. It
does not implement separate authenticated student accounts or a shared remote
classroom service. Grading inherits the existing model's limitations, including
requiring explicit names for both entities in a credited statement. Professor
review is available for those cases. No extraction or background-knowledge logic
is changed by the dashboard.

## Verification

Run the HTTP/persistence and existing explorer regression tests:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_professor tests.test_learning_views tests.test_quiz_rubric tests.test_quiz_grading tests.test_explorer -q
```

The optional browser check uses installed Chrome and Playwright (test dependency
only: `python -m pip install playwright`):

```powershell
& .\.venv\Scripts\python.exe -m tests.browser_professor
& .\.venv\Scripts\python.exe -m tests.browser_learning_views
```

It uses deterministic model fixtures and an isolated database, exercises the
five-question review, overrides, analytics, view switching, exploration reset,
student isolation, assisted-answer colors, fresh-browser recovery, graph versions
and mobile layout. Screenshots are saved under `outputs/professor_checks`.
