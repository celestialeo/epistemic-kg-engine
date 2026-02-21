import argparse
import os
from typing import Any, Dict, List, Set

from neo4j import GraphDatabase


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


# 1) Definition-first: prefer KU text + cite chunk
Q_DEFINITIONS = """
MATCH (c:Concept:Entity {id:$concept})<-[:DEFINES]-(k:Definition:Entity)<-[:HAS_KU]-(ch:Chunk:Entity)
RETURN ch.id AS chunk_id,
       k.id AS ku_id,
       k.text AS ku_text,
       k.unit_kind AS unit_kind,
       k.confidence AS ku_confidence
ORDER BY ku_confidence DESC
LIMIT $limit
"""

# 2) Supporting: KU ABOUT excluding definitions
Q_SUPPORT = """
MATCH (c:Concept:Entity {id:$concept})<-[:ABOUT]-(k:Entity)<-[:HAS_KU]-(ch:Chunk:Entity)
WHERE k.type = "KnowledgeUnit" AND NOT k:Definition
RETURN ch.id AS chunk_id,
       k.id AS ku_id,
       k.text AS ku_text,
       k.unit_kind AS unit_kind,
       k.confidence AS ku_confidence
ORDER BY ku_confidence DESC
LIMIT $limit
"""

# 2b) Fallback when no definitions exist: allow any KU ABOUT (including definitions)
Q_KU_FALLBACK = """
MATCH (c:Concept:Entity {id:$concept})<-[:ABOUT]-(k:Entity)<-[:HAS_KU]-(ch:Chunk:Entity)
WHERE k.type = "KnowledgeUnit"
RETURN ch.id AS chunk_id,
       k.id AS ku_id,
       k.text AS ku_text,
       k.unit_kind AS unit_kind,
       k.confidence AS ku_confidence
ORDER BY ku_confidence DESC
LIMIT $limit
"""

# 3) Mentions: chunk-level concept index (may overlap with above)
Q_MENTIONS = """
MATCH (ch:Chunk:Entity)-[r:MENTIONS]->(c:Concept:Entity {id:$concept})
RETURN ch.id AS chunk_id,
       ch.text AS chunk_text,
       r.confidence AS mention_confidence
ORDER BY mention_confidence DESC
LIMIT $limit
"""


def _normalize_ws(s: str) -> str:
    return " ".join((s or "").strip().split())


def _print_section(title: str, rows: List[Dict[str, Any]], exclude_chunks: Set[str] | None = None) -> Set[str]:
    exclude_chunks = exclude_chunks or set()

    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)

    shown: Set[str] = set()
    printed = 0

    for row in rows:
        chunk_id = row.get("chunk_id")
        if not chunk_id or chunk_id in exclude_chunks:
            continue

        # Prefer KU text when present (more “learning unit” feel)
        text = row.get("ku_text") or row.get("chunk_text") or ""
        text = _normalize_ws(text)

        extra_parts = []
        if row.get("ku_confidence") is not None:
            extra_parts.append(f"ku_conf={row['ku_confidence']}")
        if row.get("unit_kind"):
            extra_parts.append(f"unit_kind={row['unit_kind']}")
        if row.get("mention_confidence") is not None:
            extra_parts.append(f"mention_conf={row['mention_confidence']}")

        extra = f" ({', '.join(extra_parts)})" if extra_parts else ""
        kind = "KU" if row.get("ku_text") else "CH"

        printed += 1
        print(f"{printed}. [{chunk_id}] {kind}{extra}\n   {text}\n")

        shown.add(chunk_id)

    if printed == 0:
        print("(no results)")

    return shown


def main():
    parser = argparse.ArgumentParser(description="Retrieve definition-first + supporting content for a concept.")
    parser.add_argument("--concept", required=True, help="Concept id (normalized), e.g. 'neuron'")
    parser.add_argument("--limit-def", type=int, default=5, help="Max definition results")
    parser.add_argument("--limit-support", type=int, default=8, help="Max supporting KU results")
    parser.add_argument("--limit-mentions", type=int, default=8, help="Max mention-based chunk results")
    parser.add_argument("--no-dedupe", action="store_true", help="If set, allow duplicates across sections")
    args = parser.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first, e.g. export NEO4J_PASSWORD='yourpassword'")

    concept = args.concept.strip().lower()

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        defs = session.run(Q_DEFINITIONS, concept=concept, limit=args.limit_def).data()

        # If no definitions exist for this concept, fall back to best KUs
        if len(defs) == 0:
            support = session.run(Q_KU_FALLBACK, concept=concept, limit=args.limit_support).data()
        else:
            support = session.run(Q_SUPPORT, concept=concept, limit=args.limit_support).data()

        mentions = session.run(Q_MENTIONS, concept=concept, limit=args.limit_mentions).data()

    driver.close()

    print(f"Concept: {concept}")

    shown_chunks: Set[str] = set()
    if args.no_dedupe:
        _print_section("1) DEFINITIONS (KU-first, via DEFINES)", defs)
        _print_section("2) SUPPORTING (KU-first, via KU ABOUT)", support)
        _print_section("3) MENTIONS (Chunk-level index)", mentions)
    else:
        shown_chunks |= _print_section("1) DEFINITIONS (KU-first, via DEFINES)", defs)
        shown_chunks |= _print_section("2) SUPPORTING (KU-first, via KU ABOUT)", support, exclude_chunks=shown_chunks)
        _print_section("3) MENTIONS (Chunk-level index)", mentions, exclude_chunks=shown_chunks)


if __name__ == "__main__":
    main()