import argparse
import json
from pathlib import Path
from collections import Counter

def norm_concept(s: str) -> str:
    return " ".join(s.strip().lower().split())

def main():
    parser = argparse.ArgumentParser(description="Build dedup concept list + mentions edges from extraction output.")
    parser.add_argument("--in", dest="in_path", required=True, help="Input extractions JSON (key 'extractions').")
    parser.add_argument("--concepts-out", required=True, help="Output concepts JSON.")
    parser.add_argument("--mentions-out", required=True, help="Output mentions JSON.")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    out_concepts = Path(args.concepts_out)
    out_mentions = Path(args.mentions_out)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    extractions = data["extractions"]

    concept_counts = Counter()
    mentions = []
    seen_edges = set()

    for row in extractions:
        if "error" in row:
            continue

        chunk_id = row["chunk_id"]
        llm = row["llm"]
        concepts = llm.get("concepts", [])

        for c in concepts:
            c_norm = norm_concept(c)
            if not c_norm:
                continue

            concept_counts[c_norm] += 1

            edge = (chunk_id, c_norm)
            if edge in seen_edges:
                continue
            seen_edges.add(edge)

            mentions.append({
                "from_chunk_id": chunk_id,
                "to_concept": c_norm,
                "confidence": llm.get("confidence", 0.5),
                "unit_kind": llm.get("unit_kind", "other"),
                "layer": llm.get("layer", "support"),
            })

    concepts_out = [{"id": c, "label": c, "count": concept_counts[c]} for c in sorted(concept_counts.keys())]

    out_concepts.write_text(json.dumps({"concepts": concepts_out}, indent=2), encoding="utf-8")
    out_mentions.write_text(json.dumps({"mentions": mentions}, indent=2), encoding="utf-8")

    print(f"Wrote concepts: {out_concepts} ({len(concepts_out)} unique)")
    print(f"Wrote mentions: {out_mentions} ({len(mentions)} edges)")

if __name__ == "__main__":
    main()
