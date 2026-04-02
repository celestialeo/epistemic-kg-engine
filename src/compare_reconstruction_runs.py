import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def get_generated_text(row: Dict[str, Any]) -> str:
    return row.get("reconstructed") or row.get("regenerated") or ""


def load_rows(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in data.get("results", []) if "scores" in row]


def summarize(rows: List[Dict[str, Any]], threshold: float) -> Dict[str, float]:
    if not rows:
        return {
            "count": 0,
            "avg_embedding": 0.0,
            "avg_lexical": 0.0,
            "pass_rate": 0.0,
            "near_threshold": 0.0,
        }

    emb = [row["scores"]["embedding_cosine"] for row in rows]
    lex = [row["scores"]["lexical_combined"] for row in rows]
    passed = sum(score >= threshold for score in emb)
    near = sum(abs(score - threshold) <= 0.05 for score in emb)

    return {
        "count": len(rows),
        "avg_embedding": sum(emb) / len(emb),
        "avg_lexical": sum(lex) / len(lex),
        "pass_rate": passed / len(rows),
        "near_threshold": near,
    }


def print_side_by_side(
    left_name: str,
    left_rows: List[Dict[str, Any]],
    right_name: str,
    right_rows: List[Dict[str, Any]],
    threshold: float,
) -> None:
    # Compare two graph-facing representations by the fidelity of their regenerated chunks.
    left = summarize(left_rows, threshold)
    right = summarize(right_rows, threshold)

    print(f"Threshold: {threshold:.2f}")
    print(f"{'Metric':<18}{left_name:<20}{right_name:<20}{'Delta':<12}")
    print("-" * 70)

    metrics = [
        ("count", "count"),
        ("avg_embedding", "avg_embedding"),
        ("avg_lexical", "avg_lexical"),
        ("pass_rate", "pass_rate"),
        ("near_threshold", "near_threshold"),
    ]

    for label, key in metrics:
        lval = left[key]
        rval = right[key]
        if key in {"count", "near_threshold"}:
            print(f"{label:<18}{int(lval):<20}{int(rval):<20}{(rval - lval):<12.0f}")
        else:
            print(f"{label:<18}{lval:<20.3f}{rval:<20.3f}{(rval - lval):<12.3f}")

    print("\nChunk-level embedding changes:")
    by_id = {row["chunk_id"]: row for row in left_rows}
    paired = []
    for row in right_rows:
        chunk_id = row["chunk_id"]
        if chunk_id in by_id:
            paired.append(
                (
                    row["scores"]["embedding_cosine"] - by_id[chunk_id]["scores"]["embedding_cosine"],
                    chunk_id,
                    by_id[chunk_id]["scores"]["embedding_cosine"],
                    row["scores"]["embedding_cosine"],
                )
            )

    for delta, chunk_id, lscore, rscore in sorted(paired, reverse=True)[:10]:
        print(f"{chunk_id}: {lscore:.3f} -> {rscore:.3f} ({delta:+.3f})")


def print_demo_cases(
    left_rows: List[Dict[str, Any]],
    right_rows: List[Dict[str, Any]],
    threshold: float,
) -> None:
    # Surface a few interpretable cases for manual inspection of graph fidelity.
    left_by_id = {row["chunk_id"]: row for row in left_rows}
    right_by_id = {row["chunk_id"]: row for row in right_rows}
    shared_ids = [chunk_id for chunk_id in right_by_id if chunk_id in left_by_id]

    improved_passes = []
    borderline = []
    suspicious_passes = []

    for chunk_id in shared_ids:
        left = left_by_id[chunk_id]
        right = right_by_id[chunk_id]
        lscore = left["scores"]["embedding_cosine"]
        rscore = right["scores"]["embedding_cosine"]
        delta = rscore - lscore

        if lscore < threshold <= rscore:
            improved_passes.append((delta, chunk_id, left, right))
        if abs(rscore - threshold) <= 0.03 or abs(lscore - threshold) <= 0.03:
            borderline.append((min(abs(rscore - threshold), abs(lscore - threshold)), chunk_id, left, right))
        if rscore >= threshold and right["scores"]["lexical_combined"] < 0.2:
            suspicious_passes.append((right["scores"]["lexical_combined"], chunk_id, right))

    print("\nDemo cases:")

    if improved_passes:
        delta, chunk_id, left, right = sorted(improved_passes, reverse=True)[0]
        print(f"\nBest relation-driven improvement: {chunk_id}")
        print(
            f"baseline={left['scores']['embedding_cosine']:.3f} "
            f"candidate={right['scores']['embedding_cosine']:.3f} delta={delta:+.3f}"
        )
        print(f"original: {right['original']}")
        print(f"baseline output: {get_generated_text(left)}")
        print(f"with relations output: {get_generated_text(right)}")

    if borderline:
        _, chunk_id, left, right = sorted(borderline)[0]
        print(f"\nBorderline threshold case: {chunk_id}")
        print(
            f"baseline={left['scores']['embedding_cosine']:.3f} "
            f"candidate={right['scores']['embedding_cosine']:.3f}"
        )
        print(f"original: {right['original']}")
        print(f"baseline output: {get_generated_text(left)}")
        print(f"with relations output: {get_generated_text(right)}")

    if suspicious_passes:
        _, chunk_id, right = sorted(suspicious_passes)[0]
        print(f"\nSuspicious semantic pass to inspect: {chunk_id}")
        print(
            f"embedding={right['scores']['embedding_cosine']:.3f} "
            f"lexical={right['scores']['lexical_combined']:.3f}"
        )
        print(f"original: {right['original']}")
        print(f"with relations output: {get_generated_text(right)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare two graph-fidelity runs based on regenerated chunk outputs."
    )
    parser.add_argument("--baseline", required=True, help="Path to baseline reconstruction/regeneration JSON.")
    parser.add_argument("--candidate", required=True, help="Path to candidate reconstruction/regeneration JSON.")
    parser.add_argument("--threshold", type=float, default=0.70, help="Embedding pass threshold.")
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)
    baseline_rows = load_rows(baseline_path)
    candidate_rows = load_rows(candidate_path)

    print_side_by_side(
        baseline_path.stem,
        baseline_rows,
        candidate_path.stem,
        candidate_rows,
        args.threshold,
    )
    print_demo_cases(baseline_rows, candidate_rows, args.threshold)


if __name__ == "__main__":
    main()
