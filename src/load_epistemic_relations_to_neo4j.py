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
    p = argparse.ArgumentParser(description="Load DEFINES/PART_OF/CAUSES edges from relations.json into Neo4j.")
    p.add_argument("--relations", required=True, help="Path to relations JSON (key: 'relations').")
    p.add_argument("--source-type", default="unknown", help="Tag stored on relationships.")
    args = p.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    rel_path = Path(args.relations)
    if not rel_path.exists():
        raise FileNotFoundError(f"Missing {rel_path}")

    rows: List[Dict[str, Any]] = load_json(rel_path).get("relations", [])
    if not rows:
        raise ValueError(f"No relations found in {rel_path} under key 'relations'.")

    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD),
        encrypted=False,
    )

    defines_n = partof_n = causes_n = 0

    with driver.session(database=NEO4J_DB) as session:
        for r in rows:
            if "error" in r or "relations" not in r:
                continue

            ku_id = r["ku_id"]
            conf = float(r.get("confidence", 0.5))
            rels = r["relations"]

            # DEFINES: KU -> Concept
            for c in rels.get("defines", []):
                session.run(
                    """
                    MERGE (k:KnowledgeUnit {id:$ku_id})
                    MERGE (c:Concept {id:$cid})
                    MERGE (k)-[e:DEFINES]->(c)
                    SET e.confidence = $conf,
                        e.source_type = $source_type
                    """,
                    ku_id=ku_id, cid=c, conf=conf, source_type=args.source_type
                )
                defines_n += 1

            # PART_OF: KU -> parent Concept, store child as property
            for p2 in rels.get("part_of", []):
                child = p2.get("child")
                parent = p2.get("parent")
                if not child or not parent:
                    continue
                session.run(
                    """
                    MERGE (k:KnowledgeUnit {id:$ku_id})
                    MERGE (parent:Concept {id:$parent})
                    MERGE (k)-[e:PART_OF]->(parent)
                    SET e.child = $child,
                        e.confidence = $conf,
                        e.source_type = $source_type
                    """,
                    ku_id=ku_id, parent=parent, child=child, conf=conf, source_type=args.source_type
                )
                partof_n += 1

            # CAUSES: KU -> effect Concept, store cause as property
            for c2 in rels.get("causes", []):
                cause = c2.get("cause")
                effect = c2.get("effect")
                if not cause or not effect:
                    continue
                session.run(
                    """
                    MERGE (k:KnowledgeUnit {id:$ku_id})
                    MERGE (effect:Concept {id:$effect})
                    MERGE (k)-[e:CAUSES]->(effect)
                    SET e.cause = $cause,
                        e.confidence = $conf,
                        e.source_type = $source_type
                    """,
                    ku_id=ku_id, effect=effect, cause=cause, conf=conf, source_type=args.source_type
                )
                causes_n += 1

    print(f"Loaded epistemic edges into DB={NEO4J_DB}: DEFINES={defines_n} PART_OF={partof_n} CAUSES={causes_n}")


if __name__ == "__main__":
    main()
