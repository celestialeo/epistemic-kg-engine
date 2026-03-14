# Offline Knowledge Graph Demo (LangChain + Ollama + Neo4j)

This project turns raw chunked text into a structured knowledge graph that we can explore and retrieve from locally, without relying on external APIs. In practice, it uses an offline LLM pipeline to extract concepts and relations, loads them into Neo4j, and then tests whether the extracted representation is actually good enough to preserve meaning for retrieval and navigation.

At a high level, the repo is about more than “building a graph.” It is also about evaluating whether the graph-friendly representation is useful for information retrieval, semantic organization, and explainable exploration of text.

This repo demonstrates an end-to-end offline pipeline:

`chunked text -> LLM extraction -> graph artifacts -> Neo4j load -> retrieval`

Goal: convert raw chunked text into a concept-linked graph for concept-centric navigation and retrieval.

## Why I Built This

I built this project to explore how unstructured text can be transformed into a more queryable and explainable knowledge representation. Instead of relying only on keyword search, the goal is to organize chunks around concepts, semantic links, and epistemic roles so retrieval can become easier to interpret and more useful for downstream analysis.

This also supports a core information science question: when we compress text into extracted concepts and relations, are we preserving enough meaning for later retrieval? The reconstruction-validation step in this repo is my way of testing that directly rather than assuming that a plausible-looking graph is automatically a good representation.

## Architecture Overview

```text
chunked JSON
    |
    v
LangChain + Ollama extraction
    |
    +--> knowledge-unit metadata
    |      (unit_kind, layer, confidence, concepts)
    |
    +--> optional epistemic relations
    |      (DEFINES, PART_OF, CAUSES)
    |
    v
graph artifacts
    |
    +--> deduplicated concepts
    +--> chunk-to-concept mention edges
    +--> chunk ordering edges
    |
    v
Neo4j graph
    |
    +--> concept-based retrieval
    +--> neighborhood exploration
    +--> graph QA
    |
    v
reconstruction validation
    |
    +--> reconstruct chunk from extracted knowledge
    +--> compare original vs reconstructed meaning
```

## What Gets Built in Neo4j

Core mode builds:
- `(:Chunk)` nodes
- `(:Concept)` nodes
- `(:Chunk)-[:MENTIONS]->(:Concept)` edges
- `(:Chunk)-[:NEXT]->(:Chunk)` edges

Optional extensions can also add:
- `(:KnowledgeUnit)` nodes
- `[:DEFINES]`, `[:PART_OF]`, `[:CAUSES]` edges

## Repository Entry Point

Pipeline input is chunked JSON in `outputs/` with this structure:

```json
{
  "chunks": [
    { "chunk_id": "...", "text": "..." }
  ]
}
```

## Folder Overview

- `src/`: extraction scripts, graph artifact builders, Neo4j loaders, retrieval scripts
- `outputs/`: sample datasets and generated artifacts
- `schema/`: schema reference (`graph_schema.yaml`)

## Prerequisites

1. Python 3.10+
2. Ollama installed and running locally
3. Docker (for local Neo4j)

## Install Ollama

Official installer: `https://ollama.com/download`

macOS:

```bash
brew install ollama
brew services start ollama
```

Linux:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve
```

Windows:
- Install from `https://ollama.com/download`
- Open Ollama once to start the local service

Pull a local model:

```bash
ollama pull llama3.2:3b
```

Verify:

```bash
ollama run llama3.2:3b "Say hi"
```

Optional Ollama environment variable:

```bash
export OLLAMA_HOST="http://127.0.0.1:11434"
```

Example `.env` values:

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=test12345
NEO4J_DB=neo4j
OLLAMA_HOST=http://127.0.0.1:11434
```

## Setup

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

Windows Git Bash:

```bash
py -m venv .venv
source .venv/Scripts/activate
python -m pip install -U pip
pip install -r requirements.txt
```

## Demo Run (testpack)

### Step 1: Generate structured extractions (LangChain + Ollama)

Input:
- `outputs/testpack_v1_chunks.json`

Output:
- `outputs/testpack_v1_extractions.json`

Run:

```bash
python -u src/langchain_extract_knowledgeunits.py \
  --in outputs/testpack_v1_chunks.json \
  --out outputs/testpack_v1_extractions.json \
  --model llama3.2:3b
```

Optional chunk limit:

```bash
python -u src/langchain_extract_knowledgeunits.py \
  --in outputs/testpack_v1_chunks.json \
  --out outputs/testpack_v1_extractions.json \
  --model llama3.2:3b \
  --limit 20
