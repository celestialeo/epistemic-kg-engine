import argparse
import json
import math
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from neo4j import GraphDatabase
from langchain_ollama import ChatOllama, OllamaEmbeddings


NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")


def norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def tokenize(s: str) -> List[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return [t for t in s.split() if t]


def jaccard(a: str, b: str) -> float:
    A = set(tokenize(a))
    B = set(tokenize(b))
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def cosine_bow(a: str, b: str) -> float:
    ca = Counter(tokenize(a))
    cb = Counter(tokenize(b))
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0

    dot = 0.0
    for k, va in ca.items():
        vb = cb.get(k)
        if vb:
            dot += va * vb

    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))


def cosine_dense(a: List[float], b: List[float]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(va * vb for va, vb in zip(a, b))
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0 or nb == 0:
        return 0.0
    return float(dot / (na * nb))


def infer_unit_kind(text: str) -> str:
    t = (text or "").strip().lower()
    for prefix, kind in [
        ("definition:", "definition"),
        ("claim:", "claim"),
        ("example:", "example"),
        ("support:", "support"),
        ("navigation:", "navigation"),
        ("metadata:", "metadata"),
        ("ambiguous:", "example"),
        ("noise:", "noise"),
    ]:
        if t.startswith(prefix):
            return kind
    return "other"


def build_prompt(
    unit_kind: str,
    concepts: List[str],
    relation_lines: Optional[List[str]] = None,
    background_lines: Optional[List[str]] = None,
) -> str:
    base = (
        "You are regenerating the likely original text of a short instructional chunk from a graph-facing semantic representation.\n"
        "Write only the likely chunk content itself, not commentary about the task.\n"
        "Do not mention the graph, the prompt, or missing context.\n"
        "Preserve the chunk's likely function when possible, such as definition, claim, example, navigation note, metadata, or scaffolding.\n"
        "Use only the information provided. Do not invent facts. Keep it 1-2 sentences.\n\n"
        f"unit_kind: {unit_kind}\n"
        f"concepts: {', '.join(concepts) if concepts else '(none)'}\n"
    )

    if relation_lines:
        base += "\nhelpful relation hints:\n"
        for line in relation_lines:
            base += f"- {line}\n"

    if background_lines:
        base += "\nhelpful background knowledge:\n"
        for line in background_lines:
            base += f"- {line}\n"

    base += (
        "\nReturn ONLY the regenerated text as plain prose."
        "\nBad style example: 'The graph representation describes a concept related to neuroscience.'"
        "\nGood style example: 'A neuron is an excitable cell that processes and transmits information through electrical and chemical signals.'"
    )
    return base


def fetch_rows(session, chunk_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
    query = """
    MATCH (ch:Chunk)-[m:MENTIONS]->(c:Concept)
    WHERE $chunk_id IS NULL OR ch.id = $chunk_id
    WITH
      ch,
      collect(DISTINCT c.id) AS concepts,
      collect(DISTINCT m.unit_kind) AS unit_kinds,
      collect(DISTINCT m.layer) AS layers
    RETURN ch.id AS chunk_id, ch.text AS text, concepts, unit_kinds, layers
    ORDER BY ch.id ASC
    LIMIT $limit
    """
    return session.run(query, chunk_id=chunk_id, limit=limit).data()


def resolve_unit_kind(row: Dict[str, Any], original: str) -> str:
    kinds = [
        norm_ws(str(k)).lower()
        for k in row.get("unit_kinds", [])
        if norm_ws(str(k))
    ]
    non_other = [k for k in kinds if k != "other"]
    if non_other:
        return Counter(non_other).most_common(1)[0][0]
    if kinds:
        return Counter(kinds).most_common(1)[0][0]
    return infer_unit_kind(original)


def fetch_relations(session, chunk_id: str) -> Dict[str, Any]:
    ku_id = f"ku::{chunk_id}"

    defines = session.run(
        """
        MATCH (:KnowledgeUnit {id:$ku_id})-[:DEFINES]->(c:Concept)
        RETURN collect(DISTINCT c.id) AS defines
        """,
        ku_id=ku_id,
    ).single()

    part_of = session.run(
        """
        MATCH (:KnowledgeUnit {id:$ku_id})-[r:PART_OF]->(c:Concept)
        RETURN collect(DISTINCT {child: r.child, parent: c.id}) AS part_of
        """,
        ku_id=ku_id,
    ).single()

    causes = session.run(
        """
        MATCH (:KnowledgeUnit {id:$ku_id})-[r:CAUSES]->(c:Concept)
        RETURN collect(DISTINCT {cause: r.cause, effect: c.id}) AS causes
        """,
        ku_id=ku_id,
    ).single()

    return {
        "defines": defines["defines"] if defines else [],
        "part_of": part_of["part_of"] if part_of else [],
        "causes": causes["causes"] if causes else [],
    }


def fetch_background_rows(session, concepts: List[str], limit_per_concept: int) -> List[Dict[str, Any]]:
    if not concepts:
        return []

    query = """
    UNWIND $concepts AS concept_id
    MATCH (c:Concept:Entity {id: concept_id})-[r:IS_A|HAS_PART|REQUIRES_UNDERSTANDING_OF]->(bg:Concept:Entity)
    WITH concept_id, c, r, bg
    ORDER BY concept_id ASC, r.confidence DESC, bg.id ASC
    WITH concept_id, collect({
        source_concept: c.id,
        relation_type: type(r),
        target_concept: bg.id,
        justification: coalesce(r.justification, ""),
        confidence: coalesce(r.confidence, 0.0)
    })[..$limit_per_concept] AS rows
    UNWIND rows AS row
    RETURN row
    """
    raw = session.run(query, concepts=concepts, limit_per_concept=limit_per_concept).data()
    dedup: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for wrapper in raw:
        row = wrapper["row"]
        key = (row["source_concept"], row["relation_type"], row["target_concept"])
        prev = dedup.get(key)
        if prev is None or row["confidence"] > prev["confidence"]:
            dedup[key] = row
    rows = list(dedup.values())
    rows.sort(key=lambda r: (-float(r.get("confidence", 0.0)), r["source_concept"], r["target_concept"]))
    return rows


def format_background_lines(rows: List[Dict[str, Any]], max_background: int) -> List[str]:
    lines: List[str] = []
    for row in rows[:max_background]:
        source = row.get("source_concept", "")
        rel = row.get("relation_type", "")
        target = row.get("target_concept", "")
        justification = norm_ws(row.get("justification", ""))
        confidence = row.get("confidence")
        if justification:
            lines.append(f"{source} {rel} {target} (confidence={confidence:.2f}): {justification}")
        else:
            lines.append(f"{source} {rel} {target} (confidence={confidence:.2f})")
    return lines


def select_relations(
    relations: Dict[str, Any],
    relation_types: List[str],
    max_relations: int,
) -> Dict[str, Any]:
    selected: Dict[str, Any] = {"defines": [], "part_of": [], "causes": []}
    remaining = max_relations

    for rel_type in relation_types:
        if remaining <= 0:
            break
        values = relations.get(rel_type, []) or []
        take = values[:remaining]
        selected[rel_type] = take
        remaining -= len(take)

    return selected


def format_relation_lines(relations: Dict[str, Any]) -> List[str]:
    lines: List[str] = []

    for concept in relations.get("defines", []):
        lines.append(f"the chunk helps define {concept}")

    for rel in relations.get("part_of", []):
        child = rel.get("child")
        parent = rel.get("parent")
        if child and parent:
            lines.append(f"{child} is part of {parent}")

    for rel in relations.get("causes", []):
        cause = rel.get("cause")
        effect = rel.get("effect")
        if cause and effect:
            lines.append(f"{cause} can cause {effect}")

    return lines


def choose_relation_strategy(
    unit_kind: str,
    include_relations: bool,
    relation_types: List[str],
    max_relations: int,
) -> Dict[str, Any]:
    if not include_relations:
        return {"use_relations": False, "relation_types": [], "max_relations": 0, "policy": "graph_only"}

    return {
        "use_relations": True,
        "relation_types": relation_types,
        "max_relations": max_relations,
        "policy": "global",
    }


def choose_relation_strategy_auto(unit_kind: str) -> Dict[str, Any]:
    # Conservative policy based on current experiments:
    # graph-only is the strongest default, while support chunks benefit the most
    # from a small amount of relation guidance.
    if unit_kind == "support":
        return {
            "use_relations": True,
            "relation_types": ["defines"],
            "max_relations": 3,
            "policy": "auto_support_defines",
        }

    return {"use_relations": False, "relation_types": [], "max_relations": 0, "policy": "auto_graph_only"}


def main() -> None:
    p = argparse.ArgumentParser(
        description="Evaluate Neo4j graph fidelity by regenerating chunk text from graph-side concepts and relations."
    )
    p.add_argument("--out", required=True, help="Output JSON with graph-fidelity results.")
    p.add_argument("--model", default="llama3.2:3b", help="Ollama chat model for regeneration.")
    p.add_argument(
        "--embedding-model",
        default="",
        help="Ollama embedding model. Defaults to the chat model name if omitted.",
    )
    p.add_argument("--chunk-id", default="", help="If set, evaluate one chunk only.")
    p.add_argument("--limit", type=int, default=20, help="Maximum number of chunks to evaluate.")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Pass/fail threshold for embedding cosine similarity.",
    )
    p.add_argument(
        "--include-relations",
        action="store_true",
        help="If set, enrich graph-side prompts with epistemic relations via ku::<chunk_id>.",
    )
    p.add_argument(
        "--relation-types",
        default="defines,part_of,causes",
        help="Comma-separated relation types to include when --include-relations is set.",
    )
    p.add_argument(
        "--max-relations",
        type=int,
        default=4,
        help="Maximum number of relation hints to pass into the prompt.",
    )
    p.add_argument(
        "--relation-policy",
        choices=["global", "auto"],
        default="global",
        help="Use one global relation setting for all chunks, or a conservative chunk-type-aware policy.",
    )
    p.add_argument(
        "--include-background",
        action="store_true",
        help="If set, enrich graph-side prompts with background knowledge from IS_A/HAS_PART/REQUIRES_UNDERSTANDING_OF edges.",
    )
    p.add_argument(
        "--background-limit-per-concept",
        type=int,
        default=3,
        help="Maximum background edges to retrieve per concept when --include-background is set.",
    )
    p.add_argument(
        "--max-background",
        type=int,
        default=8,
        help="Maximum number of background hints to pass into the prompt.",
    )
    args = p.parse_args()

    if not NEO4J_PASSWORD:
        raise RuntimeError("Set NEO4J_PASSWORD env var first.")

    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASSWORD),
        encrypted=False,
    )

    llm = ChatOllama(model=args.model, temperature=0)
    embedding_model = args.embedding_model or args.model
    embeddings = OllamaEmbeddings(model=embedding_model)

    out_rows = []
    with driver.session(database=NEO4J_DB) as session:
        rows = fetch_rows(session, args.chunk_id or None, args.limit)
        total = len(rows)
        relation_types = [t.strip() for t in args.relation_types.split(",") if t.strip()]

        for i, row in enumerate(rows, start=1):
            chunk_id = row["chunk_id"]
            original = norm_ws(row.get("text", ""))
            concepts = [norm_ws(str(c)).lower() for c in row.get("concepts", []) if norm_ws(str(c))]
            unit_kind = resolve_unit_kind(row, original)
            if not args.include_relations:
                strategy = choose_relation_strategy(
                    unit_kind=unit_kind,
                    include_relations=False,
                    relation_types=relation_types,
                    max_relations=args.max_relations,
                )
            elif args.relation_policy == "auto":
                strategy = choose_relation_strategy_auto(unit_kind)
            else:
                strategy = choose_relation_strategy(
                    unit_kind=unit_kind,
                    include_relations=args.include_relations,
                    relation_types=relation_types,
                    max_relations=args.max_relations,
                )

            relations = fetch_relations(session, chunk_id) if strategy["use_relations"] else None
            selected_relations = (
                select_relations(relations, strategy["relation_types"], strategy["max_relations"])
                if relations is not None
                else None
            )
            relation_lines = format_relation_lines(selected_relations) if selected_relations is not None else None
            background_rows = (
                fetch_background_rows(session, concepts, args.background_limit_per_concept)
                if args.include_background
                else None
            )
            background_lines = (
                format_background_lines(background_rows, args.max_background)
                if background_rows is not None
                else None
            )
            prompt = build_prompt(
                unit_kind=unit_kind,
                concepts=concepts,
                relation_lines=relation_lines,
                background_lines=background_lines,
            )

            try:
                resp = llm.invoke(prompt)
                regenerated = norm_ws(getattr(resp, "content", str(resp)))

                jac = jaccard(original, regenerated)
                bow_cos = cosine_bow(original, regenerated)
                lexical_combined = float((jac + bow_cos) / 2.0)

                original_vec = embeddings.embed_query(original)
                regenerated_vec = embeddings.embed_query(regenerated)
                emb_cos = cosine_dense(original_vec, regenerated_vec)
                passed = emb_cos >= args.threshold

                out_rows.append(
                    {
                        "chunk_id": chunk_id,
                        "unit_kind": unit_kind,
                        "concepts": concepts,
                        "used_relations": bool(strategy["use_relations"]),
                        "used_background": bool(args.include_background),
                        "relation_policy": strategy["policy"],
                        "relations": selected_relations if args.include_relations else None,
                        "relation_lines": relation_lines if args.include_relations else None,
                        "background_rows": background_rows if args.include_background else None,
                        "background_lines": background_lines if args.include_background else None,
                        "original": original,
                        "regenerated": regenerated,
                        "scores": {
                            "jaccard": jac,
                            "bow_cosine": bow_cos,
                            "lexical_combined": lexical_combined,
                            "embedding_cosine": emb_cos,
                            "threshold": args.threshold,
                            "pass": passed,
                        },
                    }
                )
                print(
                    f"[{i}/{total}] ok chunk={chunk_id} "
                    f"embed={emb_cos:.3f} lexical={lexical_combined:.3f} pass={passed}"
                )
            except Exception as e:
                out_rows.append({"chunk_id": chunk_id, "error": str(e)})
                print(f"[{i}/{total}] ERROR chunk={chunk_id} -> {e}")

    driver.close()

    ok_rows = [r for r in out_rows if "scores" in r]
    summary = {
        "rows": len(out_rows),
        "ok": len(ok_rows),
        "errors": sum("error" in r for r in out_rows),
        "pass": sum(r.get("scores", {}).get("pass") is True for r in out_rows),
        "fail": sum(r.get("scores", {}).get("pass") is False for r in out_rows),
        "avg_embedding_cosine": (
            sum(r["scores"]["embedding_cosine"] for r in ok_rows) / len(ok_rows) if ok_rows else 0.0
        ),
        "avg_lexical_combined": (
            sum(r["scores"]["lexical_combined"] for r in ok_rows) / len(ok_rows) if ok_rows else 0.0
        ),
        "embedding_model": embedding_model,
        "include_relations": bool(args.include_relations),
        "relation_policy": args.relation_policy,
        "include_background": bool(args.include_background),
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps({"summary": summary, "results": out_rows}, indent=2), encoding="utf-8")
    print(f"Saved graph-fidelity results to {out_path}")
    print("Summary:", summary)


if __name__ == "__main__":
    main()
