# Epistemic Knowledge Graph Engine

Run a complete pipeline from chunked text to a knowledge graph, background
knowledge enrichment, and evaluation reports. When the run finishes, open the
**Pipeline results** page to read the reports and explore the **interactive HTML
graph** in your browser.

## Project documentation

This README covers running the project and opening its results. For how it works,
read the **[project overview, file diagrams, and terminology](docs/project-overview.md)**.

For evidence checking, paired statistics, and before/after graphs, see the
**[FActScore comparison guide](docs/factscore-comparison.md)**. The existing pipeline
remains the baseline. Compare a completed run without Neo4j using
`--compare-factscore RUN_ID`; add `--factscore-reference data/references.json` for
external passage evidence, or omit it for an explicitly labeled input-document
support check. Start with `--factscore-limit 2 --factscore-edge-limit 2` for a pilot.

**Open graphs and reports together:**
`& .\.venv\Scripts\python.exe .\run_pipeline_beforevsafter.py`
opens the latest saved dashboard. To generate a full comparison, use
`run_pipeline_beforevsafter.py --run RUN_ID`.
See the **[step-by-step before/after viewing guide](docs/beforevsafter.md)**.

The project tests how well a graph preserves the meaning of source text, and
whether adding model-generated background knowledge helps reconstruct that text.

```mermaid
flowchart TD
    entry["run_pipeline.py"] --> cli["pipeline/cli.py: run and coordinate"]
    plan["pipeline/plan.py: ordered stages"] --> cli
    input["data/chunks.json"] --> cli
    cli --> stages["src/: extract, load, enrich, evaluate"]
    stages <--> services["Ollama models and Neo4j database"]
    stages --> saved["outputs/runs/run-id/: saved JSON and reports"]
    saved --> view["pipeline/graph_view.py + graph_view.html"]
    view --> graph["knowledge_graph.html"]
    cli --> results["index.html: Pipeline results"]
    results -. "links to" .-> graph
    results -. "links to" .-> reports["HTML fidelity reports"]
```

