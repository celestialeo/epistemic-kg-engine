# Offline Knowledge Graph Demo (LangChain + Ollama + Neo4j)

This repo demonstrates an end-to-end offline pipeline:

`chunked text -> LLM extraction -> graph artifacts -> Neo4j load -> retrieval`

Goal: convert raw chunked text into a concept-linked graph for concept-centric navigation and retrieval.

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
