import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from neo4j import GraphDatabase
from build_mentions_from_extractions import norm_concept, keep_concept

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description="Load KnowledgeUnit nodes from extractions JSON.")
    p.add_argument("--extractions", required=True, help="Path to extractions JSON (key: 'extractions').")
    p.add_argument("--source-type", default="unknown", help="Tag stored on KU nodes.")
    args = p.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    in_path = Path(args.extractions)
    if not in_path.exists():
        raise FileNotFoundError(f"Missing {in_path}")

    data = load_json(in_path)
    rows: List[Dict[str, Any]] = data.get("extractions", [])
    if not rows:
        raise ValueError(f"No extractions found in {in_path} under key 'extractions'.")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    loaded = 0
    with driver.session(database=NEO4J_DB) as session:
        # Constraints
        session.run("""
        CREATE CONSTRAINT ku_id_unique IF NOT EXISTS
        FOR (k:KnowledgeUnit) REQUIRE k.id IS UNIQUE
        """)

        for r in rows:
            if "error" in r:
                continue

            chunk_id = r["chunk_id"]
            text = r.get("text", "")
            llm = r.get("llm", {})

            ku_id = f"ku::{chunk_id}"
            unit_kind = llm.get("unit_kind", "other")
            layer = llm.get("layer", "support")
            confidence = float(llm.get("confidence", 0.5))
            concepts = llm.get("concepts", [])

            # 1) Create KU and link Chunk -> KU
            session.run(
                """
                MERGE (ch:Chunk {id:$chunk_id})
                MERGE (k:KnowledgeUnit {id:$ku_id})
                SET k.text = $text,
                    k.unit_kind = $unit_kind,
                    k.layer = $layer,
                    k.confidence = $confidence,
                    k.source_type = $source_type,
                    k.chunk_id = $chunk_id
                MERGE (ch)-[:HAS_KU]->(k)
                """,
                chunk_id=chunk_id,
                ku_id=ku_id,
                text=text,
                unit_kind=unit_kind,
                layer=layer,
                confidence=confidence,
                source_type=args.source_type,
            )

            # 2) KU -> Concept MENTIONS (for semantic anchoring)
            for c in concepts:
                cid = norm_concept(c)
                if not keep_concept(cid):
                    continue
                session.run(
                    """
                    MERGE (c:Concept {id:$cid})
                    MERGE (k:KnowledgeUnit {id:$ku_id})
                    MERGE (k)-[:MENTIONS]->(c)
                    """,
                    cid=cid,
                    ku_id=ku_id,
                )

            loaded += 1

    print(f"Loaded {loaded} KnowledgeUnits from {in_path}. DB={NEO4J_DB} source_type={args.source_type}")


if __name__ == "__main__":
    main()
