import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def norm_concept(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


def load_extractions(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = load_json(path).get("extractions", [])
    out = {}
    for row in rows:
        if "error" in row:
            continue
        out[row["chunk_id"]] = row
    return out


def load_relations(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = load_json(path).get("relations", [])
    out = {}
    for row in rows:
        if "error" in row or "relations" not in row:
            continue
        out[row["chunk_id"]] = row["relations"]
    return out


def load_fidelity(path: Path) -> Dict[str, Dict[str, Any]]:
    rows = load_json(path).get("results", [])
    return {row["chunk_id"]: row for row in rows if "scores" in row}


def derive_flags(
    fidelity_row: Dict[str, Any],
    extraction_row: Dict[str, Any],
    relations_row: Dict[str, Any] | None,
    threshold: float,
) -> List[str]:
    flags: List[str] = []
    score = fidelity_row["scores"]["embedding_cosine"]
    lexical = fidelity_row["scores"]["lexical_combined"]
    concepts = fidelity_row.get("concepts", [])
    unit_kind = fidelity_row.get("unit_kind", "other")

    if score < threshold:
        flags.append("low_fidelity")
    if score >= threshold and lexical < 0.15:
        flags.append("suspicious_pass_low_lexical")
    if len(concepts) < 3:
        flags.append("sparse_concepts")
    if unit_kind in {"metadata", "navigation", "noise"}:
        flags.append(f"hard_chunk_type:{unit_kind}")

    llm = extraction_row.get("llm", {})
    original_concepts = [norm_concept(c) for c in llm.get("concepts", []) if norm_concept(c)]
    graph_concepts = [norm_concept(c) for c in concepts if norm_concept(c)]
    if sorted(original_concepts) != sorted(graph_concepts):
        flags.append("graph_extraction_concept_mismatch")

    if relations_row is not None:
        rel_count = (
            len(relations_row.get("defines", []))
            + len(relations_row.get("part_of", []))
            + len(relations_row.get("causes", []))
        )
        if rel_count == 0:
            flags.append("no_relations")
        elif rel_count > 4:
            flags.append("relation_dense")

    return flags


def summarize_by_flag(diagnosis_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in diagnosis_rows:
        for flag in row["flags"]:
            counts[flag] = counts.get(flag, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def summarize_by_unit_kind(diagnosis_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    summary: Dict[str, Dict[str, int]] = {}
    for row in diagnosis_rows:
        unit_kind = row["unit_kind"]
        bucket = summary.setdefault(unit_kind, {"rows": 0, "low_fidelity": 0, "suspicious_pass": 0})
        bucket["rows"] += 1
        if "low_fidelity" in row["flags"]:
            bucket["low_fidelity"] += 1
        if "suspicious_pass_low_lexical" in row["flags"]:
            bucket["suspicious_pass"] += 1
    return dict(sorted(summary.items(), key=lambda kv: (-kv[1]["low_fidelity"], kv[0])))


def summarize_root_causes(diagnosis_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    cause_counts = {
        "under_specified_graph": 0,
        "over_dense_relations": 0,
        "hard_chunk_type": 0,
        "metric_prompt_mismatch": 0,
    }
    for row in diagnosis_rows:
        flags = set(row["flags"])
        if "sparse_concepts" in flags or "no_relations" in flags:
            cause_counts["under_specified_graph"] += 1
        if "relation_dense" in flags:
            cause_counts["over_dense_relations"] += 1
        if any(flag.startswith("hard_chunk_type:") for flag in flags):
            cause_counts["hard_chunk_type"] += 1
        if "suspicious_pass_low_lexical" in flags:
            cause_counts["metric_prompt_mismatch"] += 1
    return cause_counts


def print_unit_kind_summary(diagnosis_rows: List[Dict[str, Any]]) -> None:
    print("\nBY UNIT KIND")
    print("============")
    print(f"{'unit_kind':<14}{'rows':<8}{'low_fid':<10}{'suspicious':<12}")
    for unit_kind, stats in summarize_by_unit_kind(diagnosis_rows).items():
        print(
            f"{unit_kind:<14}{stats['rows']:<8}{stats['low_fidelity']:<10}{stats['suspicious_pass']:<12}"
        )


def print_root_cause_summary(diagnosis_rows: List[Dict[str, Any]]) -> None:
    print("\nLIKELY ROOT CAUSES")
    print("==================")
    for cause, count in summarize_root_causes(diagnosis_rows).items():
        print(f"{cause}: {count}")


def print_cases(title: str, rows: List[Dict[str, Any]], limit: int) -> None:
    print(f"\n{title}")
    print("=" * len(title))
    if not rows:
        print("(none)")
        return

    for row in rows[:limit]:
        print(f"\nchunk_id: {row['chunk_id']}")
        print(f"unit_kind: {row['unit_kind']}")
        print(f"embedding: {row['scores']['embedding_cosine']:.3f} | lexical: {row['scores']['lexical_combined']:.3f}")
        print(f"flags: {', '.join(row['flags']) if row['flags'] else '(none)'}")
        print(f"concepts: {row['concepts']}")
        if row.get("relations") is not None:
            print(f"relations: {row['relations']}")
        print(f"original: {row['original']}")
        generated = row.get("regenerated") or row.get("reconstructed") or ""
        print(f"generated: {generated}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose likely upstream graph-representation issues using extraction, relation, and fidelity outputs."
    )
    parser.add_argument("--extractions", required=True, help="Path to extractions JSON.")
    parser.add_argument("--fidelity", required=True, help="Path to graph-fidelity or reconstruction JSON.")
    parser.add_argument("--relations", default="", help="Optional relations JSON for richer diagnosis.")
    parser.add_argument("--threshold", type=float, default=0.70, help="Embedding threshold for low-fidelity cases.")
    parser.add_argument("--limit", type=int, default=5, help="How many cases to print per section.")
    args = parser.parse_args()

    extractions = load_extractions(Path(args.extractions))
    relations = load_relations(Path(args.relations)) if args.relations else {}
    fidelity = load_fidelity(Path(args.fidelity))

    diagnosis_rows: List[Dict[str, Any]] = []
    for chunk_id, fidelity_row in fidelity.items():
        extraction_row = extractions.get(chunk_id)
        if extraction_row is None:
            continue
        relations_row = relations.get(chunk_id) if relations else None
        flags = derive_flags(fidelity_row, extraction_row, relations_row, args.threshold)
        diagnosis_rows.append(
            {
                "chunk_id": chunk_id,
                "unit_kind": fidelity_row.get("unit_kind", "other"),
                "concepts": fidelity_row.get("concepts", []),
                "relations": relations_row,
                "original": fidelity_row.get("original", ""),
                "regenerated": fidelity_row.get("regenerated"),
                "reconstructed": fidelity_row.get("reconstructed"),
                "scores": fidelity_row["scores"],
                "flags": flags,
            }
        )

    diagnosis_rows.sort(key=lambda row: row["scores"]["embedding_cosine"])

    print("DIAGNOSIS SUMMARY")
    print("=================")
    print(f"rows: {len(diagnosis_rows)}")
    print(f"flag_counts: {summarize_by_flag(diagnosis_rows)}")
    print_root_cause_summary(diagnosis_rows)
    print_unit_kind_summary(diagnosis_rows)

    low_fidelity = [row for row in diagnosis_rows if "low_fidelity" in row["flags"]]
    suspicious = [row for row in diagnosis_rows if "suspicious_pass_low_lexical" in row["flags"]]
    dense_rel = [row for row in diagnosis_rows if "relation_dense" in row["flags"]]

    print_cases("Low-fidelity cases", low_fidelity, args.limit)
    print_cases("Suspicious passes", suspicious, args.limit)
    print_cases("Relation-dense cases", dense_rel, args.limit)


if __name__ == "__main__":
    main()