Arrows show calls or data flow; dotted arrows are browser links. The
[detailed diagrams](docs/project-overview.md#how-the-files-work-together) separate
these responsibilities and show the individual scripts. Mermaid diagrams render
on GitHub and in Markdown previews with Mermaid support.

## Run the pipeline

If this is your first time using the project, complete the [one-time setup](#one-time-setup)
below. After that, use these steps each time, including after restarting your laptop.

1. Open **Docker Desktop** and wait until its engine is running.
2. Open **Ollama** and leave it running.
3. Open PowerShell or your IDE terminal and run:

```powershell
cd C:\Users\miche\Documents\epistemic-kg-engine
& .\.venv\Scripts\python.exe .\run_pipeline.py --new --start-neo4j
```

Copy the commands inside the code block, without adding a `PS C:\...>` terminal
prompt. The command uses the project's Python directly; no environment activation
is needed. `--new` starts immediately without a menu, and `--start-neo4j` starts
the bundled database container once Docker Desktop is ready.

The pipeline processes **all chunks in `data/chunks.json`**. It extracts concepts
and relations, loads the graph, adds background knowledge, evaluates the results,
and generates HTML reports and the interactive graph. Progress appears in the
terminal, and each execution saves a new run in `outputs/runs/`.

### Try a smaller complete run

To test the full workflow with the first five chunks and up to three background
seed concepts, use:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --new --start-neo4j --limit 5 --seed-limit 3
```

This includes background enrichment, evaluation, the results page, and the HTML
graph. Docker Desktop and Ollama must be running, just as for the full run.

## Open the pipeline results

When the run finishes, the **results page** and **interactive graph** open in your
browser. On the results page:

- Click **Explore the interactive knowledge graph** to view the graph in HTML.
- Click **Open graph in Neo4j Browser** to explore the live database using the commands below.
- Open the **Fidelity reports** to inspect the evaluation results.
- Open the **Run manifest** to see the run settings and status.

You can return to the results later by opening `index.html` in the run's folder.
The HTML graph and reports work without starting Neo4j or Ollama after they have
been generated. Neo4j is used during pipeline execution; viewing the HTML graph
requires only your browser.

Each run saves these files under `outputs/runs/<run-id>/`:

| File | Purpose |
| --- | --- |
| `index.html` | Main results page with links to the graph and reports |
| `knowledge_graph.html` | Interactive graph with names, colors, and explanations |
| `concepts_only.html` | Fidelity report using concept hints |
| `document.html` | Fidelity report including document relations |
| `with_background.html` | Fidelity report including background knowledge |
| `manifest.json` | Run settings and status |
| `logs/` | Output from each pipeline stage |

The report files are generated when their corresponding evaluation stages run.
In File Explorer, open `outputs`, then `runs`, then your run's folder, and
double-click `index.html` or `knowledge_graph.html`.

## View the graph in Neo4j Browser

From the results page, click **Open graph in Neo4j Browser**, or open
[localhost:7474/browser](http://localhost:7474/browser/). Keep Neo4j running and
log in with the credentials from `.env`.

**Run the following blocks in Neo4j Browser's command editor, not PowerShell.**
Run each block separately with **Ctrl+Enter**.

### 1. Identify background concepts

Run this after loading a new run or restoring an old one. It refreshes the
`BackgroundConcept` visualization label using the stored background origin and
absence of document links. It changes labels, not the saved HTML graph.

```cypher
MATCH (c:Concept)
REMOVE c:BackgroundConcept
WITH c
WHERE c.source IN ['background', 'document+background']
  AND NOT EXISTS {
    MATCH (:Chunk)-[:MENTIONS]->(c)
  }
  AND NOT EXISTS {
    MATCH (:KnowledgeUnit)-[:MENTIONS|DEFINES|PART_OF|CAUSES]->(c)
  }
SET c:BackgroundConcept
RETURN count(c) AS background_concepts;
```

### 2. Apply names and colors

Paste this whole block as one Browser command:

```text
:style {
  "node.BackgroundConcept": {"color": "#CF681B", "caption": "{label}"},
  "node.BackgroundFact": {"color": "#CF681B", "caption": "{text}"},
  "node.Chunk": {"color": "#60758A", "caption": "{text}"},
  "node.KnowledgeUnit": {"color": "#2877CC", "caption": "{text}"},
  "node.Concept": {"color": "#2877CC", "caption": "{label}"}
}
```

| Color | Neo4j nodes |
| --- | --- |
| Blue | Document concepts and extracted statements |
| Orange | Background-only concepts and background facts |
| Gray | Source chunks |

Concepts display their names, while chunks, statements, and background facts
use their text. Click a node to read its full properties, including scores.

Neo4j uses the first label's style when a node has multiple labels. In the result's
label overview, put **BackgroundConcept above Concept**, and put **Entity below
all the labels above** if colors or captions are wrong. These Browser settings
are separate from the HTML graph's automatic styling.
[Neo4j styling reference](https://neo4j.com/docs/browser/operations/browser-styling/).

### 3. Show the graph

The results page's Neo4j link prefills a query starting from that run's chunks.
Run it and select the **Graph** result view. To browse a sample of the entire
live database instead, run:

```cypher
MATCH p=(n)-[r]->(m)
RETURN p
LIMIT 200;
```

To explore a named concept, replace `neuron` below with the concept you want:

```cypher
MATCH (c:Concept)
WHERE toLower(coalesce(c.label, c.id)) = 'neuron'
OPTIONAL MATCH p=(c)-[r]-(neighbor)
RETURN c, p
LIMIT 200;
```

Double-click nodes to expand their neighbors. These queries show at most 200
rows, and the live database can contain multiple runs. Concepts and background
relationships are shared across runs; the HTML graph provides the saved view
for one run. The Neo4j colors above identify nodes, not relationship origin.

## Explore the HTML graph

The graph starts with one concept and its neighbors so the names are readable.
Click **Show all** to see the full graph with the current filters.

| Color | Meaning |
| --- | --- |
| Blue | Knowledge extracted from the document |
| Orange | Generated background additions |
| Purple | A document concept also used in background knowledge |
| Gray | An original source chunk |

Concepts display their names, and statements display source-text previews. Click
a node to inspect its full details. Click an orange relationship to read its
background explanation and score. Scores appear in the details, not as node names.
Colors identify origin, not correctness.

- **Search** for a concept to see matches and their neighbors.
- Uncheck **Background** to view document knowledge on its own.
- Check **Source chunks** to include the original text chunks.
- Select a node and click **Focus on selected** to explore its neighborhood.
- Drag nodes to arrange them, drag empty space to pan, and scroll to zoom.

The graph is a self-contained HTML file built from that run's saved data. It uses
no external scripts or live database connection. The results page also provides
an optional Neo4j Browser link for exploring the live database, which requires
Neo4j to be running.

## Revisit a previous run

New runs generate the HTML graph automatically. To generate or refresh the HTML
graph for a previous run, using its saved files:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --view-run --graph-only
```

The terminal lists saved runs and asks `Choose a run:`. Type the number beside
your run and press **Enter**. Its graph opens without starting services or
repeating extraction, model calls, or evaluation. Existing HTML files update
when regenerated; they do not update themselves.

To list saved runs and find their folders:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --list-runs
```

Open the chosen folder's `index.html` to revisit its reports as well.

## One-time setup

<details>
<summary>Expand installation and configuration steps</summary>

Skip this if the pipeline already runs on your laptop. Restarting your laptop
does not require reinstalling dependencies or downloading models again.

Install Python 3.10+ (3.11 recommended), Ollama, and Docker Desktop for the bundled
Neo4j setup. From the project folder in PowerShell:

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Set `NEO4J_PASSWORD` in `.env` to your database password and save the file. Keep
an existing working configuration. Changing `.env` does not change the password
stored in an existing Neo4j database.

Open Ollama, then download the default models once:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

You are now ready to [run the pipeline](#run-the-pipeline). If you use your own
running Neo4j server, configure its connection in `.env` and omit `--start-neo4j`.
On macOS/Linux, create the environment with `python3.11 -m venv .venv` and use
`.venv/bin/python` instead of the PowerShell Python prefix.

</details>

## More run commands

Run these in **PowerShell**, from the project folder.

**Restore an existing run and open its results** (Docker Desktop/Neo4j required;
Ollama is not needed). Choose a run number when prompted:

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --view-run --start-neo4j
```

**Use your own input file:**

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --new --start-neo4j --input .\data\my_chunks.json
```

**Preview the steps without services or model calls:**

```powershell
& .\.venv\Scripts\python.exe .\run_pipeline.py --dry-run
```

Add `--no-open` to save results without opening browser windows. Use `--help`
for all options. Omit `--new` from the main run command to choose between **New
run** and **Display existing run** in the terminal menu.

## If something fails

| Message or symptom | What to do |
| --- | --- |
| `Neo4j preflight failed` | Open Docker Desktop, wait until it is ready, and retry with `--start-neo4j`. If Neo4j is already running, check its connection settings and password in `.env`. |
| Docker engine unavailable | Start Docker Desktop; `--start-neo4j` starts the container, not Docker Desktop itself. |
| `Ollama preflight failed` | Open Ollama and download both models from the setup section. |
| Python executable not found | Check that you are in the project folder and have completed the virtual environment setup. |
| Browser does not open | Open the printed run folder and double-click `index.html`. |
| Graph is crowded | Search for a concept or use **Focus on selected**. |

## Input and run notes

The default input is `data/chunks.json`. Custom input files use this format:

```json
{"chunks": [{"chunk_id": "lesson_001", "text": "A neuron transmits signals."}]}
```

Chunk IDs must be unique, nonempty strings, and text must be nonempty. Input must
already be chunked; this pipeline does not ingest PDFs. `--limit 0` processes all
chunks; `--seed-limit` defaults to 20.

Generated outputs are excluded from Git. Runs stop on stage errors; inspect the
run's `logs/` folder and retry after fixing the cause. Completed Neo4j writes are
not rolled back, and existing graph data is not cleared. For controlled experiments,
use a separate clean database and avoid concurrent runs against the same database.

The concepts-only evaluation still uses predicates and anchor phrases but omits
relation and background hints. Metadata/noise copied verbatim are excluded from
hypothesis tests but remain included in report aggregates.
