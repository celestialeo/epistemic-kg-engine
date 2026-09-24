# View before/after graphs and reports together

The launcher is `run_pipeline_beforevsafter.py` in the project root.

## 1. Open saved results immediately

From PowerShell in the project folder:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline_beforevsafter.py
```

This opens the latest saved comparison dashboard. No Ollama, Neo4j, or Docker is
needed. It refreshes graph presentation without recomputing scores. The currently
available completed experiment is a **two-chunk, two-edge pilot**. Its page is
clearly labeled PILOT; showing all its nodes does not turn it into a full-run
experiment.

The dashboard has three tabs:

1. **Side-by-side graphs:** all saved nodes, including statements and source
   chunks, start visible. Both panels share positions, search, pan, zoom, and node
   dragging. Red dashed edges were removed; green background edges were retained.
   Select an edge for its evidence decisions. Uncheck statements or source chunks
   to reduce clutter, or search for a concept to inspect its neighborhood.
2. **Before / after reports:** the individual fidelity reports appear side by
   side. Compare the same chunk ID and read its original text, reconstruction,
   hints, and similarity scores. Each pane scrolls independently.
3. **Statistics and what changed:** matched before/after means, changes,
   confidence intervals, p-values, and the full claim/evidence audit.

Links above the tabs open each graph/report in a separate browser tab. The
Markdown document can be opened or saved for sharing. Pipeline results also
links to the dashboard after it has been generated.

## 2. Generate the full comparison

Start **Ollama**. The existing completed baseline already contains the graph
artifacts; you do not need Docker or Neo4j for this comparison.

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline_beforevsafter.py --run run_20260914_174040_72ef4ce6
```

This compares **all 20 saved chunks and all 135 approved background edges** in
that baseline, with no pilot limits. It preserves the baseline, checks background
evidence, reconstructs both versions, computes statistics, and opens the dashboard
when finished. The output is a new experiment folder. The full comparison can
take hours with the current local model; progress prints in the terminal.

By default, the source document supplies evidence. To use a separate reference
collection, create the passage JSON described in the
[FActScore guide](factscore-comparison.md#prepare-reference-evidence), then run:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline_beforevsafter.py --run run_20260914_174040_72ef4ce6 --reference .\data\references.json
```

Optionally add `--verifier MODEL_NAME` for a different installed Ollama verifier.
Generation and embedding models are taken from the saved baseline for both arms.
Do not run the placeholder reference file example without replacing its text
with actual evidence.

## 3. Reopen or choose results

Once the full comparison finishes, the command in step 1 opens it without
repeating model calls. To list available experiments:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline_beforevsafter.py --list
```

To open the latest comparison belonging to a particular baseline:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline_beforevsafter.py --view run_20260914_174040_72ef4ce6
```

`--view` also accepts a comparison ID or its directory path. `--no-open` writes
the dashboard and prints its path without launching a browser.

To resume the full comparison started in this workspace after an interruption:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline_beforevsafter.py --resume compare_20260920_175537_52d2c49f
```

Do not start a second copy while that experiment is running. Resumption reuses
cached successful calls and checks that the baseline, references, scoring code,
and model versions still match. Its dashboard opens when the run finishes.

## How to judge whether the after version is better

Look for fewer unsupported assertions while preserving original claim coverage.
Inspect changed reconstructions, rather than relying on edge removal counts or
embedding similarity alone. Check the number of matched chunks and the uncertainty
around changes. The confidence intervals and tests are exploratory; verifier
errors and dependence between chunks limit the conclusions.

An empty after background graph has undefined background precision, not perfect
precision. The default verifier produced questionable decisions in the
[first pilot](factscore-pilot-results.md), so manually review evidence decisions
before treating automated estimates as factual accuracy. A full comparison means
the full saved dataset was processed; it does not by itself establish statistical
significance or scientific validity.
