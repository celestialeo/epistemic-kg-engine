import argparse
import os
from typing import Any, Dict, List

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")

def detect_rel_type(session) -> str:
    # Prefer MENTIONS if present, else ABOUT, else first rel type
    rels = session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType").data()
    rel_names = [r["relationshipType"] for r in rels]
    if "MENTIONS" in rel_names:
        return "MENTIONS"
    if "ABOUT" in rel_names:
        return "ABOUT"
    return rel_names[0] if rel_names else "MENTIONS"

def main():
    p = argparse.ArgumentParser(description="Core-mode retrieval: Concept -> Chunks via concept relationship.")
    p.add_argument("--concept", required=True, help="Concept id (exact match to Concept.id)")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--db", default=None, help="Neo4j database name (optional).")
    args = p.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # If you want to force DB: session(database="neo4j")
    session_kwargs = {}
    if args.db:
        session_kwargs["database"] = args.db

    with driver.session(database=NEO4J_DB) as session:
        rel = detect_rel_type(session)

        query = f"""
        MATCH (c:Concept {{id:$concept}})<-[:{rel}]-(ch:Chunk)
        RETURN ch.id AS chunk_id, ch.text AS text
        ORDER BY ch.id ASC
        LIMIT $limit
        """

        rows: List[Dict[str, Any]] = session.run(query, concept=args.concept, limit=args.limit).data()

    if not rows:
        print(f"No chunks found for concept='{args.concept}'.")
        print("Tip: list concepts with: MATCH (c:Concept) RETURN c.id LIMIT 20;")
        return

    print(f"Relationship used: {rel}")
    print(f"Concept: {args.concept} | results: {len(rows)}\n")
    for i, r in enumerate(rows, start=1):
        print(f"[{i}] {r.get('chunk_id')}")
        print(f"    {(r.get('text') or '').strip()}\n")

if __name__ == "__main__":
    main()