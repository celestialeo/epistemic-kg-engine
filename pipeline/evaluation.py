"""Reconstruction fidelity: claims, idea order, ROUGE-L and length."""
import re
import statistics

from pydantic import Field
from .records import Record
from .models import ModelResponseError, ModelServiceError
from .health import finish_item


METRIC_WEIGHTS = {
    "claim_fidelity_f1": 0.55,
    "idea_order_agreement": 0.25,
    "rouge_l_f1": 0.10,
    "length_similarity": 0.10,
}
METRIC_KEYS = (*METRIC_WEIGHTS, "final_score")
METRIC_VERSION = "reconstruction_fidelity_v1"


class Reconstruction(Record):
    text: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EvaluationClaim(Record):
    text: str = Field(min_length=1)
    evidence: str = Field(min_length=1, description="Exact continuous quote from the supplied text")


class OrderedClaims(Record):
    claims: list[EvaluationClaim]


class ClaimMatch(Record):
    original_index: int = Field(ge=0, strict=True)
    reconstructed_index: int = Field(ge=0, strict=True)
    reason: str = Field(min_length=1)


class ClaimAlignment(Record):
    matches: list[ClaimMatch]


def tokens(text):
    """Case-insensitive Unicode word tokens; no stemming, punctuation ignored."""
    return re.findall(r"\w+", text.casefold())


def rouge_l_f1(original, reconstructed):
    """Whole-passage LCS F1, using linear memory (not sentence-union ROUGE-Lsum)."""
    left, right = tokens(original), tokens(reconstructed)
    if not left or not right:
        return float(not left and not right)
    if len(left) < len(right):
        left, right = right, left
    row = [0] * (len(right) + 1)
    for word in left:
        diagonal = 0
        for index, other in enumerate(right, 1):
            previous = row[index]
            row[index] = diagonal + 1 if word == other else max(row[index], row[index - 1])
            diagonal = previous
    return 2 * row[-1] / (len(left) + len(right))


def validate_matches(matches, original_count, reconstructed_count):
    """Reject reused or out-of-range claims instead of inflating match counts."""
    original_seen, reconstructed_seen = set(), set()
    for match in matches:
        left, right = match.original_index, match.reconstructed_index
        if not (0 <= left < original_count and 0 <= right < reconstructed_count):
            raise ValueError("Claim match index outside the supplied claim lists")
        if left in original_seen or right in reconstructed_seen:
            raise ValueError("Claim alignment must be one-to-one")
        original_seen.add(left)
        reconstructed_seen.add(right)


def metrics(original, reconstructed, original_claims, reconstructed_claims, matches):
    """Score ordered atomic claims and semantic matches without model calls.

    Components use [0, 1]; final_score uses [0, 100]. A single preserved
    idea has no possible inversion and gets order=1. No matches gets order=0,
    except when both claim lists are empty (vacuous agreement).
    """
    matches = list(matches)
    left_count, right_count = len(original_claims), len(reconstructed_claims)
    validate_matches(matches, left_count, right_count)
    matched = len(matches)
    empty = left_count == right_count == 0
    precision = matched / right_count if right_count else float(empty)
    recall = matched / left_count if left_count else float(empty)
    fidelity = 2 * matched / (left_count + right_count) if not empty else 1.0
    ordered = sorted(matches, key=lambda match: match.original_index)
    pairs = matched * (matched - 1) // 2
    concordant = sum(a.reconstructed_index < b.reconstructed_index
                     for index, a in enumerate(ordered) for b in ordered[index + 1:])
    order = concordant / pairs if pairs else float(matched == 1 or empty)
    # Match the input loader's whitespace-delimited word counts.
    left_words, right_words = len(original.split()), len(reconstructed.split())
    longest = max(left_words, right_words)
    scores = {
        "claim_fidelity_f1": fidelity,
        "idea_order_agreement": order,
        "rouge_l_f1": rouge_l_f1(original, reconstructed),
        "length_similarity": min(left_words, right_words) / longest if longest else 1.0,
    }
    return {
        **scores,
        "final_score": 100 * sum(scores[key] * weight for key, weight in METRIC_WEIGHTS.items()),
        "claim_precision": precision, "claim_recall": recall,
        "original_claim_count": left_count, "reconstructed_claim_count": right_count,
        "matched_claim_count": matched, "ordered_pair_count": pairs,
        "concordant_pair_count": concordant,
        "original_word_count": left_words, "reconstructed_word_count": right_words,
    }


