# Offline Knowledge Graph Demo — LangChain + Ollama → Neo4j (Core Mode)

This repo demonstrates an end-to-end **offline** pipeline:

**chunked text → structured extraction (LLM) → graph artifacts (concepts + mentions) → Neo4j load → graph queries**

The goal is to convert raw text into a **concept-linked graph** so we can retrieve and navigate information by shared concepts.

---

## What gets built in Neo4j

- `(:Chunk)` nodes (one per chunk of text)
- `(:Concept)` nodes (deduplicated concept strings)
- `(:Chunk)-[:MENTIONS]->(:Concept)` edges (chunk mentions a concept)
- `(:Chunk)-[:NEXT]->(:Chunk)` edges (preserve chunk ordering)

---

## Repository entrypoint (important)

This project starts from already-chunked JSON files in `outputs/` with this structure:

```json
{ "chunks": [ { "chunk_id": "...", "text": "..." }, ... ] }

---
```

## Folder Overview
- src/- pipeline scripts(extraction,graph artifacts, Neo4j loaders)
- outputs/- datasets and generated artifacts
- schema/- schema reference(labels,properties,conventions)

## Prerequisties 

# 1. Python 3.10+
# 2. Ollama installed + model available locally
# 3. Docker installed (for Neo4j)

## Verify Ollama
```bash
ollama run llama3.2:3b "Say hi"
```
## Setup

# macOS/Linux
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
```
# Windows Powershell
```bash
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```
# Windows GitBash
```bash
py -m venv .venv
source .venv/Scripts/activate
python -m pip install -U pip
pip install -r requirements.txt
```

## Demo Run(Testpack)

# Step 1- Generate structured extractions (LangChain + Ollama)
# Input- 
- outputs/testpack_v1_chunks.json

# Output-
- outputs/testpack_v1_chunks.json

# Run
```bash
python -u src/langchain_extract_knowledgeunits.py \
  --in outputs/testpack_v1_chunks.json \
  --out outputs/testpack_v1_extractions.json \
  --model llama3.2:3b
  ```
- Optional(Limit Chunks)
```bash
python -u src/langchain_extract_knowledgeunits.py \
  --in outputs/testpack_v1_chunks.json \
  --out outputs/testpack_v1_extractions.json \
  --model llama3.2:3b
```

# Verify
```bash
python -c "import json; d=json.load(open('outputs/testpack_v1_extractions.json')); print('rows', len(d['extractions']), 'errors', sum('error' in r for r in d['extractions']))"
```

# Step 2- Build graph artifacts (dedup concepts + mentions edges)

# Input
- outputs/testpack_v1_extractions.json

# Outputs
- outputs/testpack_v1_concepts_dedup.json
- outputs/testpack_v1_mentions.json

# Run:
```bash
python -u src/build_mentions_from_extractions.py \
  --in outputs/testpack_v1_extractions.json \
  --concepts-out outputs/testpack_v1_concepts_dedup.json \
  --mentions-out outputs/testpack_v1_mentions.json
```

# Verify
```bash
python -c "import json; m=json.load(open('outputs/testpack_v1_mentions.json'))['mentions']; c=json.load(open('outputs/testpack_v1_concepts_dedup.json'))['concepts']; print('concepts', len(c), 'edges', len(m)); print('sample_edge', m[:2])"
```

## Neo4j(Docker)

## Step 3- Start Neo4j

```bash
docker rm -f neo4j 2>/dev/null || true
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/test12345 \
  neo4j:5
```

# Neo4j Browser- 
- http://localhost:7474
- username/password: neo4j / test12345

## Step 4- Set Neo4j environment variables
- The loaders require NEO4J_PASSWORD to be set.

# macOS/Linux
```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="test12345"
```

# Windows (PowerShell):
```bash
setx NEO4J_URI "bolt://localhost:7687"
setx NEO4J_USER "neo4j"
setx NEO4J_PASSWORD "test12345"
# restart terminal after setx
```

# Windows (Git Bash):
```bash
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="test12345"
```

## Load the graph into Neo4j
## Step 5A- Load Chunk nodes + NEXT edges

```bash
python -u src/load_chunks_to_neo4j.py \
  --chunks outputs/testpack_v1_chunks.json \
  --source-type testpack
```
## Step 5B- Load Concept nodes
```bash 
python -u src/load_concepts_to_neo4j.py \
  --concepts outputs/testpack_v1_concepts_dedup.json \
  --source-type testpack
```
## Step 5C- Load MENTIONS edges (Chunk → Concept)
```bash
python -u src/load_mentions_to_neo4j.py \
  --mentions outputs/testpack_v1_mentions.json
```

## Validate in Neo4j (Cypher)

### Counts:
```cypher
MATCH (ch:Chunk) RETURN count(ch) AS chunks;
MATCH (c:Concept) RETURN count(c) AS concepts;
MATCH (:Chunk)-[:MENTIONS]->(:Concept) RETURN count(*) AS mention_edges;
MATCH ()-[r:NEXT]->() RETURN count(r) AS next_edges;
```

### Graph view:
```cypher
MATCH (ch:Chunk)-[:MENTIONS]->(c:Concept)
RETURN ch, c
LIMIT 50;
```

### Relationship audit:
```cypher
MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS n ORDER BY n DESC;
```
