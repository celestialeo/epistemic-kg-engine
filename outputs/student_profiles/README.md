# Student records and provenance

The roster now also includes **Liam Morgan**, a fictional microglia concept specialist.
The [additional quiz exercise](additional_quizzes/README.md) preserves all original
records and documents the four students' additional quizzes. Use
`python tools/extend_student_profiles.py verify` to check the expanded roster.
The totals and verification results below describe the original three-student exercise.

These three students are fictional. Their records are authored exercises run through
the project's ordinary local-model quiz and contribution workflows, not evidence of
real learners or independent validation of the generated source graphs.

- [Maya Chen](Maya_Chen.md): strong generalist.
- [Noah Patel](Noah_Patel.md): struggling beginner.
- [Elena Morales](Elena_Morales.md): specialist in neurons and glia.

The interface displays their normal names and saved histories. Profile descriptions
and fictional origin belong here and in `metadata.json`, not beside their names in
the roster. The intended profiles do not guarantee particular model grades.

Final exercise totals: **3 students, 18 sessions, 30 graded answers and 3 unresolved
submissions**. Those technical failures prevented the next question in their sessions;
no replacement answers or synthetic grades were inserted. Contribution processing
completed for 27 answers and needs technical review for 3. Candidate decisions are
5 accepted, 13 duplicate, 22 needing review, 2 rejected and 1 still pending within
an interrupted contribution job.

One accepted contribution is incorrect: Elena's assertion that self-attention is a
person supervising a transformer. Both model reviews treated it as a metaphor and
accepted it. The original source defines self-attention as a text-processing mechanism.
The outcome is preserved and flagged in Elena's document; the attributed overlay
remains visible, but the relationship has no professor approval for quiz use.
Do not treat accepted contributions as independently verified facts.

## Protocol

The initial and follow-up rounds use the three existing saved source topics. Each
session is capped at two questions for this exercise through the existing round-size
setting; production defaults, progress selection, grading weights and mastery rules
are unchanged. No randomization, question-bank substitution, direct grade insertion,
mastery insertion or professor grading correction is used in these student records.

Initial-round responses were authored from the displayed question and requested help.
Before the follow-up, the user requested the targeted graph relationship as the
reference. Follow-up responses use its meaning, direction, qualifications and the
student profile. The authoring view exposes relationship fields but excludes hidden
expected answers and grading criteria. No internet research is used.

Each answer is saved as authored. Successful grades are never rerun. Technical failures
retain the original request ID and answer, with two HTTP attempts maximum. Two early
grading failures received one additional, explicitly recorded technical retry after
the validation diagnostic was clarified to list required and returned criterion indices.
The validation rule was not relaxed, missing indices were not filled automatically,
and unsuccessful retries remain pending with no grade. Model-internal validation
retries retain the existing bounded configuration.

Contribution extraction and review run independently of grades. Actual duplicate,
rejected, uncertain and accepted decisions are retained. An accepted contribution
does not directly earn mastery or become quiz material without professor approval.
The model's factual review is not external verification. Some proposed additions are
disconnected from the graph or receive disagreeing reviews and remain pending human
review; no acceptance rate is targeted.

## Records

`metadata.json` contains the fictional origin, student IDs, profiles, source IDs,
backup location, original graph hashes, exact API request receipts, technical failures,
and metric snapshots before and after each round. `answers_r*.json` contains the
authored answers. The three readable documents include actual questions, answers,
help, outcomes, contributions, metric changes and limitations.

The original roster was backed up using SQLite's consistent backup operation before
replacement. The backup is in the root `archive/databases/student_profiles_*` folder.
It contained three students and no sessions, answers, contribution records or published
student overlays. Source graphs, source registrations and professor fact approvals
were retained. Generated `artifacts/graph.json` files are checked against their original
hashes. New student additions, if accepted, use the ordinary reversible manual-graph
sidecar and keep student/answer attribution.

Administrative checks use separate fixture databases. They cover persistence,
student ownership, pending-answer replay without duplicates, independently mastered
fact exclusion, explicit review, professor corrections, contribution approval,
rejection and undo. They do not change these students' natural outcomes.

Verification passed: 51 focused unit checks, the isolated professor browser workflow,
the contribution browser workflow, and fresh-app checks against these actual records.
The final browser capture has no JavaScript errors or horizontal overflow at 390px.
`verification.json` records the saved-data checks; screenshots are under `interface/`.
Administrative evidence is under
`archive/maintenance/2026-11-26/professor-refresh/administrative-verification.json`.

## Reproduce reports and verify saved state

From the project root:

```powershell
& .\.venv\Scripts\python.exe tools/export_student_profiles.py
& .\.venv\Scripts\python.exe tools/verify_student_profiles.py --browser
```

These commands read the existing outcomes. Verification replays one already completed
idempotent receipt and asserts that no answer, grade or mastery changes. Browser
captures use the normal professor views. Generating more answers requires explicit
authored input to `tools/populate_student_profiles.py`; reports do not invent results.
