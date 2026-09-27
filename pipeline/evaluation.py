"""One final reconstruction evaluation; descriptive statistics, no comparisons."""
from collections import Counter
import math
import re
import statistics

from pydantic import Field
from .extraction import Record


class Reconstruction(Record):
    text: str = Field(min_length=1)
    reason: str = Field(min_length=1)


def tokens(text):
    return re.findall(r"\w+", text.casefold())


def cosine(a, b):
    if len(a) != len(b):
        raise ValueError("Embedding dimension mismatch")
    denominator = math.sqrt(sum(v*v for v in a) * sum(v*v for v in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0.0


def metrics(original, reconstructed, a, b):
    left, right = Counter(tokens(original)), Counter(tokens(reconstructed))
    union = set(left) | set(right)
    return {"semantic_cosine": cosine(a, b),
            "token_jaccard": len(set(left) & set(right)) / len(union) if union else 1.0,
            "token_cosine": cosine([left[k] for k in sorted(union)], [right[k] for k in sorted(union)])}


def evaluate(chunks, graph, models, trace):
    results = []
    by_id = {n["id"]: n for n in graph["nodes"]}
    for chunk in chunks:
        print(f"  Evaluating {chunk['id']}", flush=True)
        # Exclude source chunks, paragraphs and evidence; use extracted claims.
        claims = [n["text"] for n in graph["nodes"] if n["kind"] == "statement" and n["chunk_id"] == chunk["id"]]
        concepts = [by_id[e["target"]]["label"] for e in graph["edges"]
                    if e["source"] == chunk["id"] and e["label"] == "mentions"]
        relations = [{"source": by_id[e["source"]]["label"], "relation": e["label"],
                      "target": by_id[e["target"]]["label"], "origin": e["origin"]}
                     for e in graph["edges"] if by_id[e["source"]]["kind"] == "concept"
                     and by_id[e["target"]]["kind"] == "concept"
                     and (e.get("chunk_id") == chunk["id"] or
                          (e["origin"] == "background" and by_id[e["source"]]["label"] in concepts))]
        context = {"claims": claims, "concepts": concepts, "relations": relations}
        trace.emit("evaluation.context_built", entity_id=chunk["id"], context=context)
        result = models.ask("reconstructor",
            "Reconstruct one coherent passage using only the supplied final graph. Preserve the document "
            "claims and their qualifications. Background relations may clarify concepts but must not be "
            "presented as document assertions. Do not invent missing facts.", context, Reconstruction, chunk["id"])
        scores = metrics(chunk["text"], result.text, models.embed(chunk["text"], chunk["id"]),
                         models.embed(result.text, chunk["id"]))
        trace.emit("evaluation.metrics_computed", entity_id=chunk["id"], **scores)
        results.append({"chunk_id": chunk["id"], "original": chunk["text"], "reconstruction": result.text,
                        "reason": result.reason, **scores})
    summary = {}
    for key in ("semantic_cosine", "token_jaccard", "token_cosine"):
        values = [r[key] for r in results]
        summary[key] = {"n": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
                        "min": min(values), "max": max(values),
                        "sample_stddev": statistics.stdev(values) if len(values) > 1 else None}
    trace.emit("evaluation.summary_computed", summary=summary)
    return {"results": results, "summary": summary,
            "interpretation": "Reconstruction similarity, not factual accuracy. The same model serves all roles; "
                              "debate judgments are not independent verification. No significance tests on one document."}
