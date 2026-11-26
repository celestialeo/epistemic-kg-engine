# Project archive

This is the single archive root for the project. Archived content is excluded
from the active run library, which is scanned under `outputs/runs`.

| Folder | Contents |
| --- | --- |
| `inputs/` | Other input documents, validation fixtures, and the previous input catalog. |
| `runs/` | Superseded runs, preserving their paths relative to the former `outputs/runs/`. |
| `outputs/` | Historical diagnostics, replay runs, demo/test outputs, exports, logs, and the former output archives. |
| `databases/2026-11-26/` | Verified pre-cleanup SQLite snapshot containing all nine registered graphs and their student history. |
| `logs/` | Archived root-level logs. |
| `maintenance/2026-11-26/` | Selection record, move plan and ledger, consolidation script, verification report, and copies of edited files before cleanup. |

The active inputs are AI test, LLM tuning, and neurons and glia. Their latest
November 25 generations remain in [outputs/runs](../outputs/runs/README.md).
The SQLite library retains these three graphs and the existing student identities.
The five sessions, fifteen answers, and related records tied to older graphs are
preserved in the database snapshot, not assigned to newer graph generations.

LLM tuning's original and recovery runs remain unchanged under
`runs/llm-tuning/custom/run_20261125_034536_UTC-0500_9e4db7ab/` and
`runs/llm-tuning/recoveries/recovery_20261125_153513_1d4712cf/`.
The active copy consolidates their timeline without hiding the interruption or
changing the final graph's scientific content or incomplete evaluation status.

Former `data/archive` files now live in `inputs/`. The former `outputs/archive`
subfolders (`runs-cleanup-20261122`, `ai-test-reference-fix-20261122`, and
`student_database_20261122_203835`) now live in `outputs/`. Saved manifests and logs
inside the archive retain their original historical paths.

Use this root for future archives, separating inputs, runs, databases, and other
generated outputs. To restore a moved item, consult the maintenance move ledger
and move its destination back to its original source after checking for conflicts.
To inspect old student history, use a copy of the archived SQLite database.
Retain its paired archived run directories for manual graph edit history.