def extract_evaluation_claims(text, models, entity_id):
    if not text.strip():
        return OrderedClaims(claims=[])

    def validate(result):
        position = 0
        for claim in result.claims:
            found = text.find(claim.evidence, position)
            if found < 0:
                raise ValueError("Claim evidence must be an exact quote in source reading order")
            # Several atomic claims can share the same sentence as evidence.
            position = found

    return models.ask("evaluation_claims",
        "Extract every explicitly stated atomic claim from this text in reading order. "
        "Split independently checkable facts and relationships into separate claims. "
        "Preserve participants, relationship direction, quantities, negation, modality, conditions "
        "and other qualifications. Resolve pronouns only from this text. Do not infer facts or add "
        "background knowledge. Include an exact supporting quote for each claim, using the "
        "smallest sufficient span. Keep claims sharing a sentence in their textual order. "
        "Collapse repeated equivalent claims to their first occurrence. Return an empty list "
        "only if the text makes no factual assertions.",
        {"text": text}, OrderedClaims, entity_id, validator=validate)


def compare_texts(original, reconstructed, models, entity_id):
    """Extract each text's claims independently, then align without an order constraint."""
    left = extract_evaluation_claims(original, models, entity_id + ":original")
    right = extract_evaluation_claims(reconstructed, models, entity_id + ":reconstructed")
    alignment = ClaimAlignment(matches=[])
    if left.claims and right.claims:
        alignment = models.ask("evaluation_alignment",
            "Find the maximum set of one-to-one semantically equivalent atomic claim pairs. "
            "Use zero-based indices. Match paraphrases only when the same fact, relationship "
            "direction, participants, quantities, negation, modality, conditions and qualifications "
            "are preserved. A broader, narrower or contradictory assertion is not an equivalent "
            "claim. Do not use outside knowledge. Leave unsupported claims unmatched. Each index "
            "may occur at most once. Ignore claim order when matching: crossing matches are allowed. "
            "Explain each match briefly.",
            {"original_claims": [c.model_dump() for c in left.claims],
             "reconstructed_claims": [c.model_dump() for c in right.claims]},
            ClaimAlignment, entity_id + ":alignment",
            validator=lambda result: validate_matches(result.matches, len(left.claims), len(right.claims)))
    return {
        **metrics(original, reconstructed, left.claims, right.claims, alignment.matches),
        "original_claims": [c.model_dump() for c in left.claims],
        "reconstructed_claims": [c.model_dump() for c in right.claims],
        "claim_matches": [match.model_dump() for match in alignment.matches],
    }


def reconstruction_context(graph, chunk_id):
    """Project only this chunk's document facts; never serialize source annotations."""
    by_id = {node["id"]: node for node in graph["nodes"]}
    concepts, relations = {}, []
    for edge in graph["edges"]:
        if edge.get("origin") != "document":
            continue
        # Deduplicated document facts can have support in multiple chunks.
        # Read only the support's chunk ID, never its evidence or other text.
        if edge.get("chunk_id") != chunk_id and not any(
                support.get("chunk_id") == chunk_id
                for support in edge.get("supporting_evidence", [])):
            continue
        source, target = by_id[edge["source"]], by_id[edge["target"]]
        if source["kind"] not in {"concept", "event"} or target["kind"] not in {"concept", "event"}:
            continue
        for node in (source, target):
            # Registry definitions can include prose from other chunks. Only
            # endpoint identity and type are needed to interpret these facts.
            concepts[node["id"]] = {key: node[key] for key in
                                    ("id", "label", "kind", "semantic_kind") if key in node}
        relations.append({"source": source["label"], "relation": edge["label"],
                          "target": target["label"], "definition": edge.get("definition"),
                          "conditions": edge.get("conditions"), "modality": edge.get("modality")})
    return {"concepts": list(concepts.values()), "relations": relations}


