import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple


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
        }

    emb = [row["scores"]["embedding_cosine"] for row in rows]
    lex = [row["scores"]["lexical_combined"] for row in rows]
    passed = sum(score >= threshold for score in emb)
    return {
        "count": len(rows),
        "avg_embedding": sum(emb) / len(emb),
        "avg_lexical": sum(lex) / len(lex),
        "pass_rate": passed / len(rows),
    }


def parse_run_arg(value: str) -> Tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Each --run must look like label=path/to/file.json")
    label, path = value.split("=", 1)
    label = label.strip()
    path = Path(path.strip())
    if not label:
        raise argparse.ArgumentTypeError("Run label cannot be empty.")
    return label, path


def print_overall(run_rows: Dict[str, List[Dict[str, Any]]], threshold: float) -> None:
    print("OVERALL")
    print(f"{'run':<18}{'rows':<8}{'pass_rate':<12}{'avg_embed':<12}{'avg_lex':<12}")
    print("-" * 62)
    for label, rows in run_rows.items():
        s = summarize(rows, threshold)
        print(
            f"{label:<18}{s['count']:<8}{s['pass_rate']:<12.3f}"
            f"{s['avg_embedding']:<12.3f}{s['avg_lexical']:<12.3f}"
        )


def print_best_condition_per_chunk(run_rows: Dict[str, List[Dict[str, Any]]]) -> None:
    row_maps = {label: {row["chunk_id"]: row for row in rows} for label, rows in run_rows.items()}
    shared_ids = sorted(set.intersection(*(set(m.keys()) for m in row_maps.values())))
    counts = {label: 0 for label in run_rows}

    for chunk_id in shared_ids:
        scores = {
            label: row_maps[label][chunk_id]["scores"]["embedding_cosine"]
            for label in run_rows
        }
        best_label = max(scores, key=scores.get)
        counts[best_label] += 1

    print("\nBEST CONDITION PER CHUNK")
    for label, count in counts.items():
        print(f"{label}: {count}")


def print_by_unit_kind(run_rows: Dict[str, List[Dict[str, Any]]], threshold: float) -> None:
    unit_kinds = sorted(
        {
            row.get("unit_kind", "other")
            for rows in run_rows.values()
            for row in rows
        }
    )

    print("\nBY UNIT KIND")
    for unit_kind in unit_kinds:
        print(f"\n[{unit_kind}]")
        print(f"{'run':<18}{'rows':<8}{'pass_rate':<12}{'avg_embed':<12}{'avg_lex':<12}")
        print("-" * 62)
        for label, rows in run_rows.items():
            subset = [row for row in rows if row.get("unit_kind", "other") == unit_kind]
            s = summarize(subset, threshold)
            print(
                f"{label:<18}{s['count']:<8}{s['pass_rate']:<12.3f}"
                f"{s['avg_embedding']:<12.3f}{s['avg_lexical']:<12.3f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare multiple graph-fidelity or reconstruction runs, with optional chunk-type breakdown."
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        help="Run spec in the form label=path/to/file.json. Repeat for multiple runs.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="Embedding pass threshold.",
    )
    parser.add_argument(
        "--by-unit-kind",
        action="store_true",
        help="If set, print a breakdown by unit_kind.",
    )
    args = parser.parse_args()

    parsed_runs = [parse_run_arg(value) for value in args.run]
    run_rows = {label: load_rows(path) for label, path in parsed_runs}

    print_overall(run_rows, args.threshold)
    print_best_condition_per_chunk(run_rows)
    if args.by_unit_kind:
        print_by_unit_kind(run_rows, args.threshold)


if __name__ == "__main__":
    main()
