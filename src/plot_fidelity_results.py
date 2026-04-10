import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_run(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def summarize_by_unit(results: list[dict]) -> dict[str, dict[str, float]]:
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for row in results:
        by_unit[row.get("unit_kind", "other")].append(row)

    out: dict[str, dict[str, float]] = {}
    for unit, rows in by_unit.items():
        embeds = [r["scores"]["embedding_cosine"] for r in rows]
        lexes = [r["scores"]["lexical_combined"] for r in rows]
        passes = [1.0 if r["scores"]["pass"] else 0.0 for r in rows]
        out[unit] = {
            "avg_embed": sum(embeds) / len(embeds),
            "avg_lex": sum(lexes) / len(lexes),
            "pass_rate": sum(passes) / len(passes),
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot overall and by-unit graph fidelity results."
    )
    parser.add_argument(
        "--doc-only",
        default="outputs/testpack_v1_graph_fidelity_doc_only.json",
        help="Path to document-only fidelity JSON.",
    )
    parser.add_argument(
        "--with-background",
        default="outputs/testpack_v1_graph_fidelity_with_background.json",
        help="Path to background-integrated fidelity JSON.",
    )
    parser.add_argument(
        "--out",
        default="outputs/final_fidelity_results.png",
        help="Path to output figure.",
    )
    args = parser.parse_args()

    doc = load_run(Path(args.doc_only))
    bg = load_run(Path(args.with_background))

    doc_summary = doc["summary"]
    bg_summary = bg["summary"]

    doc_units = summarize_by_unit(doc["results"])
    bg_units = summarize_by_unit(bg["results"])

    unit_order = ["definition", "example", "metadata", "navigation"]
    units = [u for u in unit_order if u in doc_units or u in bg_units]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5))

    # Overall comparison
    overall_labels = ["Embedding", "Lexical", "Pass Rate"]
    doc_vals = [
        doc_summary["avg_embedding_cosine"],
        doc_summary["avg_lexical_combined"],
        doc_summary["pass"] / doc_summary["rows"],
    ]
    bg_vals = [
        bg_summary["avg_embedding_cosine"],
        bg_summary["avg_lexical_combined"],
        bg_summary["pass"] / bg_summary["rows"],
    ]
    x = np.arange(len(overall_labels))
    width = 0.36
    axes[0].bar(x - width / 2, doc_vals, width, label="Document-only", color="#7aa6c2")
    axes[0].bar(
        x + width / 2,
        bg_vals,
        width,
        label="With background",
        color="#d98f5f",
    )
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(overall_labels)
    axes[0].set_ylim(0, 1.0)
    axes[0].set_title("Overall Graph Fidelity")
    axes[0].legend(frameon=False)

    # By unit kind (embedding)
    x2 = np.arange(len(units))
    doc_embed = [doc_units[u]["avg_embed"] for u in units]
    bg_embed = [bg_units[u]["avg_embed"] for u in units]
    axes[1].bar(x2 - width / 2, doc_embed, width, color="#7aa6c2")
    axes[1].bar(x2 + width / 2, bg_embed, width, color="#d98f5f")
    axes[1].set_xticks(x2)
    axes[1].set_xticklabels([u.capitalize() for u in units])
    axes[1].set_ylim(0, 1.0)
    axes[1].set_title("Embedding Fidelity by Unit Kind")

    for ax in axes:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.grid(axis="y", linestyle="--", alpha=0.3)

    fig.suptitle(
        "Document-only vs Background-integrated Graph Fidelity",
        fontsize=13,
        y=1.02,
    )
    fig.tight_layout()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=220, bbox_inches="tight")
    print(f"Saved figure to {out_path}")


if __name__ == "__main__":
    main()
