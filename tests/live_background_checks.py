"""Opt-in live positive/negative controls; never imported by production code.

Run with python -m tests.live_background_checks SOURCE_RUN.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from pipeline.debate import check_novelty, check_representation, review_background_many
from pipeline.models import Models
from pipeline.replay_background import load_document
from pipeline.trace import Trace


def main():
    source = Path(sys.argv[1]).resolve()
    config = json.loads((source / "manifest.json").read_text(encoding="utf-8"))["config"]
    identifier = "controls_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    trace = Trace(Path("outputs/background_replays") / identifier, identifier)
    models = Models(trace, config["model"], config["embedding_model"],
                    os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
                    context_tokens=config["context_tokens"], max_output_tokens=config["max_output_tokens"],
                    think=True if "--think" in sys.argv else config.get("think", False), batch_size=config.get("batch_size", 4))
    chunks, _, outline, concepts, relations, facts = load_document(source, models, trace)
    cases = [
        ("false_precision", "Quantization always increases the numerical precision of model parameters.",
         "quantization", "increases", "numerical precision", "SOURCE increases TARGET.", "always", "debate", False),
        ("false_guarantee", "Regularization guarantees perfect predictions on all unseen data.",
         "regularization", "guarantees", "perfect predictions", "SOURCE guarantees TARGET.", "on all unseen data", "debate", False),
        ("false_invariance", "Permuting input tokens leaves the entire ordered sequence of self-attention outputs numerically identical, without positional information.",
         "self attention", "produces", "numerically identical ordered output sequence", "SOURCE produces TARGET.", "without positional information, when input tokens are permuted", "debate", False),
        ("true_chain_rule", "Backpropagation uses the chain rule to compute derivatives of composed functions.",
         "backpropagation", "uses", "chain rule", "SOURCE employs TARGET.", "to compute derivatives of composed functions", "debate", True),
        ("unknown_case_choice", "The small transformer in the supplied chapter uses dropout.",
         "small transformer", "uses", "dropout", "SOURCE employs TARGET.", "in the supplied chapter", "debate", False),
        ("paraphrase_duplicate", "Regularization helps models generalize beyond their training examples.",
         "regularization", "enables", "generalization beyond training example", "SOURCE permits TARGET.", None, "novelty", False),
        ("inverse_duplicate", "Model memory requirements are reduced by quantization.",
         "memory requirement", "is_reduced_by", "quantization", "TARGET decreases SOURCE.", None, "novelty", False),
        ("new_mechanism", "Quantization can reduce storage by representing parameters with fewer bits.",
         "quantization", "reduces", "memory requirement", "SOURCE decreases TARGET.", "by representing parameters with fewer bits", "novelty", True),
        ("wrong_named_contract", "Backpropagation uses the chain rule.",
         "chain rule", "causes", "backpropagation", "SOURCE is employed by TARGET.", None, "representation", False),
    ]
    if len(sys.argv) > 2:
        selected = set(sys.argv[2:]) - {"--think"}
        if not selected <= {case[0] for case in cases}:
            raise ValueError("Unknown live control name")
        cases = [case for case in cases if case[0] in selected]
    results = []
    try:
        for name, sentence, start, predicate, end, contract, conditions, stage, expected in cases:
            print(name, flush=True)
            for concept in (start, end):
                concepts.entries.setdefault(concept, dict(name=concept, definition=concept, kind="abstract", form="concept"))
            relations.entries.setdefault(predicate, dict(key=predicate, definition=contract, inverse=None, symmetric=False))
            row = dict(id=name, seed_id=name, source=start, target=end, relation=predicate,
                       relation_definition=contract, conditions=conditions, modality="assertion",
                       intended_fact=sentence, link_reading=sentence, reason=sentence,
                       origin="background", chunk_id=chunks[0]["id"], accepted=False, review_status="pending",
                       source_mention=concepts.entries[start], target_mention=concepts.entries[end],
                       source_context=[dict(id=chunk["id"], text=chunk["text"]) for chunk in chunks],
                       gaps=[dict(id="gap", question="How does this mechanism work, and what are its limitations?")],
                       case_specific_unknowns=[], gap_ids=["gap"])
            if stage == "novelty":
                result = check_novelty(row, chunks, facts, models, trace)
                row["novelty"] = result
                actual = result["status"] == "new"
                passed = actual == expected and result["status"] in ("new", "duplicate")
            elif stage == "representation":
                row["relation"] = relations.resolve_background(predicate, contract, start, end, {}, name)
                row["relation_definition"] = relations.entries[row["relation"]]["definition"]
                actual = check_representation(row, models, trace)
                passed = actual == expected
            else:
                # A false claim can be represented correctly. Truth must be
                # rejected by the critic/proposer/judge, not hidden by bad syntax.
                represented = check_representation(row, models, trace)
                if represented:
                    review_background_many([row], {c["id"]: c for c in chunks}, outline, concepts, models, trace)
                actual = row["accepted"]
                passed = represented and actual == expected and row["review_status"] != "unresolved"
                row["representation_passed"] = represented
            results.append(dict(case=name, stage=stage, expected=expected, actual=actual, passed=passed, candidate=row))
            trace.save("controls.json", results)
        print(json.dumps(dict(output=str(trace.directory), passed=sum(r["passed"] for r in results), total=len(results)), indent=2))
    finally:
        trace.close()
    if not all(r["passed"] for r in results):
        raise SystemExit("Live background controls failed; inspect controls.json")


if __name__ == "__main__":
    main()
