import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_ollama import ChatOllama, OllamaEmbeddings


def norm_ws(s: str) -> str:
    return " ".join((s or "").split())


def tokenize(s: str) -> List[str]:
    # simple, offline tokenizer (no extra deps)
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    toks = [t for t in s.split() if t]
    return toks


def jaccard(a: str, b: str) -> float:
    A = set(tokenize(a))
    B = set(tokenize(b))
    if not A and not B:
        return 1.0
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def cosine_bow(a: str, b: str) -> float:
    # bag-of-words cosine using Counter
    ca = Counter(tokenize(a))
    cb = Counter(tokenize(b))
    if not ca and not cb:
        return 1.0
    if not ca or not cb:
        return 0.0

    # dot product
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


def build_prompt(
    unit_kind: str,
    layer: str,
    concepts: List[str],
    relations: Optional[Dict[str, Any]] = None,
) -> str:
    # High-level instruction: reconstruct meaning, not exact wording.
    base = (
        "You are reconstructing the likely original text of a short chunk from its compressed knowledge representation.\n"
        "Write only the likely chunk content itself, not commentary about the task.\n"
        "Do not say things like 'the compressed representation', 'the original chunk', 'this suggests', or 'based on the information provided'.\n"
        "Do not mention missing context or uncertainty unless the provided information is genuinely fragmentary.\n"
        "Preserve the chunk's likely function when possible, such as definition, example, navigation note, metadata, or scaffolding.\n"
        "Use only the information provided. Do not invent facts. Keep it 1-2 sentences.\n\n"
        f"unit_kind: {unit_kind}\n"
        f"layer: {layer}\n"
        f"concepts: {', '.join(concepts) if concepts else '(none)'}\n"
    )

    if relations is not None:
        # relations schema from outputs/*_relations.json created by extract_epistemic_relations.py
        defines = relations.get("defines", [])
        part_of = relations.get("part_of", [])
        causes = relations.get("causes", [])

        base += "\nrelations:\n"
        base += f"- defines: {defines if defines else []}\n"
        base += f"- part_of: {part_of if part_of else []}\n"
        base += f"- causes: {causes if causes else []}\n"

    base += (
        "\nReturn ONLY the reconstructed text as plain prose."
        "\nBad style example: 'The compressed representation describes a concept related to neuroscience.'"
        "\nGood style example: 'The hippocampus supports episodic memory formation and spatial navigation.'"
    )
    return base


def main():
    p = argparse.ArgumentParser(description="Compressed Knowledge Reconstruction validator (offline).")
    p.add_argument("--extractions", required=True, help="Path to extractions JSON (key: 'extractions').")
    p.add_argument("--relations", default="", help="Optional relations JSON (key: 'relations').")
    p.add_argument("--out", required=True, help="Output JSON with reconstructions + similarity scores.")
    p.add_argument("--model", default="llama3.2:3b", help="Ollama chat model for reconstruction.")
    p.add_argument(
        "--embedding-model",
        default="",
        help="Ollama embedding model. Defaults to the chat model name if omitted.",
    )
    p.add_argument("--limit", type=int, default=0, help="Process only first N rows (0=all).")
    p.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Pass/fail threshold for embedding cosine similarity.",
    )
    args = p.parse_args()

    ext_path = Path(args.extractions)
    out_path = Path(args.out)

    ext_data = json.loads(ext_path.read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = ext_data.get("extractions", [])
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    # Optional relations lookup by chunk_id
    rel_map: Dict[str, Dict[str, Any]] = {}
    if args.relations:
        rpath = Path(args.relations)
        if rpath.exists():
            rel_rows = json.loads(rpath.read_text(encoding="utf-8")).get("relations", [])
            for r in rel_rows:
                if "error" in r:
                    continue
                cid = r.get("chunk_id")
                rels = r.get("relations", {})
                if cid and isinstance(rels, dict):
                    rel_map[cid] = rels

    llm = ChatOllama(model=args.model, temperature=0)
    embedding_model = args.embedding_model or args.model
    embeddings = OllamaEmbeddings(model=embedding_model)

    out_rows = []
    total = len(rows)

    for i, r in enumerate(rows, start=1):
        chunk_id = r.get("chunk_id", f"chunk_{i:04d}")
        original = norm_ws(r.get("text", ""))

        if "error" in r:
            out_rows.append({"chunk_id": chunk_id, "error": r["error"]})
            continue

        llm_block = r.get("llm", {}) or {}
        unit_kind = llm_block.get("unit_kind", "other")
        layer = llm_block.get("layer", "support")
        concepts = llm_block.get("concepts", []) or []
        # normalize concepts (light)
        concepts = [norm_ws(str(c)).lower() for c in concepts if norm_ws(str(c))]

        rels = rel_map.get(chunk_id) if rel_map else None
        prompt = build_prompt(unit_kind=unit_kind, layer=layer, concepts=concepts, relations=rels)

        try:
            resp = llm.invoke(prompt)
            reconstructed = norm_ws(getattr(resp, "content", str(resp)))

            # Lexical diagnostics
            jac = jaccard(original, reconstructed)
            bow_cos = cosine_bow(original, reconstructed)

            # Semantic validation signal
            original_vec = embeddings.embed_query(original)
            reconstructed_vec = embeddings.embed_query(reconstructed)
            emb_cos = cosine_dense(original_vec, reconstructed_vec)
            lexical_combined = float((jac + bow_cos) / 2.0)
            passed = emb_cos >= args.threshold

            out_rows.append(
                {
                    "chunk_id": chunk_id,
                    "unit_kind": unit_kind,
                    "layer": layer,
                    "concepts": concepts,
                    "used_relations": bool(rels),
                    "original": original,
                    "reconstructed": reconstructed,
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
    }

    out_path.write_text(json.dumps({"summary": summary, "results": out_rows}, indent=2), encoding="utf-8")
    print(f"Saved reconstruction results to {out_path}")
    print("Summary:", summary)


if __name__ == "__main__":
    main()
