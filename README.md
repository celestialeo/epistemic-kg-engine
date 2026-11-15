# ECSE 679 — Epistemic Knowledge Graph Engine

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

Questions carry a shared, reviewed assessment specification. New quizzes use scoped,
question-aware semantic grading: clear paraphrases, pronouns and short contextual
answers count without requiring the graph's exact wording. Criterion checks and
verbatim learner evidence govern green/yellow/red states; unrelated answers do not
earn credit. Older questions retain their whole-graph matching/retry workflow. Correct
component answers do not establish full-relationship mastery. Background facts
require professor approval under Run Insights before quiz use. See the workflow
documentation for evidence requirements, corrections and unresolved retries.

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
python run_pipeline.py --chapter both --no-open --no-explorer

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
`--stage` or extraction-only CLI. `--resume` revalidates matching cached responses and
makes new model calls on misses; it does not skip to an arbitrary checkpoint.
`--no-open` alone does not disable the server. The normal full terminal command still
launches the combined dashboard unless `--no-explorer` is specified.

Background replay requires saved chunks, reviewed extractions, chapter outline,
concepts, reconciliation, relations and source paragraphs/text. It writes a separate
background experiment and leaves its source intact; it does not run reconstruction or
produce a complete full-run report. Evaluation requires a completed/partial-completed
manifest, graph, chunks, paragraphs, debate, input, statistics and prior report files.
It updates evaluation/report outputs while preserving the graph and original event log.
Existing evaluation trace/provenance behavior is retained.

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
