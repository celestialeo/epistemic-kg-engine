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
    a_set = set(tokenize(a))
    b_set = set(tokenize(b))
    if not a_set and not b_set:
        return 1.0
    if not a_set or not b_set:
        return 0.0
    return len(a_set & b_set) / len(a_set | b_set)


def cosine_bow(a: str, b: str) -> float:
    ca = Counter(tokenize(a))
    cb = Counter(tokenize(b))
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0

    dot = sum(va * cb.get(k, 0) for k, va in ca.items())
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


def fetch_rows(session, chunk_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
    query = """
    MATCH (ch:Chunk)-[m:MENTIONS]->(c:Concept)
    WHERE $chunk_id IS NULL OR ch.id = $chunk_id
    WITH ch, collect(DISTINCT c.id) AS concepts
    RETURN ch.id AS chunk_id, ch.text AS text, concepts
    ORDER BY ch.id ASC
    LIMIT $limit
    """
    return session.run(query, chunk_id=chunk_id, limit=limit).data()


def fetch_background(session, concepts: List[str], limit_per_concept: int) -> List[Dict[str, Any]]:
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
        target_kind: coalesce(bg.concept_kind, ""),
        target_source: coalesce(bg.source, ""),
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
        if key not in dedup or row["confidence"] > dedup[key]["confidence"]:
            dedup[key] = row
    rows = list(dedup.values())
    rows.sort(key=lambda r: (-float(r.get("confidence", 0.0)), r["source_concept"], r["target_concept"]))
    return rows


def build_prompt(concepts: List[str], background_lines: Optional[List[str]] = None) -> str:
    prompt = (
        "You are reconstructing the likely original wording of a short neuroscience teaching chunk from graph retrieval results.\n"
        "Write only the likely chunk content itself, not commentary.\n"
        "Keep it to 1-2 sentences.\n"
        "Use only the information provided and avoid inventing unsupported facts.\n\n"
        f"document concepts: {', '.join(concepts) if concepts else '(none)'}\n"
    )
    if background_lines:
        prompt += "\nretrieved background knowledge:\n"
        for line in background_lines:
            prompt += f"- {line}\n"
    prompt += "\nReturn only the reconstructed chunk text."
    return prompt


def format_background_lines(rows: List[Dict[str, Any]], max_lines: int) -> List[str]:
    lines: List[str] = []
    for row in rows[:max_lines]:
        source = row.get("source_concept", "")
        rel = row.get("relation_type", "")
        target = row.get("target_concept", "")
        justification = norm_ws(row.get("justification", ""))
        conf = float(row.get("confidence", 0.0))
        if justification:
            lines.append(f"{source} {rel} {target} (confidence={conf:.2f}): {justification}")
        else:
            lines.append(f"{source} {rel} {target} (confidence={conf:.2f})")
    return lines


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate whether Neo4j background retrieval improves chunk reconstruction quality."
    )
    parser.add_argument("--out", required=True, help="Output JSON with evaluation results.")
    parser.add_argument("--model", default="llama3.2:3b", help="Ollama chat model for reconstruction.")
    parser.add_argument(
        "--embedding-model",
        default="",
        help="Ollama embedding model. Defaults to the chat model name if omitted.",
    )
    parser.add_argument("--chunk-id", default="", help="If set, evaluate one chunk only.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum number of chunks to evaluate.")
    parser.add_argument(
        "--limit-per-concept",
        type=int,
        default=3,
        help="Maximum background edges to retrieve per concept.",
    )
    parser.add_argument(
        "--max-background-lines",
        type=int,
        default=8,
        help="Maximum retrieved background lines to pass into the reconstruction prompt.",
    )
    args = parser.parse_args()

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

    out_rows: List[Dict[str, Any]] = []
    with driver.session(database=NEO4J_DB) as session:
        rows = fetch_rows(session, args.chunk_id or None, args.limit)
        total = len(rows)
        for i, row in enumerate(rows, start=1):
            chunk_id = row["chunk_id"]
            original = norm_ws(row.get("text", ""))
            concepts = sorted({norm_ws(c) for c in row.get("concepts", []) if norm_ws(c)})
            bg_rows = fetch_background(session, concepts, args.limit_per_concept)
            bg_lines = format_background_lines(bg_rows, args.max_background_lines)

            baseline_resp = llm.invoke(build_prompt(concepts))
            baseline_text = norm_ws(getattr(baseline_resp, "content", str(baseline_resp)))

            background_resp = llm.invoke(build_prompt(concepts, bg_lines))
            background_text = norm_ws(getattr(background_resp, "content", str(background_resp)))

            original_emb = embeddings.embed_query(original)
            baseline_emb = embeddings.embed_query(baseline_text)
            background_emb = embeddings.embed_query(background_text)
            bundle_text = " ".join(bg_lines)
            bundle_emb = embeddings.embed_query(bundle_text) if bundle_text else []

            baseline_cos = cosine_dense(original_emb, baseline_emb)
            background_cos = cosine_dense(original_emb, background_emb)
            delta_cos = background_cos - baseline_cos

            baseline_lex = 0.5 * jaccard(original, baseline_text) + 0.5 * cosine_bow(original, baseline_text)
            background_lex = 0.5 * jaccard(original, background_text) + 0.5 * cosine_bow(original, background_text)
            bundle_relevance = cosine_dense(original_emb, bundle_emb) if bundle_text else 0.0

            out_rows.append(
                {
                    "chunk_id": chunk_id,
                    "original": original,
                    "concepts": concepts,
                    "background_edge_count": len(bg_rows),
                    "background_lines_used": bg_lines,
                    "baseline_reconstruction": baseline_text,
                    "background_reconstruction": background_text,
                    "baseline_embedding_cosine": round(baseline_cos, 4),
                    "background_embedding_cosine": round(background_cos, 4),
                    "delta_embedding_cosine": round(delta_cos, 4),
                    "baseline_lexical_score": round(baseline_lex, 4),
                    "background_lexical_score": round(background_lex, 4),
                    "delta_lexical_score": round(background_lex - baseline_lex, 4),
                    "background_bundle_relevance": round(bundle_relevance, 4),
                    "background_helped": background_cos > baseline_cos,
                    "background_hurt": background_cos < baseline_cos,
                }
            )
            print(
                f"[{i}/{total}] chunk={chunk_id} "
                f"bg_edges={len(bg_rows)} "
                f"base={baseline_cos:.4f} with_bg={background_cos:.4f} delta={delta_cos:+.4f}"
            )

    driver.close()

    coverage = mean([1.0 if r["background_edge_count"] > 0 else 0.0 for r in out_rows])
    avg_baseline = mean([r["baseline_embedding_cosine"] for r in out_rows])
    avg_background = mean([r["background_embedding_cosine"] for r in out_rows])
    avg_delta = mean([r["delta_embedding_cosine"] for r in out_rows])
    avg_positive_delta = mean([max(r["delta_embedding_cosine"], 0.0) for r in out_rows])
    avg_bundle_relevance = mean([r["background_bundle_relevance"] for r in out_rows])
    improved_rate = mean([1.0 if r["background_helped"] else 0.0 for r in out_rows])
    hurt_rate = mean([1.0 if r["background_hurt"] else 0.0 for r in out_rows])

    composite_score = 100.0 * clamp01(
        (0.45 * avg_background) +
        (0.20 * coverage) +
        (0.20 * avg_bundle_relevance) +
        (0.15 * avg_positive_delta)
    )

    summary = {
        "total_chunks": len(out_rows),
        "coverage": round(coverage, 4),
        "avg_baseline_embedding_cosine": round(avg_baseline, 4),
        "avg_background_embedding_cosine": round(avg_background, 4),
        "avg_delta_embedding_cosine": round(avg_delta, 4),
        "avg_positive_delta_embedding_cosine": round(avg_positive_delta, 4),
        "avg_background_bundle_relevance": round(avg_bundle_relevance, 4),
        "improved_rate": round(improved_rate, 4),
        "hurt_rate": round(hurt_rate, 4),
        "background_retrieval_utility_score": round(composite_score, 2),
        "score_formula": "100 * (0.45*avg_background_embedding_cosine + 0.20*coverage + 0.20*avg_background_bundle_relevance + 0.15*avg_positive_delta_embedding_cosine)",
        "model": args.model,
        "embedding_model": embedding_model,
    }

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps({"summary": summary, "rows": out_rows}, indent=2),
        encoding="utf-8",
    )
    print(f"\nSummary: {summary}")
    print(f"Saved background retrieval evaluation to {out_path}")


if __name__ == "__main__":
    main()
