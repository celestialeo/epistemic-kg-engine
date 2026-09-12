"""
Write key_predicate and anchor_phrases from an extractions JSON onto
existing Chunk nodes in Neo4j.

Run this after re-extracting with the updated schema to enrich the graph
without rebuilding it from scratch:

    python src/enrich_chunks_in_neo4j.py \
        --extractions outputs/runs/<run-id>/extractions.json
"""

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


def build_rows(extractions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for r in extractions:
        if "error" in r:
            continue
        llm = r.get("llm", {})
        rows.append({
            "chunk_id": r["chunk_id"],
            "key_predicate": llm.get("key_predicate", ""),
            "anchor_phrases": llm.get("anchor_phrases", []),
        })
    return rows


def main() -> None:
    p = argparse.ArgumentParser(
        description="Enrich Chunk nodes with key_predicate and anchor_phrases from extractions JSON."
    )
    p.add_argument("--extractions", required=True, help="Extractions JSON produced by langchain_extract_knowledgeunits.py")
    args = p.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    data = json.loads(Path(args.extractions).read_text(encoding="utf-8"))
    extractions: List[Dict[str, Any]] = data.get("extractions", [])
    rows = build_rows(extractions)

    if not rows:
        print("No rows to enrich.")
        return

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), encrypted=False)
    with driver.session(database=NEO4J_DB) as session:
        result = session.run(
            """
            UNWIND $rows AS row
            MATCH (ch:Chunk {id: row.chunk_id})
            SET ch.key_predicate   = row.key_predicate,
                ch.anchor_phrases  = row.anchor_phrases
            RETURN count(*) AS updated
            """,
            rows=rows,
        )
        updated = result.single()["updated"]

    driver.close()
    print(f"Enriched {updated} Chunk nodes from {args.extractions}")


if __name__ == "__main__":
    main()
