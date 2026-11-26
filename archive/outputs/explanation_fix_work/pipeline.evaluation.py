from .settings import snapshot
"""Reconstruction fidelity: claims, idea order, ROUGE-L and length."""
import re
import statistics
from collections import deque

from pydantic import Field
from .records import Record
from .models import ModelResponseError, ModelServiceError
from .health import finish_item


METRIC_WEIGHTS = snapshot()["evaluation_weights"]
_weight_sum = sum(METRIC_WEIGHTS.values())
METRIC_WEIGHTS = {key: value / _weight_sum for key, value in METRIC_WEIGHTS.items()}
METRIC_KEYS = (*METRIC_WEIGHTS, "final_score")
METRIC_VERSION = "reconstruction_fidelity_v3_verified_matching"


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


class ContextVerdict(Record):
    reason: str = Field(min_length=1, max_length=400,
                       description="Brief comparison of ONLY the selected claim pair and its relevant context, before deciding the flags")
    participants_preserved: bool
    ownership_preserved: bool
    purpose_preserved: bool
    timing_preserved: bool
    qualifications_preserved: bool
    direction_preserved: bool


CONTEXT_FLAGS = ('participants_preserved', 'ownership_preserved', 'purpose_preserved',
                 'timing_preserved', 'qualifications_preserved', 'direction_preserved')


def context_matches(matches, original, reconstructed, left, right, models, entity_id):
    """Independently reject core-fact matches that lose context. No partial credit as equivalence."""
    accepted, reviews = [], []
    for position, match in enumerate(matches):
        result = models.ask('evaluation_context_review',
            'Independently audit ONLY the selected original_claim and reconstructed_claim as a pair. '
            'Use BOTH complete passages to resolve the relevant context of this pair. An error in another '
            'unrelated assertion does not invalidate this pair; that assertion receives its own comparison. '
            'The passages are evidence for their respective side, not permission to fill gaps in the other. '
            'Resolve pronouns separately in each text. Check the same participant identities and roles, '
            'ownership (whose property/action), purpose versus achieved outcome, timing including shared '
            'scope over coordinated clauses, direction, polarity, uncertainty and other qualifications. '
            'A generic fact without its original actor, owner, goal or temporal scope is not equivalent. '
            'A detail absent from both claims is preserved; an omitted source qualification is not. '
            'Equivalent paraphrases, articles, possessive wording and repetition are not errors when the '
            'referents and actual meaning are unchanged. Do not match merely because the central nouns '
            'and verb agree. Give at most two concise sentences about this pair, then consistent flags.',
            dict(original_passage=original, reconstructed_passage=reconstructed,
                 original_claim=left[match.original_index].text,
                 reconstructed_claim=right[match.reconstructed_index].text),
            ContextVerdict, f'{entity_id}:context:{position}')
        valid = all(getattr(result, flag) for flag in CONTEXT_FLAGS)
        reviews.append({**match.model_dump(), **result.model_dump(), 'accepted': valid,
                        'alignment_reason': match.reason})
        if valid:
            accepted.append(match)
    return accepted, reviews


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


def validate_matches(matches, original_count, reconstructed_count, *, one_to_one=True):
    """Reject reused or out-of-range claims instead of inflating match counts."""
    original_seen, reconstructed_seen = {}, {}
    for match in matches:
        left, right = match.original_index, match.reconstructed_index
        if not (0 <= left < original_count and 0 <= right < reconstructed_count):
            raise ValueError(f"Claim match index outside the supplied claim lists: ({left}, {right}); "
                             f"original indices are 0..{original_count-1}, reconstructed 0..{reconstructed_count-1}")
        if one_to_one and (left in original_seen or right in reconstructed_seen):
            conflicts = []
            if left in original_seen:
                conflicts.append(f"original {left} is already paired with reconstructed {original_seen[left]}")
            if right in reconstructed_seen:
                conflicts.append(f"reconstructed {right} is already paired with original {reconstructed_seen[right]}")
            raise ValueError(f"Claim alignment must be one-to-one: proposed pair ({left}, {right}) conflicts: "
                             + '; '.join(conflicts) + '. Choose only genuinely equivalent pairs without reusing either index.')
        original_seen[left] = right
        reconstructed_seen[right] = left