```

Verify:

```bash
python -c "import json; d=json.load(open('outputs/testpack_v1_extractions.json')); print('rows', len(d['extractions']), 'errors', sum('error' in r for r in d['extractions']))"
```

### Step 2: Build graph artifacts (deduplicated concepts + mention edges)

Input:
- `outputs/testpack_v1_extractions.json`

Outputs:
- `outputs/testpack_v1_concepts_dedup.json`
- `outputs/testpack_v1_mentions.json`

Run:

```bash
python -u src/build_mentions_from_extractions.py \
  --in outputs/testpack_v1_extractions.json \
  --concepts-out outputs/testpack_v1_concepts_dedup.json \
  --mentions-out outputs/testpack_v1_mentions.json
```

Verify:

```bash
python -c "import json; m=json.load(open('outputs/testpack_v1_mentions.json'))['mentions']; c=json.load(open('outputs/testpack_v1_concepts_dedup.json'))['concepts']; print('concepts', len(c), 'edges', len(m)); print('sample_edge', m[:2])"
```

### Step 3: Start Neo4j (Docker)

```bash
docker rm -f neo4j 2>/dev/null || true
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/test12345 \
  neo4j:5
```

Neo4j Browser:
- `http://localhost:7474`
- username/password: `neo4j` / `test12345`

### Step 4: Set Neo4j environment variables

macOS/Linux:

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="test12345"
export NEO4J_DB="neo4j"
```

Windows PowerShell:

```powershell
setx NEO4J_URI "bolt://localhost:7687"
setx NEO4J_USER "neo4j"
setx NEO4J_PASSWORD "test12345"
setx NEO4J_DB "neo4j"
```

Windows Git Bash:

```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="test12345"
export NEO4J_DB="neo4j"
```

### Step 5: Load graph into Neo4j

Load `Chunk` nodes + `NEXT` edges:

```bash
python -u src/load_chunks_to_neo4j.py \
  --chunks outputs/testpack_v1_chunks.json \
  --source-type testpack
```

Load `Concept` nodes:

```bash
python -u src/load_concepts_to_neo4j.py \
  --concepts outputs/testpack_v1_concepts_dedup.json \
  --source-type testpack
```

Load `MENTIONS` edges:

```bash
python -u src/load_mentions_to_neo4j.py \
  --mentions outputs/testpack_v1_mentions.json
```

## Validate in Neo4j (Cypher)

Counts:

```cypher
MATCH (ch:Chunk) RETURN count(ch) AS chunks;
MATCH (c:Concept) RETURN count(c) AS concepts;
MATCH (:Chunk)-[:MENTIONS]->(:Concept) RETURN count(*) AS mention_edges;
MATCH ()-[r:NEXT]->() RETURN count(r) AS next_edges;
```

Graph view:

```cypher
MATCH (ch:Chunk)-[:MENTIONS]->(c:Concept)
RETURN ch, c
LIMIT 50;
```

Relationship audit:

```cypher
MATCH ()-[r]->()
RETURN type(r) AS rel, count(*) AS n
ORDER BY n DESC;
```

## Retrieval Demo (No Cypher Needed)

```bash
python -u src/retrieve_core_by_concept.py --concept neuron --limit 5
```

Example retrieval output:

```text
Concept: neuron

1. Definition
   chunk_id: tp_0000
   text: A neuron is an excitable cell that processes and transmits information using electrical and chemical signals.

2. Support
   chunk_id: tp_0003
   text: Myelination increases conduction speed through saltatory conduction between nodes of Ranvier.
```

If you want to make this README more presentation-ready later, this is also a good place to add:
- a screenshot of the Neo4j Browser concept neighborhood view
- a screenshot of retrieval output for a concept such as `neuron`

## Optional: Epistemic Relations Extension

Extract `DEFINES`, `PART_OF`, and `CAUSES`:

```bash
python -u src/extract_epistemic_relations.py \
  --in outputs/testpack_v1_extractions.json \
  --out outputs/testpack_v1_relations.json \
  --model llama3.2:3b
```

Load those relations:

```bash
python -u src/load_epistemic_relations_to_neo4j.py \
  --relations outputs/testpack_v1_relations.json \
  --source-type testpack
```

Optional: load explicit `KnowledgeUnit` nodes:

```bash
python -u src/load_kus_to_neo4j.py \
  --extractions outputs/testpack_v1_extractions.json \
  --source-type testpack
```

## Reconstruction Validation Demo

This is an evaluation step for the extraction pipeline, not a graph-loading step.

Purpose:
- test whether compressed knowledge is sufficient to recover the meaning of the original chunk
- compare `concepts only` against `concepts + relations`
- use semantic similarity as a validation signal for extraction quality

Current validator:
- `src/compresses_knowlege_reconstruction.py`
- reconstructs chunk text from extracted concepts and optional relations
- scores `original` vs `reconstructed` with lexical overlap and embedding cosine

### Run baseline reconstruction

Input:
- `outputs/testpack_v1_extractions.json`

Output:
- `outputs/testpack_v1_reconstruction.json`

```bash
python -u src/compresses_knowlege_reconstruction.py \
  --extractions outputs/testpack_v1_extractions.json \
  --out outputs/testpack_v1_reconstruction.json \
  --model llama3.2:3b
