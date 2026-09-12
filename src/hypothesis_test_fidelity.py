import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from scipy.stats import ttest_rel, wilcoxon


def load_rows(path: Path) -> Dict[str, Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["chunk_id"]: row
        for row in data.get("results", [])
        if "scores" in row and not row.get("bypass_llm", False)
    }


def paired_vectors(
    a: Dict[str, Dict[str, Any]],
    b: Dict[str, Dict[str, Any]],
    unit_kind: str | None = None,
) -> Tuple[List[str], List[float], List[float]]:
    shared = sorted(set(a) & set(b))
    if unit_kind is not None:
        shared = [cid for cid in shared if a[cid].get("unit_kind", "other") == unit_kind]
    return (
        shared,
        [a[cid]["scores"]["embedding_cosine"] for cid in shared],
        [b[cid]["scores"]["embedding_cosine"] for cid in shared],
    )


def run_test(
    baseline_rows: Dict[str, Dict[str, Any]],
    candidate_rows: Dict[str, Dict[str, Any]],
    alternative: str,
    unit_kind: str | None = None,
) -> None:
    shared, baseline_vec, candidate_vec = paired_vectors(baseline_rows, candidate_rows, unit_kind=unit_kind)

    label = unit_kind or "all"
    print(f"\n[{label}]")

    if not shared:
        print("No shared chunk_ids for this subset.")
        return

    deltas = [cand - base for base, cand in zip(baseline_vec, candidate_vec)]
    mean_delta = sum(deltas) / len(deltas)
    improved = sum(d > 0 for d in deltas)
    worsened = sum(d < 0 for d in deltas)
    tied = sum(d == 0 for d in deltas)

    print(f"Shared chunk_ids: {len(shared)}")
    print(f"Mean delta (candidate - baseline): {mean_delta:.4f}")
    print(f"Improved: {improved} | Worsened: {worsened} | Tied: {tied}")

    if len(shared) < 2 or all(d == 0 for d in deltas):
        print("Not enough variation for paired statistical testing.")
        return

    t_stat, t_p = ttest_rel(candidate_vec, baseline_vec, alternative=alternative)
    try:
        w_stat, w_p = wilcoxon(candidate_vec, baseline_vec, alternative=alternative, zero_method="wilcox")
    except ValueError:
        w_stat, w_p = float("nan"), float("nan")

    print()
    print("Paired t-test")
    print(f"  statistic={t_stat:.4f} p_value={t_p:.6f}")
    print("Wilcoxon signed-rank test")
    print(f"  statistic={w_stat:.4f} p_value={w_p:.6f}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run paired statistical tests on chunk-level graph-fidelity embedding scores."
    )
    parser.add_argument("--baseline", required=True, help="Path to baseline JSON results file.")
    parser.add_argument("--candidate", required=True, help="Path to candidate JSON results file.")
    parser.add_argument(
        "--alternative",
        choices=["two-sided", "greater", "less"],
        default="two-sided",
        help="Alternative hypothesis for candidate vs baseline.",
    )
    parser.add_argument(
        "--by-unit-kind",
        action="store_true",
        help="If set, also run the paired tests separately for each unit_kind.",
    )
    args = parser.parse_args()

    baseline_rows = load_rows(Path(args.baseline))
    candidate_rows = load_rows(Path(args.candidate))
    run_test(baseline_rows, candidate_rows, args.alternative)

    if args.by_unit_kind:
        unit_kinds = sorted(
            {
                row.get("unit_kind", "other")
                for row in baseline_rows.values()
            }
        )
        for unit_kind in unit_kinds:
            run_test(baseline_rows, candidate_rows, args.alternative, unit_kind=unit_kind)


if __name__ == "__main__":
    main()
