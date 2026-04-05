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


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


Q_CONSTRAINTS = [
    """
    CREATE CONSTRAINT node_id_unique IF NOT EXISTS
    FOR (n:Entity) REQUIRE n.id IS UNIQUE
    """,
]

Q_UPSERT_CONCEPTS = """
UNWIND $rows AS row
MERGE (s:Concept:Entity {id: row.source_concept})
ON CREATE SET s.label = row.source_concept, s.source = "document", s.concept_kind = "domain"
SET s.source = CASE
    WHEN s.source IS NULL THEN "document"
    WHEN s.source = "background" THEN "document+background"
    ELSE s.source
END,
s.concept_kind = CASE
    WHEN s.concept_kind IS NULL THEN "domain"
    WHEN s.concept_kind = "background" THEN "domain_background"
    ELSE s.concept_kind
END

MERGE (t:Concept:Entity {id: row.target_concept})
ON CREATE SET t.label = row.target_concept, t.source = "background", t.concept_kind = "background"
SET t.source = CASE
    WHEN t.source IS NULL THEN "background"
    WHEN t.source = "document" THEN "document+background"
    ELSE t.source
END,
t.concept_kind = CASE
    WHEN t.concept_kind IS NULL THEN "background"
    WHEN t.concept_kind = "domain" THEN "domain_background"
    ELSE t.concept_kind
END,
t.last_updated = datetime()
"""

Q_LOAD_IS_A = """
UNWIND $rows AS row
MATCH (s:Concept:Entity {id: row.source_concept})
MATCH (t:Concept:Entity {id: row.target_concept})
MERGE (s)-[r:IS_A]->(t)
SET r.source = "co_scientist_background",
    r.justification = row.justification,
    r.confidence = row.loaded_score,
    r.status = row.status,
    r.last_updated = datetime()
"""

Q_LOAD_HAS_PART = """
UNWIND $rows AS row
MATCH (s:Concept:Entity {id: row.source_concept})
MATCH (t:Concept:Entity {id: row.target_concept})
MERGE (s)-[r:HAS_PART]->(t)
SET r.source = "co_scientist_background",
    r.justification = row.justification,
    r.confidence = row.loaded_score,
    r.status = row.status,
    r.last_updated = datetime()
"""

Q_LOAD_REQUIRES = """
UNWIND $rows AS row
MATCH (s:Concept:Entity {id: row.source_concept})
MATCH (t:Concept:Entity {id: row.target_concept})
MERGE (s)-[r:REQUIRES_UNDERSTANDING_OF]->(t)
SET r.source = "co_scientist_background",
    r.justification = row.justification,
    r.confidence = row.loaded_score,
    r.status = row.status,
    r.last_updated = datetime()
"""

Q_LOAD_BACKGROUND_FACTS = """
UNWIND $rows AS row
MERGE (f:BackgroundFact:Entity {id: row.fact_id})
SET f.text = row.justification,
    f.relation_type = row.relation_type,
    f.confidence = row.loaded_score,
    f.status = row.status,
    f.source = "co_scientist_background",
    f.last_updated = datetime()

WITH row, f
MATCH (s:Concept:Entity {id: row.source_concept})
MATCH (t:Concept:Entity {id: row.target_concept})
MERGE (f)-[:ABOUT]->(s)
MERGE (f)-[:ABOUT]->(t)
MERGE (s)-[:SUPPORTED_BY]->(f)
"""


def make_fact_id(row: Dict[str, Any]) -> str:
    return f"bgf::{row['source_concept']}::{row['relation_type']}::{row['target_concept']}"


def resolve_score(row: Dict[str, Any]) -> float:
    if row.get("eigenvalue_weighted_score") is not None:
        return float(row["eigenvalue_weighted_score"])
    if row.get("final_score") is not None:
        return float(row["final_score"])
    if row.get("proposer_confidence") is not None:
        return float(row["proposer_confidence"])
    return 0.0


def main():
    parser = argparse.ArgumentParser(description="Load approved background knowledge into Neo4j.")
    parser.add_argument("--in", dest="in_path", required=True, help="Input approved background JSON.")
    parser.add_argument("--with-facts", action="store_true", help="Also create BackgroundFact nodes.")
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    in_path = Path(args.in_path)
    data = load_json(in_path)
    rows: List[Dict[str, Any]] = data.get("approved_edges", [])

    if not rows:
        raise ValueError(f"No approved_edges found in {in_path}")

    for row in rows:
        row["fact_id"] = make_fact_id(row)
        row["loaded_score"] = resolve_score(row)

    is_a_rows = [r for r in rows if r["relation_type"] == "is_a"]
    has_part_rows = [r for r in rows if r["relation_type"] == "has_part"]
    requires_rows = [r for r in rows if r["relation_type"] == "requires_understanding_of"]

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session(database=NEO4J_DB) as session:
        for q in Q_CONSTRAINTS:
            session.run(q)

        session.run(Q_UPSERT_CONCEPTS, rows=rows)

        if is_a_rows:
            session.run(Q_LOAD_IS_A, rows=is_a_rows)
        if has_part_rows:
            session.run(Q_LOAD_HAS_PART, rows=has_part_rows)
        if requires_rows:
            session.run(Q_LOAD_REQUIRES, rows=requires_rows)

        if args.with_facts:
            session.run(Q_LOAD_BACKGROUND_FACTS, rows=rows)

    driver.close()
    print(f"Loaded {len(rows)} background edges into Neo4j from {in_path}")


if __name__ == "__main__":
    main()
