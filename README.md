# Show & Tell Demo Runbook — LangChain + Ollama → Neo4j Knowledge Graph

This demo shows an end-to-end, **offline** pipeline that converts text chunks into **structured knowledge** and loads it into **Neo4j** as a queryable knowledge graph.

---

## What I’m Demonstrating

1. **Heuristic test data** (`testpack_v1_chunks.json`) covering:
   - definitions, claims, examples
   - navigation/metadata text
   - noisy/low-signal text
   - abbreviations + mixed technical domains

2. **Structured extraction** using:
   - **LangChain** orchestration
   - **Ollama** (local Llama model)
   - **Pydantic schema validation** (`layer`, `unit_kind`, `concepts`, `confidence`)

3. **Graph construction**
   - Concept list (deduped)
   - `(:Chunk)-[:ABOUT]->(:Concept)` relationships

4. **Neo4j visualization + queries**
   - counts as proof of loading
   - graph view 

---
Raw text is hard to search and connect. I want the system to understand: what is this chunk about, what kind of information is it, and what concepts does it mention—then store that in a graph.”


## Quick Project Flow

```text
testpack chunks
  → LangChain/Ollama extraction (structured JSON)
  → build mentions + dedup concepts
  → load nodes + edges into Neo4j
  → query + visualize the knowledge graph

  ```
  The flow is: I take chunks of text → send each chunk to a local LLM via LangChain → the model outputs a structured JSON object → I validate it with Pydantic → then I create concept nodes and connect chunks to concepts in Neo4j.
  
## Demo step 1: input testpack 
I created a heuristic testpack that includes definitions, claims, examples, navigation text, metadata, and noisy text—so it tests multiple project directions.

## Demo step 2: extraction output
For each chunk, the model returns four fields: layer, unit_kind, concepts, and confidence. This is the structured ‘knowledge unit’ representation.

## Demo step 3: graph visualization 
In Neo4j, each chunk is a node, each concept is a node, and an ABOUT edge means ‘this chunk talks about that concept’. The nice part is that multiple chunks can link to the same concept, which enables concept-based retrieval.



-------------------------------------------------------------------------------------------------------------

```
## Prerequisites 

1. Activate the Python environment 
```
source .venv/bin/activate

```
2. Ollama installed + model available:- 
```
ollama run llama3.2:3b "Say hi"
```
3. Docker Installed (For Neo4j)

```
docker --version 
```
---------------------------------------------------------------------------------------------------------------

## Step 1- Generate Structured Extractions (LangChain + Ollama)

1. Input: outputs/testpack_v1_chunks.json
2. Output: outputs/testpack_v1_chunks.json

```
python -u src/langchain_extract_knowledgeunits.py \
  --in outputs/testpack_v1_chunks.json \
  --out outputs/testpack_v1_extractions.json \
  --model llama3.2:3b
  ```
  # Verify
  ```
  python -c "import json; d=json.load(open('outputs/testpack_v1_extractions.json')); print('rows', len(d['extractions']), 'errors', sum('error' in r for r in d['extractions']))"
```

## Step 2- Build Graph- Ready Artifacts (Concepts+Edges)
Outputs- 
1. outputs/testpack_v1_concepts_dedup.json
2. outputs/testpack_v1_mentions.json

```
python -u src/build_mentions_from_extractions.py \
  --in outputs/testpack_v1_extractions.json \
  --concepts-out outputs/testpack_v1_concepts_dedup.json \
  --mentions-out outputs/testpack_v1_mentions.json
  ```

  # Verify 
  ```
  python -c "import json; m=json.load(open('outputs/testpack_v1_mentions.json'))['mentions']; c=json.load(open('outputs/testpack_v1_concepts_dedup.json'))['concepts']; print('concepts', len(c), 'edges', len(m)); print('sample_edge', m[:2])"

  ```
  
  ## Step 3- Start Neo4j (Docker) + Set Environment Variables
  ```
  docker rm -f neo4j 2>/dev/null || true
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/test12345 \
  neo4j:5
  ```

  # Set env vars- 
  ```
export NEO4J_URI="bolt://localhost:7687"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="test12345"
```
# Check bolt port 

```
nc -vz localhost 7687

```

## Step 4- Load Nodes and Edges in Neo4j 

1. Load chunk nodes + NEXT edges 

Run 
```
python -u src/load_chunks_to_neo4j.py

```
2. Load Concept Nodes (nodes only)

Run 
```
python -u src/load_concepts_to_neo4j.py

```
3. Load ABOUT edges from mentions 

Run 
```
python -u src/load_mentions_to_neo4j.py
```

## Step 5- Neo4j Queries (Counts + Graph View)

# Counts(proof it loaded)

```
MATCH (ch:Chunk) RETURN count(ch) AS chunks;
MATCH (c:Concept) RETURN count(c) AS concepts;
MATCH (:Chunk)-[:ABOUT]->(:Concept) RETURN count(*) AS about_edges;
MATCH ()-[r:NEXT]->() RETURN count(r) AS next_edges;
```

# Graph View 

```
MATCH (ch:Chunk {id:"tp_0000"})-[:ABOUT]->(c:Concept)
RETURN ch, c;
```
```
MATCH (c:Concept {id:"neuron"})<-[:ABOUT]-(ch:Chunk)-[:ABOUT]->(c2:Concept)
RETURN c, ch, c2
LIMIT 50;
```