```

### Run relation-aware reconstruction

Inputs:
- `outputs/testpack_v1_extractions.json`
- `outputs/testpack_v1_relations.json`

Output:
- `outputs/testpack_v1_reconstruction_with_relations.json`

```bash
python -u src/compresses_knowlege_reconstruction.py \
  --extractions outputs/testpack_v1_extractions.json \
  --relations outputs/testpack_v1_relations.json \
  --out outputs/testpack_v1_reconstruction_with_relations.json \
  --model llama3.2:3b
```

### Compare the two runs

This prints:
- average embedding similarity
- average lexical score
- pass rate at a chosen threshold
- chunk-level improvements
- a few demo-friendly cases to inspect manually

```bash
python -u src/compare_reconstruction_runs.py \
  --baseline outputs/testpack_v1_reconstruction.json \
  --candidate outputs/testpack_v1_reconstruction_with_relations.json \
  --threshold 0.70
```

### How to interpret the outputs

- `embedding_cosine`: the main semantic score; higher means the reconstruction is closer in meaning to the original
- `lexical_combined`: a secondary diagnostic based on word overlap
- `pass`: whether `embedding_cosine >= threshold`

Recommended demo framing:
1. Extract concepts from chunk text.
2. Optionally extract relations.
3. Reconstruct the chunk from the compressed representation.
4. Compare reconstruction to the original chunk.
5. Show whether relations help preserve meaning.

Recommended speaking point:
- this evaluation loop helps distinguish "the extraction looks plausible" from "the extraction preserves enough meaning to be useful downstream"

## Suggested Demo Order

If you want one clean show-and-tell path, run these in order from the project root:

```bash
source .venv/bin/activate
python -u src/langchain_extract_knowledgeunits.py \
  --in outputs/testpack_v1_chunks.json \
  --out outputs/testpack_v1_extractions.json \
  --model llama3.2:3b

python -u src/extract_epistemic_relations.py \
  --in outputs/testpack_v1_extractions.json \
  --out outputs/testpack_v1_relations.json \
  --model llama3.2:3b

python -u src/compresses_knowlege_reconstruction.py \
  --extractions outputs/testpack_v1_extractions.json \
  --out outputs/testpack_v1_reconstruction.json \
  --model llama3.2:3b

python -u src/compresses_knowlege_reconstruction.py \
  --extractions outputs/testpack_v1_extractions.json \
  --relations outputs/testpack_v1_relations.json \
  --out outputs/testpack_v1_reconstruction_with_relations.json \
  --model llama3.2:3b

python -u src/compare_reconstruction_runs.py \
  --baseline outputs/testpack_v1_reconstruction.json \
  --candidate outputs/testpack_v1_reconstruction_with_relations.json \
  --threshold 0.70
```

Notes:
- run all commands from the repo root: `/home/miggy/Practicum Project- 2026`
- Ollama must be running locally before these steps
- the reconstruction scripts call the local Ollama chat model and embedding endpoint
- `0.70` is a working demo threshold, not a final tuned threshold
- for a faster smoke test, add `--limit 5` to the extraction or reconstruction commands

### Quick sanity checks

Check extraction output:

```bash
python -c "import json; d=json.load(open('outputs/testpack_v1_extractions.json')); print('rows', len(d['extractions']), 'errors', sum('error' in r for r in d['extractions']))"
```

Check relation output:

```bash
python -c "import json; d=json.load(open('outputs/testpack_v1_relations.json')); print('rows', len(d['relations']), 'errors', sum('error' in r for r in d['relations']))"
```

Check reconstruction summaries:

```bash
python -c "import json; print(json.load(open('outputs/testpack_v1_reconstruction.json'))['summary'])"
python -c "import json; print(json.load(open('outputs/testpack_v1_reconstruction_with_relations.json'))['summary'])"
```

## Troubleshooting

1. Check active DB and relationship types:

```bash
python - <<'PY'
import os
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI", "bolt://localhost:7687"),
    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD"))
)
db = os.getenv("NEO4J_DB", "neo4j")
with driver.session(database=db) as s:
    rels = s.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType").data()
print("DB:", db)
print("REL TYPES:", [r["relationshipType"] for r in rels])
PY
```

2. If retrieval returns nothing, list available concepts:

```cypher
MATCH (c:Concept) RETURN c.id LIMIT 20;
```
