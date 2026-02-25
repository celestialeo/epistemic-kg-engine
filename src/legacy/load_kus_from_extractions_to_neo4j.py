import argparse
import json
import os
from pathlib import Path
from typing import Dict, Any, List

from neo4j import GraphDatabase
from neo4j.exceptions import ClientError


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


# Map unit_kind -> Neo4j label (schema-aligned)
UNIT_KIND_TO_LABEL = {
    "definition": "Definition",
    "core_statement": "Claim",
    "example": "ProofStep",
    # fallback handled below
}


def norm_concept(s: str) -> str:
    """Keep consistent with your dedup convention."""
    return " ".join(s.strip().lower().split())


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_entity_id_constraint(session) -> None:
    """
    Align with load_chunks_to_neo4j.py:
    enforce uniqueness across all node types using shared :Entity label.
    This is Neo4j 5 compatible (single label in FOR clause).
    """
    try:
        session.run("""
        CREATE CONSTRAINT node_id_unique IF NOT EXISTS
        FOR (n:Entity) REQUIRE n.id IS UNIQUE
        """)
    except ClientError as e:
        # Most common: insufficient privileges for constraint creation
        print(f"[WARN] Could not create :Entity id uniqueness constraint. Continuing. Details: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Load KnowledgeUnit nodes from LLM extractions and connect to Chunk + Concept nodes in Neo4j."
    )
    parser.add_argument("--extractions", required=True, help="Input extractions JSON (key: 'extractions').")
    parser.add_argument("--concepts", required=False, help="Optional concepts JSON (key: 'concepts').")
    parser.add_argument("--source-type", default="testpack", help="Metadata tag stored on KUs (e.g., testpack/pilot).")
    parser.add_argument("--min-confidence", type=float, default=0.0, help="Skip KUs below this confidence.")
    parser.add_argument(
        "--max-concepts-per-ku", type=int, default=0,
        help="Optional cap on concepts per KU (0 = no cap)."
    )
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first, e.g. export NEO4J_PASSWORD='yourpassword'")

    extractions_path = Path(args.extractions)
    concepts_path = Path(args.concepts) if args.concepts else None

    data = load_json(extractions_path)
    rows = data.get("extractions", [])

    # Optional: only allow concepts that exist in the dedup concept list
    allowed_concepts = None
    if concepts_path and concepts_path.exists():
        cdata = load_json(concepts_path)
        allowed_concepts = set()
        for c in cdata.get("concepts", []):
            cid = norm_concept(c.get("id", c.get("label", "")))
            if cid:
                allowed_concepts.add(cid)

    # Build batches
    ku_nodes: List[Dict[str, Any]] = []
    has_ku_rels: List[Dict[str, Any]] = []
    about_rels: List[Dict[str, Any]] = []
    defines_rels: List[Dict[str, Any]] = []

    for r in rows:
        if "error" in r:
            continue

        chunk_id = r.get("chunk_id")
        llm = r.get("llm", {})
        text = r.get("text", "")

        unit_kind = str(llm.get("unit_kind", "other")).strip().lower()
        layer = str(llm.get("layer", "support")).strip().lower()
        confidence = float(llm.get("confidence", 0.5))

        if confidence < args.min_confidence:
            continue

        ku_label = UNIT_KIND_TO_LABEL.get(unit_kind, "ProofStep") if unit_kind == "example" else UNIT_KIND_TO_LABEL.get(unit_kind, "Claim")
        # The above line is NOT ideal; we will do a cleaner fallback below:
        ku_label = UNIT_KIND_TO_LABEL.get(unit_kind, "Claim") if unit_kind in ("core_statement",) else UNIT_KIND_TO_LABEL.get(unit_kind, "ProofStep") if unit_kind in ("example",) else UNIT_KIND_TO_LABEL.get(unit_kind, "Definition") if unit_kind in ("definition",) else "Claim"
        # Ultimately: unknown types map to Claim (safe default). You can change to "Definition" if you prefer.

        ku_id = f"ku_{chunk_id}"

        concepts = llm.get("concepts", [])
        if not isinstance(concepts, list):
            concepts = []

        concepts_norm = []
        for c in concepts:
            c_norm = norm_concept(str(c))
            if not c_norm:
                continue
            if allowed_concepts is not None and c_norm not in allowed_concepts:
                continue
            concepts_norm.append(c_norm)

        if args.max_concepts_per_ku and args.max_concepts_per_ku > 0:
            concepts_norm = concepts_norm[: args.max_concepts_per_ku]

        ku_nodes.append({
            "id": ku_id,
            "ku_label": ku_label,          # one of Definition/Claim/ProofStep
            "chunk_id": chunk_id,
            "text": text,
            "layer": layer,
            "unit_kind": unit_kind,
            "confidence": confidence,
            "source_type": args.source_type,
            "type": "KnowledgeUnit",        # aligns with schema optional_node_fields
        })

        has_ku_rels.append({"chunk_id": chunk_id, "ku_id": ku_id})

        for c_norm in concepts_norm:
            about_rels.append({
                "ku_id": ku_id,
                "concept_id": c_norm,
                "confidence": confidence,
                "unit_kind": unit_kind,
                "layer": layer,
                "evidence": c_norm,
            })

            if ku_label == "Definition":
                defines_rels.append({
                    "ku_id": ku_id,
                    "concept_id": c_norm,
                    "confidence": confidence,
                    "evidence": c_norm,
                })

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        # Align with other loaders
        ensure_entity_id_constraint(session)

        # 1) Upsert KUs as :Entity plus a specific KU label (Definition/Claim/ProofStep)
        session.run("""
        UNWIND $rows AS row
        MERGE (k:Entity {id: row.id})
        SET k.type = row.type,
            k.text = row.text,
            k.layer = row.layer,
            k.unit_kind = row.unit_kind,
            k.confidence = row.confidence,
            k.source = row.source_type,
            k.chunk_id = row.chunk_id
        """, rows=ku_nodes)

        # Apply one of the schema KU labels (no APOC)
        for label in ["Definition", "Claim", "ProofStep"]:
            session.run(f"""
            UNWIND $rows AS row
            MATCH (k:Entity {{id: row.id}})
            WHERE row.ku_label = '{label}'
            SET k:{label}
            """, rows=ku_nodes)

        # 2) Connect Chunk -> KU
        session.run("""
        UNWIND $rels AS r
        MATCH (ch:Chunk:Entity {id: r.chunk_id})
        MATCH (k:Entity {id: r.ku_id})
        MERGE (ch)-[:HAS_KU]->(k)
        """, rels=has_ku_rels)

        # 3) KU -> Concept (ABOUT)
        session.run("""
        UNWIND $rels AS r
        MATCH (k:Entity {id: r.ku_id})
        MATCH (c:Concept:Entity {id: r.concept_id})
        MERGE (k)-[m:ABOUT]->(c)
        SET m.confidence = r.confidence,
            m.unit_kind = r.unit_kind,
            m.layer = r.layer,
            m.evidence = r.evidence
        """, rels=about_rels)

        # 4) Definition KUs -> Concept (DEFINES)
        session.run("""
        UNWIND $rels AS r
        MATCH (k:Entity {id: r.ku_id})
        MATCH (c:Concept:Entity {id: r.concept_id})
        MERGE (k)-[d:DEFINES]->(c)
        SET d.confidence = r.confidence,
            d.evidence = r.evidence
        """, rels=defines_rels)

    driver.close()

    print(f"Loaded KnowledgeUnits from: {extractions_path}")
    print(f"KUs upserted: {len(ku_nodes)}")
    print(f"HAS_KU rels: {len(has_ku_rels)}")
    print(f"ABOUT rels: {len(about_rels)}")
    print(f"DEFINES rels: {len(defines_rels)}")


if __name__ == "__main__":
    main()
