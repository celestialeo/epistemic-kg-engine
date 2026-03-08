import argparse
import json
import os
from pathlib import Path
from typing import List, Dict, Any

from neo4j import GraphDatabase


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")


Q_TOP_CONCEPTS = """
MATCH (c:Concept:Entity)
OPTIONAL MATCH (ch:Chunk:Entity)-[:MENTIONS]->(c)
WITH c, count(ch) AS mention_count
RETURN c.id AS concept_id,
       coalesce(c.label, c.id) AS label,
       mention_count
ORDER BY mention_count DESC, concept_id ASC
LIMIT $limit
"""


def main():
    parser = argparse.ArgumentParser(description="Select seed concepts from Neo4j for background expansion.")
    parser.add_argument("--out", required=True, help="Output JSON file for seed concepts.")
    parser.add_argument("--limit", type=int, default=50, help="Number of seed concepts to export.")
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database=NEO4J_DB) as session:
        rows = session.run(Q_TOP_CONCEPTS, limit=args.limit).data()
    driver.close()

    out = {
        "concepts": [
            {
                "id": r["concept_id"],
                "label": r["label"],
                "mention_count": r["mention_count"],
            }
            for r in rows
        ]
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Saved {len(out['concepts'])} seed concepts to {out_path}")


if __name__ == "__main__":
    main()