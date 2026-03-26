"""
select_seed_concepts_v2.py
---------------------------
Updated version of select_seed_concepts.py.

Key change: also exports chunk_id and source_text (the highest-mention chunk's
paragraph) for each concept. This feeds directly into expand_background_knowledge_v2.py
so the LLM receives the actual neuroscience context the concept appeared in,
rather than expanding blindly from the concept string alone.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from neo4j import GraphDatabase


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")


# Returns the concept's most-cited chunk together with its text,
# giving the expansion model the neuroscience context it needs.
Q_TOP_CONCEPTS = """
MATCH (c:Concept:Entity)
OPTIONAL MATCH (ch:Chunk:Entity)-[:MENTIONS]->(c)
WITH c, ch, count(ch) AS w
ORDER BY w DESC
WITH c, collect(ch)[0] AS top_chunk, sum(w) AS total_mentions
RETURN c.id AS concept_id,
       coalesce(c.label, c.id) AS label,
       total_mentions AS mention_count,
       top_chunk.id AS chunk_id,
       top_chunk.text AS source_text
ORDER BY total_mentions DESC, concept_id ASC
LIMIT $limit
"""


def main():
    parser = argparse.ArgumentParser(
        description="Select seed concepts with source paragraph context for background expansion."
    )
    parser.add_argument("--out", required=True, help="Output JSON file for seed concepts.")
    parser.add_argument("--limit", type=int, default=50, help="Number of seed concepts to export.")
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database=NEO4J_DB) as session:
        rows = session.run(Q_TOP_CONCEPTS, limit=args.limit).data()
    driver.close()

    out: Dict[str, Any] = {
        "concepts": [
            {
                "id": r["concept_id"],
                "label": r["label"],
                "mention_count": r["mention_count"],
                "chunk_id": r.get("chunk_id") or "",
                "source_text": r.get("source_text") or "",
            }
            for r in rows
        ]
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Saved {len(out['concepts'])} seed concepts (with source paragraphs) to {out_path}")


if __name__ == "__main__":
    main()