def select_one_to_one(matches):
    """Maximum-cardinality matching over independently verified pairs only.

    Alternating paths allow a later claim to displace an earlier choice rather
    than losing a valid match through greedy duplicate removal. Iterative search
    avoids recursion limits on long documents. Ordering makes ties reproducible.
    """
    pairs = {}
    for match in matches:
        pairs.setdefault((match.original_index, match.reconstructed_index), match)
    adjacent = {}
    for left, right in sorted(pairs):
        adjacent.setdefault(left, []).append(right)
    left_match, right_match = {}, {}
    for start in sorted(adjacent):
        queue, seen_left, parent_right = deque([start]), {start}, {}
        free = None
        while queue and free is None:
            left = queue.popleft()
            for right in adjacent[left]:
                if right in parent_right:
                    continue
                parent_right[right] = left
                if right not in right_match:
                    free = right
                    break
                other = right_match[right]
                if other not in seen_left:
                    seen_left.add(other)
                    queue.append(other)
        while free is not None:
            left = parent_right[free]
            previous = left_match.get(left)
            left_match[left], right_match[free] = free, left
            free = previous
    return [pairs[(left, right)] for left, right in sorted(left_match.items())]


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
        previous = None
        for index, claim in enumerate(result.claims):
            found = text.find(claim.evidence, position)
            if found < 0:
                prior = (f" Preceding claim: {previous.text!r}; its quote: {previous.evidence!r}."
                         if previous is not None else '')
                raise ValueError(
                    f"Claim evidence must be an exact quote in source reading order. Claim {index}: "
                    f"{claim.text!r}; its quote: {claim.evidence!r} was not found at or after offset {position}."
                    + prior + " Check BOTH claim-to-quote assignments against the supplied text. "
                    "Each quote must support its own claim. Correct the assignments and order, "
                    "preserving every source claim; do not drop claims to satisfy ordering.")
            # Several atomic claims can share the same sentence as evidence.
            position = found
            previous = claim

    return models.ask("evaluation_claims",
        "Extract every explicitly stated atomic claim from this text in reading order. "
        "Split independently checkable facts and relationships into separate claims. "
        "Preserve participants, relationship direction, quantities, negation, modality, conditions "
        "and other qualifications. Explicitly retain whose properties are involved, purpose versus "
        "achieved outcome, and temporal scope shared across coordinated clauses. Resolve pronouns "
        "only from this text; retain the same referent across claims. Do not infer facts or add "
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
            "Propose semantically equivalent atomic claim pairs using the explicit zero-based indices. "
            "Alternative pairs may share indices; code will select a maximum one-to-one set after independent verification. "
            "Match paraphrases only when the same fact, relationship "
            "direction, participants, quantities, negation, modality, conditions and qualifications "
            "are preserved. A broader, narrower or contradictory assertion is not an equivalent "
            "claim. Do not use outside knowledge. Leave unsupported claims unmatched. "
            "Ignore claim order when matching: crossing matches are allowed. "
            "Explain each match briefly.",
            {"original_claims": [dict(index=i, text=c.text) for i, c in enumerate(left.claims)],
             "reconstructed_claims": [dict(index=i, text=c.text) for i, c in enumerate(right.claims)]},
            ClaimAlignment, entity_id + ":alignment",
            validator=lambda result: validate_matches(result.matches, len(left.claims), len(right.claims), one_to_one=False))
    # Keep all proposed alternatives, but do not spend a review on exact repeats.
    unique = list({(m.original_index, m.reconstructed_index): m for m in alignment.matches}.values())
    verified, reviews = context_matches(unique, original, reconstructed,
                                       left.claims, right.claims, models, entity_id)
    accepted = select_one_to_one(verified)
    selected = {(m.original_index, m.reconstructed_index) for m in accepted}
    for review in reviews:
        review['selected_for_alignment'] = (review['original_index'], review['reconstructed_index']) in selected
    return {
        **metrics(original, reconstructed, left.claims, right.claims, accepted),
        "original_claims": [c.model_dump() for c in left.claims],
        "reconstructed_claims": [c.model_dump() for c in right.claims],
        "claim_matches": [match.model_dump() for match in accepted],
        "context_reviews": reviews,
        "verified_competing_pairs": len(verified) - len(accepted),
        "rejected_context_matches": sum(not row['accepted'] for row in reviews),
    }


def reconstruction_context(graph, chunk_id):
    """Project only this chunk's document facts; never serialize source annotations."""
    by_id = {node["id"]: node for node in graph["nodes"]}
    concepts, relations = {}, []
    def source_position(edge):
        supports = [s.get('evidence_start') for s in edge.get('supporting_evidence', [])
                    if s.get('chunk_id') == chunk_id and isinstance(s.get('evidence_start'), int)]
        position = edge.get('source_order', edge.get('evidence_start'))
        if supports and edge.get('chunk_id') != chunk_id:
            position = min(supports)
        return position if isinstance(position, int) else float('inf')
    for edge in sorted(graph["edges"], key=source_position):
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
        for node in [source, target] + [by_id[p['node']] for p in edge.get('participants', [])]:
            # Registry definitions can include prose from other chunks. Only
            # endpoint identity and type are needed to interpret these facts.
            concepts[node["id"]] = {key: node[key] for key in
                                    ("id", "label", "kind", "semantic_kind") if key in node}
        relations.append({"source": source["label"], "relation": edge["label"],
                          "target": target["label"], "definition": edge.get("definition"),
                          "conditions": edge.get("conditions"), "modality": edge.get("modality")})
        for key in ('purpose', 'timing', 'argument_qualifiers'):
            if edge.get(key):
                relations[-1][key] = edge[key]
        if edge.get('participants'):
            relations[-1]['participants'] = [dict(role=p['role'], scope=p['scope'], entity=by_id[p['node']]['label'])
                                             for p in edge['participants']]
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
                    "Use the supplied relation order, which follows source occurrence order. Preserve all "
                    "participant roles and ownership, purpose as intention, timing and shared entities. "
                    "Do not turn qualified goals into achieved results. Prefer explicit entity names if a "
                    "pronoun would be ambiguous. Do not invent missing facts.", context, Reconstruction, chunk["id"])
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
