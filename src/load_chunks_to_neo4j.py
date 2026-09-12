import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from neo4j import GraphDatabase


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Load Chunk nodes + NEXT edges into Neo4j.")
    parser.add_argument("--chunks", required=True, help="Path to chunks JSON (key: 'chunks').")
    parser.add_argument("--source-type", default="unknown", help="Tag to store on chunk nodes (e.g., testpack/pilot/manual).")
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first, e.g. export NEO4J_PASSWORD='yourpassword'")

    chunks_path = Path(args.chunks)
    if not chunks_path.exists():
        raise FileNotFoundError(
    f"Missing {chunks_path}. Provide a chunks JSON with key 'chunks' "
    f"(e.g., data/chunks.json)."
)

    data = load_json(chunks_path)
    chunks: List[Dict[str, Any]] = data.get("chunks", [])

    if not chunks:
        raise ValueError(f"No chunks found in {chunks_path} under key 'chunks'.")

    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD),
        encrypted=False,
    )
    with driver.session(database=NEO4J_DB) as session:
        # Shared uniqueness constraint for all nodes with :Entity label
        session.run("""
        CREATE CONSTRAINT node_id_unique IF NOT EXISTS
        FOR (n:Entity) REQUIRE n.id IS UNIQUE
        """)

        # Upsert chunks
        session.run("""
        UNWIND $rows AS row
        MERGE (c:Chunk:Entity {id: row.chunk_id})
        SET c.type = row.type,
            c.layer = row.layer,
            c.text = row.text,
            c.source_type = $source_type,
            c.source_file = coalesce(row.provenance.source_file, row.source_file, $source_file_fallback)
        """, rows=chunks, source_type=args.source_type, source_file_fallback=str(chunks_path.name))

        # NEXT edges by order (as provided in the chunks file)
        rel_rows = [{"a": chunks[i]["chunk_id"], "b": chunks[i + 1]["chunk_id"]} for i in range(len(chunks) - 1)]
        session.run("""
        UNWIND $rels AS r
        MATCH (a:Chunk:Entity {id: r.a})
        MATCH (b:Chunk:Entity {id: r.b})
        MERGE (a)-[:NEXT]->(b)
        """, rels=rel_rows)

    driver.close()
    print(f"Loaded {len(chunks)} chunks from {chunks_path} with NEXT edges. source_type={args.source_type}")


if __name__ == "__main__":
    main()
