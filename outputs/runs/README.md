# Retained graph generations

The active library contains one graph for each of the three inputs run on
November 25, 2026. Times below are America/Toronto. All three saved results retain
their original `completed_with_issues` status; graph availability does not mean
all extraction, debate, or evaluation checks passed.

| Input | Saved run | Execution time |
| --- | --- | --- |
| `data/ai_test.txt` | [AI test](ai-test/run_20261125_130636_UTC-0500_bd046a0c/index.html) | November 25, 1:06 PM–1:58 PM |
| `data/llm_tuning.txt` | [LLM tuning](llm-tuning/run_20261125_034536_UTC-0500_9e4db7ab/index.html) | Original 3:45 AM–8:12 AM; recovery 10:35 AM–12:32 PM |
| `data/neurons_and_glia.txt` | [Neurons and glia](neurons-and-glia/run_20261125_180507_UTC-0500_585a42c3/index.html) | November 25, 6:05 PM–11:06 PM |

LLM tuning is one logical run with two execution segments. Its combined
`events.jsonl` preserves every original event payload and timestamp, with unique
event IDs and a `source_event` mapping to the original records. Its manifest,
statistics, and report identify the consolidation; the original failure and
incomplete evaluation remain in the preserved history. A separate full-document
evaluation completed on November 26, producing a document score of **45.70/100**.
The six chunk results, their **52.76/100** average, and the graph content were
preserved. Earlier extraction and debate issues still make the overall run
`completed_with_issues`. See [evaluation results](llm-tuning/run_20261125_034536_UTC-0500_9e4db7ab/artifacts/evaluation.json)
and [execution segments](llm-tuning/run_20261125_034536_UTC-0500_9e4db7ab/artifacts/execution_segments.json).

The active professor database is `outputs/professor/students.sqlite3` and contains
these same three graphs. Open it without rerunning inference:

```powershell
& .\.venv\Scripts\python.exe -m pipeline.professor --runs-root outputs/runs --database outputs/professor/students.sqlite3
```

Older runs, the unmodified LLM execution records, and the database snapshot are
in the root [archive](../../archive/README.md).