def evaluate(chunks, graph, models, trace):
    results = []
    chunks = sorted(chunks, key=lambda chunk: chunk["order"])
    for chunk in chunks:
        print(f"  Evaluating {chunk['id']}", flush=True)
        context = reconstruction_context(graph, chunk["id"])
        trace.emit("evaluation.context_built", entity_id=chunk["id"], context=context)
        reconstruction = ""
        reason = "No document relations for this chunk; missing content scored as an empty reconstruction"
        try:
            if context["relations"]:
                result = models.ask("reconstructor",
                    "Reconstruct one coherent passage using only the supplied structured concepts and document "
                    "relations for this chunk. Preserve relation direction, participants, conditions, scope, "
                    "negation and modality. Relation definitions explain predicates; they are not additional "
                    "document assertions. Do not infer facts from concept names alone or use outside knowledge. "
                    "Do not invent missing facts.", context, Reconstruction, chunk["id"])
                reconstruction, reason = result.text, result.reason
            scores = compare_texts(chunk["text"], reconstruction, models, chunk["id"])
        except ModelResponseError as exc:
            results.append(dict(chunk_id=chunk["id"], original=chunk["text"], reconstruction=reconstruction,
                reason=str(exc), status="unresolved", **dict.fromkeys(METRIC_KEYS)))
            trace.save("artifacts/evaluation_progress.json", results)
            finish_item(trace, "evaluation", chunk["id"], exc)
            continue
        trace.emit("evaluation.metrics_computed", entity_id=chunk["id"], **scores)
        results.append({"chunk_id": chunk["id"], "original": chunk["text"], "reconstruction": reconstruction,
                        "reason": reason, "status": "completed", **scores})
        trace.save("artifacts/evaluation_progress.json", results)
        finish_item(trace, "evaluation", chunk["id"])
    summary = {}
    for key in METRIC_KEYS:
        values = [r[key] for r in results if r[key] is not None]
        summary[key] = {"n": len(values), "mean": statistics.mean(values) if values else None,
                        "median": statistics.median(values) if values else None,
                        "min": min(values) if values else None, "max": max(values) if values else None,
                        "sample_stddev": statistics.stdev(values) if len(values) > 1 else None}
    # Chunk means cannot measure cross-chunk claim matches or global idea order.
    document_metrics = None
    document_error = "No chunks supplied" if not results else "One or more chunks could not be evaluated"
    if results and all(row["status"] == "completed" for row in results):
        try:
            document_metrics = compare_texts("\n\n".join(r["original"] for r in results),
                "\n\n".join(r["reconstruction"] for r in results), models, "evaluation:document")
        except (ModelResponseError, ModelServiceError) as exc:
            document_error = str(exc)
            # The graph and per-chunk results already exist. Preserve them and
            # report an incomplete document score if final inference fails.
            finish_item(trace, "evaluation", "evaluation:document", exc)
        else:
            document_error = None
            trace.emit("evaluation.metrics_computed", entity_id="evaluation:document", **document_metrics)
            finish_item(trace, "evaluation", "evaluation:document")
    trace.emit("evaluation.summary_computed", summary=summary)
    return {"results": results, "summary": summary, "document_metrics": document_metrics,
            "final_score": document_metrics["final_score"] if document_metrics else None,
            "status": "completed" if document_metrics else "incomplete", "reason": document_error,
            "metric_version": METRIC_VERSION, "weights": dict(METRIC_WEIGHTS),
            "interpretation": "Model-estimated claim fidelity, idea order, ROUGE-L F1 and word-count similarity. "
                "Components range from 0 to 1; the weighted final score ranges from 0 to 100. "
                "Summary statistics describe chunks; final_score compares the complete texts and is null "
                "when evaluation is incomplete. A single matched idea has order agreement 1; no matches "
                "have order agreement 0 unless both claim lists are empty. Keep evaluator model, prompts "
                "and metric version fixed across runs. These scores are not external factual verification."}
