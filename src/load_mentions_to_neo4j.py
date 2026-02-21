import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Load Chunk->Concept MENTIONS edges into Neo4j.")
    parser.add_argument("--mentions", required=True, help="Path to mentions JSON (key: 'mentions').")
    parser.add_argument(
        "--create-missing-concepts",
        action="store_true",
        help="If set, create Concept nodes that are missing (id=concept string).",
    )
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first, e.g. export NEO4J_PASSWORD='yourpassword'")

    mentions_path = Path(args.mentions)
    if not mentions_path.exists():
        raise FileNotFoundError(f"Missing {mentions_path}. Build mentions first.")

    mentions: List[Dict[str, Any]] = load_json(mentions_path).get("mentions", [])
    if not mentions:
        raise ValueError(f"No mentions found in {mentions_path} under key 'mentions'.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        # Optional: ensure concept nodes exist (safer for end-to-end runs)
        if args.create_missing_concepts:
            session.run("""
            UNWIND $rows AS row
            MERGE (c:Concept:Entity {id: row.to_concept})
            SET c.label = coalesce(c.label, row.to_concept)
            """, rows=mentions)

        # Create MENTIONS edges from Chunk -> Concept
        session.run("""
        UNWIND $rows AS row
        MATCH (ch:Chunk:Entity {id: row.from_chunk_id})
        MATCH (c:Concept:Entity {id: row.to_concept})
        MERGE (ch)-[r:MENTIONS]->(c)
        SET r.evidence = coalesce(row.evidence, row.to_concept),
            r.confidence = row.confidence,
            r.layer = row.layer,
            r.unit_kind = row.unit_kind
        """, rows=mentions)

    driver.close()
    print(f"Loaded {len(mentions)} Chunk->Concept MENTIONS edges from {mentions_path}.")


if __name__ == "__main__":
    main()