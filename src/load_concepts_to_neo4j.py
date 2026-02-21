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
    parser = argparse.ArgumentParser(description="Load Concept nodes into Neo4j.")
    parser.add_argument("--concepts", required=True, help="Path to concepts JSON (key: 'concepts').")
    parser.add_argument("--source-type", default="unknown", help="Tag stored on concept nodes.")
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first, e.g. export NEO4J_PASSWORD='yourpassword'")

    concepts_path = Path(args.concepts)
    if not concepts_path.exists():
        raise FileNotFoundError(f"Missing {concepts_path}. Run extract_concepts.py first.")

    concepts: List[Dict[str, Any]] = load_json(concepts_path).get("concepts", [])
    if not concepts:
        raise ValueError(f"No concepts found in {concepts_path} under key 'concepts'.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        # Version-safe: rely on global uniqueness across all :Entity nodes
        session.run("""
        CREATE CONSTRAINT node_id_unique IF NOT EXISTS
        FOR (n:Entity) REQUIRE n.id IS UNIQUE
        """)

        session.run("""
        UNWIND $rows AS row
        MERGE (c:Concept:Entity {id: row.id})
        SET c.label = coalesce(row.label, row.id),
            c.count = coalesce(row.count, c.count, 0),
            c.source_type = $source_type
        """, rows=concepts, source_type=args.source_type)

    driver.close()
    print(f"Loaded/updated {len(concepts)} concepts from {concepts_path}. source_type={args.source_type}")


if __name__ == "__main__":
    main()