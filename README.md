# Epistemic Knowledge Graph Engine

Run an offline pipeline from chunked text to a Neo4j knowledge graph, background
knowledge enrichment, fidelity evaluation, and HTML reports. Models run in Ollama.

## Setup

Requires Python 3.10+ (3.11 recommended), Ollama, and Neo4j. Install Docker Desktop
if you want the runner to start Neo4j for you.

In PowerShell, from this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Keep an existing `.env` instead of overwriting it. Edit `.env` and set
`NEO4J_PASSWORD` to your database password. Start Ollama and download the models:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

On macOS/Linux, use `python3.11 -m venv .venv` and `.venv/bin/python` instead.

## Run

Start Docker Desktop, then:

```powershell
.\.venv\Scripts\python.exe run_pipeline.py --start-neo4j
```

Omit `--start-neo4j` when Neo4j is already running. Docker uses local ports 7474
and 7687 and persistent volumes. Changing `.env` does not change the password in
an existing database.

The runner extracts concepts and relations, loads the document graph, enriches
chunks, evaluates reconstruction, expands and scores background knowledge, loads
approved background edges, and generates comparisons, statistical tests, and reports.

At completion, it opens a results page and Neo4j Browser with the graph query
prefilled. **Log in, press Play / Ctrl+Enter, and select the Graph result view**
to display nodes and relationships. Double-click nodes to expand their neighbors.
The initial query is limited to 200 rows.

Other commands, using your virtual environment's Python:

```powershell
python run_pipeline.py --dry-run
python run_pipeline.py --limit 5 --seed-limit 3
python run_pipeline.py --input path/to/chunks.json
python run_pipeline.py --skip-background --skip-evaluation
python run_pipeline.py --no-open
python run_pipeline.py --help
```

## Files

```text
run_pipeline.py       Entry point
pipeline/            Stage definitions, execution, configuration, results page
src/                 Scripts used by the pipeline
data/chunks.json      Default sample input
requirements.txt     Runtime dependencies
compose.yaml         Persistent local Neo4j service
.env.example         Configuration template
```

The default input is `data/chunks.json`. Custom inputs use this format:

```json
{"chunks": [{"chunk_id": "lesson_001", "text": "A neuron transmits signals."}]}
```

Chunk IDs must be unique strings and text must be nonempty. Input must already
be chunked; this pipeline does not ingest PDFs. `--limit 0` processes all chunks;
`--seed-limit` defaults to 20.

## Results and run boundaries

Generated files go to `outputs/runs/<run-id>/`, which is excluded from Git.
Each run includes its input snapshot, JSON artifacts, HTML fidelity reports,
`index.html`, `graph.cypher`, per-step logs, and a status manifest.

Runs get unique chunk IDs and stop on stage or extraction errors. Completed
Neo4j writes are not rolled back. Retry in a new output directory after fixing
an error. The runner does not delete existing graph data. Concepts and background
edges are shared across runs: use a separate clean Neo4j instance/database for
controlled experiments, and avoid concurrent runs against the same database.

The concepts-only condition still uses predicates and anchor phrases; it omits
relation and background hints. Metadata/noise copied verbatim are excluded from
hypothesis tests but remain included in report aggregates.
