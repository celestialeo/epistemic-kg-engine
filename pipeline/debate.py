"""Shared semantic review and chapter-wide novelty checks."""
from typing import Literal
from pydantic import Field, create_model
from .records import Record, batches
from .registry import Concept, FactIndex
from .batching import ask_keyed
from .models import ModelResponseError
from .health import finish_item
from .events import EVENT_POLICY, kind_error
from .identity import concept_key


from .relations import DEFAULT_RELATIONS

# Starting vocabulary, not an admission whitelist. New predicates undergo registry review.
BACKGROUND_RELATIONS = set(DEFAULT_RELATIONS)


class IntendedFact(Record):
    intended_fact: str = Field(min_length=1,
        description="One simple factual sentence, including necessary qualifications, written before choosing graph endpoints")
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=800)
    gap_ids: list[str] = Field(min_length=1, description="Supplied knowledge gaps this assertion helps answer")
    added_knowledge: str = Field(min_length=1,
        description="What this assertion adds beyond the chapter and known facts")


class GraphLink(Record):
    source: Concept
    target: Concept
    relation: str = Field(min_length=1, max_length=80)
    relation_definition: str = Field(min_length=1, max_length=400)
    conditions: str | None = None
    modality: str | None = None


class Proposal(IntendedFact, GraphLink):
    """A persisted fact plus its separately constructed, explicit graph link."""


class FactPlan(Record):
    gap_analysis: str = Field(min_length=1)
    facts: list[IntendedFact]
    reason: str = Field(min_length=1)


class FactRepair(Record):
    corrected_fact: IntendedFact | None
    reason: str = Field(min_length=1)


def reject_background(row, stage, reason, trace):
    row.update(accepted=False, review_status="rejected", rejection_stage=stage, decision_reason=reason)
    trace.emit("debate.rejected", entity_id=row["id"], stage_of_rejection=stage, decision=row)


class Expansion(Record):
    gap_analysis: str = Field(min_length=1,
        description="Concise assessment of missing knowledge before proposing assertions, not private chain-of-thought")
    proposals: list[Proposal]
    reason: str = Field(min_length=1, max_length=800)


class RepresentationCheck(Record):
    link_reading: str = Field(min_length=1,
        description="Read SOURCE relation TARGET literally using the supplied relation contract and qualifications")
    meaning_matches: bool = Field(description="Whether the literal graph assertion expresses the intended factual sentence")
    direction_valid: bool = Field(description="Whether the endpoint roles and relation direction preserve the intended sentence")
    explanation_matches: bool = Field(description="Whether the proposer's explanation agrees with the LITERAL GRAPH ASSERTION, not merely with the intended sentence")
    scope_preserved: bool = Field(description="Whether conditions, quantifiers, modality and level of generality are preserved; this does not assess endpoint direction")
    case_specific_claim_supported: bool = Field(description="Whether any asserted case-specific detail is supported; true when the claim is wholly general and makes no such attribution")
    reason: str = Field(min_length=1)
    suggested_correction: str | None


class ReviewConflict(Record):
    field_name: str = Field(min_length=1)
    reason_quote: str = Field(min_length=1,
        description="Exact quote from the review's own reason or objections that directly disagrees with this field")
    explanation: str = Field(min_length=1,
        description="Why that quote contradicts the named field under its supplied definition")


class ReviewConsistency(Record):
    consistent: bool
    inconsistencies: list[ReviewConflict]
    reason: str = Field(min_length=1)


def validate_review_consistency(result, models, entity_id):
    """Ask about the review's internal meaning, not the truth of its conclusion.

    Called inside the originating model request's validator. A disagreement
    raises a validation error, so that reviewer must resolve it through the
    existing bounded response-retry mechanism before its result can be used.
    """
    fields = type(result).model_fields
    written_reasons = [result.reason, *getattr(result, "objections", [])]

    def validate_audit(audit):
        if audit.consistent != (not audit.inconsistencies):
            raise ValueError("Consistency flag and listed inconsistencies disagree")
        for issue in audit.inconsistencies:
            if issue.field_name not in fields:
                raise ValueError("A consistency issue must name an actual review field")
            if not any(issue.reason_quote in reason for reason in written_reasons):
                raise ValueError("A consistency issue must quote the review's own reasoning exactly")

    audit = models.ask("background_review_consistency",
        "Check only internal agreement between this review's structured fields and its written reasons or "
        "objections. Use the supplied field_meanings as the authoritative interpretation of each field. "
        "Do not rejudge the underlying subject-matter claim or invent dependencies between separate checks. "
        "A direction error can coexist with preserved scope, conditions and modality. A false overall "
        "meaning check does not force every narrower check to be false. explanation_matches compares "
        "the explanation with the literal graph assertion: agreement between explanation and intended "
        "sentence does not imply agreement with an incorrectly represented link. "
        "Interpret the reasoning semantically rather than matching keywords: a reported objection may "
        "be quoted and then explicitly resolved. Identify a conflict only when the review's own final "
        "reasoning disagrees with its fields or other conclusions. Check direction, meaning, type, scope, "
        "certainty, relevance, evidence, gap coverage and acceptance when those fields are present. "
        "For a rebuttal, check that defend/withdraw agrees with its actual conclusion. "
        "Return consistent=true and an empty list unless you can identify a direct, unambiguous conflict "
        "with the review's own final conclusion. For each conflict name the actual field, quote the exact "
        "conflicting text from reason or objections, and explain the conflict using that field's definition. "
        "Do not flag a conflict based solely on a different field's value or on speculation about what "
        "a field might mean. Do not supply a replacement verdict; "
        "the original reviewer must resolve its own inconsistency.",
        {"review_type": type(result).__name__, "review": result.model_dump(),
         "field_meanings": {name: field.description for name, field in fields.items() if field.description}},
        ReviewConsistency, entity_id, validator=validate_audit)
    if not audit.consistent:
        raise ValueError("Resolve your review's internal inconsistency without blindly flipping flags: " +
                         "; ".join(f"{issue.field_name}: {issue.explanation} (quote: {issue.reason_quote})"
                                   for issue in audit.inconsistencies))


def check_representation(row, models, trace):
    """Check the canonical graph assertion against its independently written fact."""
    result = models.ask("background_representation_checker",
        "Check representation before factual debate. First read the graph link as a simple sentence in "
        "link_reading, using the literal SOURCE-to-TARGET relation definition, conditions and modality. "
        "Then compare it with intended_fact and the proposer's explanation. Do not silently swap endpoints "
        "or repair the link while reading it. Check direction from the actual meaning, including which "
        "concept is the narrower category when the assertion expresses category membership. Do not rely "
        "on predicate names or a fixed vocabulary. Flag reversal, changed scope, and disagreement between "
        "the intended sentence, explanation and represented assertion. General background must not "
        "invent a missing fact about the particular case: check any case-specific attribution against "
        "source_context and case_specific_unknowns. General qualified explanations do not require source "
        "support. This check does not replace debate about the truth or usefulness of the general claim. "
        "Explain concrete representation errors and optionally suggest a correction as untrusted advice. "
        "Never modify the submitted assertion or treat a suggestion as accepted knowledge.",
        {"intended_fact": row["intended_fact"], "explanation": row["reason"],
         "link": {key: row.get(key) for key in
                  ("source", "relation", "relation_definition", "target", "conditions", "modality")},
         "endpoint_descriptions": {"source": row["source_mention"], "target": row["target_mention"]},
         "source_context": row["source_context"],
         "case_specific_unknowns": row.get("case_specific_unknowns", [])},
        RepresentationCheck, row["id"],
        validator=lambda result: validate_review_consistency(result, models, row["id"] + "_representation"))
    row["representation_check"] = result.model_dump()
    row["link_reading"] = result.link_reading
    passed = all((result.meaning_matches, result.direction_valid, result.explanation_matches,
                  result.scope_preserved, result.case_specific_claim_supported))
    trace.emit("debate.representation_checked", entity_id=row["id"], passed=passed,
               result=result.model_dump())
    return passed


class Review(Record):
    candidate_id: str
    semantics_valid: bool = Field(description="Whether the literal predicate use has a coherent meaning under its contract")
    direction_valid: bool = Field(description="Whether SOURCE and TARGET occupy the correct roles for this asserted relationship")
    types_valid: bool = Field(description="Whether endpoint kinds fit the predicate's contract, independently of whether direction or truth passes")
    no_contradiction: bool = Field(description="Whether no incompatible assertion under matching conditions is established; missing source support is not itself a contradiction")
    certain: bool = Field(description="Whether the claim is sufficiently well established to accept; this is not confidence in the reviewer's rejection")
    evidence_status: Literal["supported", "unsupported", "not_applicable"]
    domain_relevance: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=1200)


class Response(Record):
    candidate_id: str
    position: Literal["defend", "withdraw"]
    reason: str = Field(min_length=1, max_length=1200)


class Verdict(Review):
    accept: bool
    objections_resolved: bool


class DocumentVerdict(Verdict):
    evidence_status: Literal["supported", "unsupported"] = Field(
        description="Required quote-entailment decision for this DOCUMENT fact; evidence always applies")
    rejection_categories: list[Literal["meaning_changed", "quote_too_short", "wrong_direction",
        "wrong_kind", "unsupported_claim", "contradiction", "uncertain"]] = Field(
        description="Empty for acceptance; otherwise all applicable causes. quote_too_short means a longer source span supports the claim.")


class BackgroundReview(Review):
    evidence_status: Literal["not_applicable"]
    chapter_related: bool
    related_topic: str | None = Field(description="Copy one exact chapter topic when related, otherwise null")


class BackgroundCritique(BackgroundReview):
    objections: list[str] = Field(description="Concrete substantive objections; empty when there is no objection")


class BackgroundVerdict(BackgroundReview):
    accept: bool
    objections_resolved: bool
    gap_addressed: bool


class Novelty(Record):
    status: Literal["new", "duplicate", "uncertain"]
    evidence_ids: list[str]
    related_reference_ids: list[str] = Field(default_factory=list,
        description="References containing part of the assertion; retained for comparison across batches")
    reason: str = Field(min_length=1, max_length=800)


COMMON_POLICY = (
    "Every endpoint must be a standalone concept, never a statement or context-dependent reference. "
    "Express the assertion through a precise relation, with qualifications in conditions and modality. "
    "Evaluate the literal SOURCE relation TARGET under its relation definition, conditions and evidence. "
    "Concept names identify shared nodes across contexts; infer their contextual meaning from the relationship "
    "and supplied source material, not from separate node senses or an exhaustive node definition. "
    "A structural part is not a subtype; an event's location is not its physical component. "
    "Keep direction, causal strength, negation, conditions and specificity. "
    "Read conditions and modality as part of the assertion, including negation; preserve them in proposals. "
    "Never broaden a concept, invent an omitted action, or upgrade 'helps' to 'primary'. "
)
DOCUMENT_POLICY = EVENT_POLICY + COMMON_POLICY + (
    "Check that all participants, locations, negation and qualifications survive in the relation and its "
    "conditions and modality. Preserve collective scope without inventing pairwise routes. "
    "These are DOCUMENT candidates. The exact quote must entail THIS relation, including both endpoints, meaning, "
    "direction and qualifications; co-occurrence is insufficient. Outside knowledge cannot repair missing evidence. "
    "A quote may span multiple adjacent sentences. Judge entailment, not whether it literally contains the "
    "relation key. Mark quote_too_short only if the supplied source context contains the missing support. "
)
BACKGROUND_POLICY = COMMON_POLICY + (
    "Use a precise predicate appropriate to the asserted meaning; new predicates require schema validation. "
    "These are BACKGROUND candidates. Use well-established general knowledge. Accept a true, correctly directed "
    "relation with compatible endpoint kinds when it answers a useful knowledge gap for the WHOLE chapter. "
    "The source context establishes what needs explaining, not a boundary on what you may know. "
    "Use your own general understanding; no external texts or citations are requested. "
    "New concepts and predicates are permitted. A chapter's mention of a function does not fully explain it. "
    "Distinguish general explanatory knowledge from unknown choices or measurements in the particular case. "
    "Do not turn a possible approach into an assertion that this case actually uses it. "
    "A supporting link may join other concepts when it directly contributes to answering the seed's "
    "original gap through a connected explanation. The seed need not be an endpoint of every link. "
    "explanation_context contains unverified companion claims, not evidence; do not assume their truth. "
    "Summaries and short concept definitions are fallible aids; do not infer restrictions they do not state. "
    "Absence from the text is NOT an objection. Missing text support is never a contradiction. Reject false, uncertain, or off-topic claims. "
    "Set chapter_related=true when you can identify the chapter topic it explains; copy that exact topic into "
    "related_topic. Relevance is to the whole chapter, never just the seed's original paragraph. "
    "Preserve scientific conditions and do not contradict the chapter. Contradiction requires incompatible "
    "assertions under matching conditions, not absence of support, a different contributor, or different wording. "
    "Do not confuse a concept with text describing it or invent claims about where information originated. "
    "Keep verdicts and explanations consistent and concise. "
    "Background evidence_status must be not_applicable. A model judgment is not external factual verification. "
)
NOVELTY_POLICY = (
    "Your only task is informational novelty: is the candidate assertion already stated or implied by the "
    "supplied references without adding outside subject knowledge? Do not judge truth, plausibility, "
    "chapter relevance, usefulness, or contradiction. A false or conflicting assertion may still be new; "
    "the debate handles those questions. Compare meaning, direction, scope, conditions and modality, not "
    "word overlap. Paraphrases, aliases, equivalent inverse phrasing, or recombinations containing no new "
    "information are duplicates. Mere relatedness, shared endpoints, or rearranged words expressing a "
    "different assertion are insufficient. Broader assertions, changed conditions and genuinely additional "
    "information are not automatically duplicates. Use general linguistic understanding to resolve names "
    "and wording, but never supply an unstated subject-matter premise to derive a duplicate. "
    "Return duplicate with supporting evidence_ids only when the references entail the asserted information. "
    "Otherwise return new. Use uncertain only for a concrete ambiguity preventing this comparison, "
    "never because the candidate lacks source support. Identify related_reference_ids for partial overlaps "
    "and assertions about the same subjects under comparable conditions, even when not duplicates. "
    "Retain those references without judging whether they conflict. This lets information distributed "
    "across reference pages be combined and gives the debate relevant comparison context."
)


def index_complete(rows, candidates, trace, role):
    expected = {c["id"] for c in candidates}
    actual = [r.candidate_id for r in rows]
    valid = len(actual) == len(set(actual)) and set(actual) == expected
    trace.emit("debate.ids_validated", role=role, expected=sorted(expected), actual=actual, valid=valid)
    if not valid:
        raise ValueError(f"{role}: return exactly one record per candidate; expected {sorted(expected)}, got {actual}")
    return {r.candidate_id: r.model_dump() for r in rows}


def validate_background_review(result, chapter):
    if result.chapter_related and result.related_topic not in chapter["topics"]:
        raise ValueError("A related background fact must cite an exact supplied chapter topic")
    if not result.chapter_related and result.related_topic is not None:
        raise ValueError("An unrelated fact must not cite a related topic")
    if isinstance(result, BackgroundCritique):
        if any(not objection.strip() for objection in result.objections):
            raise ValueError("Use an empty objections list instead of an empty objection")
        checks = (result.semantics_valid, result.direction_valid, result.types_valid,
                  result.no_contradiction, result.certain, result.chapter_related)
        if not result.objections and not all(checks):
            raise ValueError("Explain a failed critic check as a concrete objection, or correct the check")
    if isinstance(result, BackgroundVerdict):
        checks = (result.semantics_valid, result.direction_valid, result.types_valid,
                  result.no_contradiction, result.certain, result.chapter_related,
                  result.objections_resolved, result.gap_addressed)
        if result.accept != all(checks):
            raise ValueError("Resolve the disagreement between accept and the mandatory judgment fields")


def withdraw_candidate(row, response, trace):
    row.update(rebuttal=response, accepted=False, score=None, review_status="withdrawn",
               decision_reason="Proposer withdrew: " + response["reason"],
               verification_basis="model_knowledge" if row["origin"] == "background" else "quote_entailment_model_review")
    trace.emit("debate.withdrawn", entity_id=row["id"], decision=row)


def review_batch(models, role, instruction, payload, row_schema, candidates, trace, entity_id):
    fields = {}
    for candidate in candidates:
        identifier = candidate["id"]
        row = create_model(f"{role}_{identifier}", __base__=row_schema, candidate_id=(Literal[identifier], ...))
        fields[identifier] = (row, ...)
    schema = create_model(f"{role}_results", __base__=Record, **fields)
    def validate(result):
        index_complete(list(result.__dict__.values()), candidates, trace, role)
        for value in result.__dict__.values():
            if isinstance(value, BackgroundReview):
                validate_background_review(value, payload["chapter"])
                validate_review_consistency(value, models, value.candidate_id + "_" + role)
    result = models.ask(role, instruction + " Return an object keyed by the exact candidate IDs.",
        payload, schema, entity_id, validator=validate)
    return {identifier: getattr(result, identifier).model_dump() for identifier in fields}


def review_context(row, chunk, outline, concepts):
    row["endpoint_kinds"] = {k: (row.get(k + "_mention") or concepts.entries[row[k]])["kind"]
                             for k in ("source", "target")}
    context = {"candidate": {k: row[k] for k in (
        "id", "source", "target", "relation", "relation_definition", "origin", "reason")},
        "concepts": [{field: concepts.entries[row[k]][field] for field in ("name", "definition", "kind")}
                     for k in ("source", "target")],
        "chapter": {k: outline[k] for k in ("overview", "topics")}}
    context["candidate"].update(conditions=row.get("conditions"), modality=row.get("modality"))
    if row["origin"] == "document":
        context.update(quote=row.get("evidence"), source_chunk=row.get("evidence_context", chunk["text"]))
    else:
        context["chapter"]["concepts"] = getattr(concepts, "chapter_names", []) or sorted(concepts.entries)
        context.update(source_chunk=chunk["text"], source_context=row.get("source_context", []),
                       gaps=row.get("gaps", []), gap_analysis=row.get("gap_analysis"),
                       added_knowledge=row.get("added_knowledge"),
                       known_seed_facts=row.get("known_seed_facts", []),
                       comparison_references=row.get("novelty_references", []),
                       intended_fact=row.get("intended_fact"), link_reading=row.get("link_reading"),
                       case_specific_unknowns=row.get("case_specific_unknowns", []),
                       explanation_context=row.get("explanation_context", []))
    return context


def review_candidate(row, chunk, outline, concepts, models, trace, threshold):
    if row["origin"] == "background":
        review_background_many([row], {row["chunk_id"]: chunk}, outline, concepts, models, trace)
        return row
    context = review_context(row, chunk, outline, concepts)
    policy = DOCUMENT_POLICY
    critic = review_batch(models, "critic", policy +
        "Independently challenge the precise relation. Explain any invalidity and keep boolean checks "
        "consistent with your reasoning. Do not give a category error a passing semantics/types check.",
        context, Review, [row], trace, row["id"])[row["id"]]
    response = review_batch(models, "proposer_rebuttal", policy +
        "Address the critic's concrete objection. Defend a sound relation or withdraw an unsound one. "
        "Do not change the proposed endpoints or meaning.",
        {**context, "objection": critic["reason"]}, Response, [row], trace, row["id"])[row["id"]]
    row.update(critic=critic, rebuttal=response)
    if response["position"] == "withdraw":
        withdraw_candidate(row, response, trace)
        return row
    # No critic scores, boolean verdicts, confidence, or defend/withdraw position
    # are shown to the judge. It must adjudicate the actual statement and arguments.
    verdict = review_batch(models, "judge", policy +
        "Make your own decision. You see arguments, not other agents' verdicts or scores. "
        "Assess each validity condition independently. An argument conceding or defending a claim is not evidence. "
        "Accept only when all semantic conditions pass and all substantive objections are resolved. "
        "Explain explicitly why a raised objection is resolved or still valid.",
        {**context, "objection": critic["reason"], "reply": response["reason"]},
        DocumentVerdict, [row], trace, row["id"])[row["id"]]
    row.update(critic=critic, rebuttal=response)
    return apply_verdict(row, verdict, trace, threshold)


def apply_verdict(row, verdict, trace, threshold):
    gates = {k: verdict[k] for k in ("semantics_valid", "direction_valid", "types_valid",
                                   "no_contradiction", "certain", "objections_resolved")}
    gates["evidence"] = verdict["evidence_status"] == ("supported" if row["origin"] == "document" else "not_applicable")
    gates["relevance"] = verdict.get("chapter_related", False) if row["origin"] == "background" else verdict["domain_relevance"] >= threshold
    if row["origin"] == "background":
        gates["gap_addressed"] = verdict["gap_addressed"]
    kinds = row.get("endpoint_kinds")
    # Background predicates are open-ended; their contracts and endpoint kinds
    # are judged semantically, without a fixed predicate-specific admission rule.
    type_error = kind_error(row["relation"], kinds["source"], kinds["target"]) if kinds and row["origin"] == "document" else None
    gates["event_contract"] = type_error is None
    accepted = verdict["accept"] and all(gates.values())
    failed = [k for k, valid in gates.items() if not valid]
    row.update(judge=verdict, gates=gates, score=verdict["domain_relevance"],
               threshold=threshold, accepted=accepted,
               decision_reason=verdict["reason"] + (" Failed gates: " + ", ".join(failed) if failed else "") +
                               (" " + type_error if type_error else ""),
               verification_basis="quote_entailment_model_review" if row["origin"] == "document" else "model_knowledge")
    if row["origin"] == "document":
        categories = set(verdict.get("rejection_categories", [])) if not accepted else set()
        if not accepted:
            for gate, category in (("direction_valid", "wrong_direction"), ("types_valid", "wrong_kind"),
                                   ("event_contract", "wrong_kind")):
                if not gates[gate]:
                    categories.add(category)
            if not categories:
                categories.add("unsupported_claim")
        row["rejection_categories"] = sorted(categories)
    if verdict["accept"] != all(gates.values()):
        trace.emit("debate.verdict_conflict", entity_id=row["id"], verdict=verdict, gates=gates)
    trace.emit("debate.adjudicated", entity_id=row["id"], candidate=row)
    return row


def review_extractions(extractions, chunks, outline, concepts, facts, models, trace):
    by_chunk = {c["id"]: c for c in chunks}
    by_extraction = {e["chunk_id"]: e for e in extractions}
    decisions = []
    quality = {e["chunk_id"]: dict(chunk_id=e["chunk_id"], reviewed=0, accepted=0,
                                  rejected=0, unresolved=0) for e in extractions}
    rows = [row for e in extractions for row in e["relation_proposals"]]

    def review_page(page):
        items = [dict(id=row["id"], **review_context(row, by_chunk[row["chunk_id"]], outline, concepts)) for row in page]
        def validate(item, result):
            if result.candidate_id != item["id"]:
                raise ValueError("Review candidate_id must match its item ID")
            if result.accept and result.rejection_categories:
                raise ValueError("Accepted relations must have no rejection categories")
            if not result.accept and not result.rejection_categories:
                raise ValueError("Rejected relations require at least one rejection category")
        try:
            verdicts = ask_keyed(models, "extraction_reviewer", DOCUMENT_POLICY +
                "Act as the single evidence reviewer for each DOCUMENT relation. Check every semantic and evidence "
                "condition independently; accept only when ALL pass. Identify objections yourself; objections_resolved "
                "is true only if no substantive objection remains. Be strict about the exact quote's entailment, "
                "endpoint types, causal strength, direction, and qualifications. These are DOCUMENT candidates: "
                "evidence_status is supported ONLY when the supplied quote entails the exact relation; otherwise "
                "it is unsupported and accept must be false. Report all applicable rejection_categories: "
                "meaning_changed for stronger/different claims, quote_too_short when surrounding source text "
                "provides missing support, wrong_direction, wrong_kind, unsupported_claim, contradiction, or "
                "uncertain. Accepted answers must have an empty category list. For parallel source statements "
                "using the same predicate, explain an actual semantic or evidential difference before giving "
                "different verdicts. Never invent an ontology restriction. Write a concise concrete reason.",
                items, DocumentVerdict, page[0]["id"], validate=validate)
        except ModelResponseError as exc:
            trace.emit("extraction.review_batch_failed", candidate_ids=[r["id"] for r in page],
                       error=str(exc), error_type=type(exc).__name__, recoverable=True)
            if len(page) > 1:
                midpoint = len(page) // 2
                yield from review_page(page[:midpoint])
                yield from review_page(page[midpoint:])
            else:
                yield page[0], None, str(exc)
            return
        for row in page:
            yield row, verdicts[row["id"]], None

    for page in batches(rows, getattr(models, "batch_size", 4)):
        for row, verdict, error in review_page(page):
            counts = quality[row["chunk_id"]]
            if error is not None:
                row.update(accepted=False, review_status="unresolved", score=None, gates={},
                           decision_reason="No validated evidence review; excluded from graph: " + error)
                extraction = by_extraction[row["chunk_id"]]
                extraction["status"] = "incomplete"
                issue = dict(id=row["id"], reason=row["decision_reason"],
                             record={k: row[k] for k in ("source", "relation", "target", "evidence")})
                extraction.setdefault("issues", []).append(issue)
                trace.emit("extraction.unresolved", entity_id=row["id"], chunk_id=row["chunk_id"], **issue)
                counts["unresolved"] += 1
                trace.save("artifacts/extraction_issues.json", [dict(chunk_id=e["chunk_id"], **i)
                    for e in extractions for i in e.get("issues", [])])
            else:
                apply_verdict(row, verdict, trace, threshold=0)
                row["reviewer"] = row.pop("judge")
                row["review_status"] = "completed"
                counts["reviewed"] += 1
                counts["accepted" if row["accepted"] else "rejected"] += 1
            if row["accepted"]:
                duplicate = facts.add(row)
                if duplicate:
                    row["duplicate_of"] = duplicate["id"]
                    duplicate.setdefault("supporting_evidence", []).append({
                        k: row[k] for k in ("id", "chunk_id", "evidence", "evidence_start", "evidence_end")})
                else:
                    by_extraction[row["chunk_id"]]["relations"].append(row)
            decisions.append(row)
            trace.emit("debate.decision", entity_id=row["id"], decision=row)
            # Save every outcome, including the final item of a partial batch.
            trace.save("artifacts/extraction_review.json", decisions)
            trace.save("artifacts/extractions.json", extractions)
            trace.save("artifacts/extraction_quality.json", list(quality.values()))
            finish_item(trace, "extraction_review", row["id"], error)
    if not rows:
        trace.save("artifacts/extraction_review.json", [])
        trace.save("artifacts/extraction_quality.json", list(quality.values()))
    facts.rows[:] = [r for r in facts.rows if r.get("accepted")]
    for extraction in extractions:
        extraction["relations"][:] = [r for r in extraction["relations"] if r.get("accepted")]
        chunk_decisions = [r for r in decisions if r["chunk_id"] == extraction["chunk_id"] and r.get("review_status") != "unresolved"]
        quality[extraction["chunk_id"]].update(accepted=sum(r["accepted"] for r in chunk_decisions),
                                              rejected=sum(not r["accepted"] for r in chunk_decisions))
    trace.save("artifacts/extraction_review.json", decisions)
    trace.save("artifacts/extractions.json", extractions)
    trace.save("artifacts/extraction_quality.json", list(quality.values()))
    for counts in quality.values():
        trace.emit("extraction.chunk_review_summary", entity_id=counts["chunk_id"], **counts)
        print(f"  {counts['chunk_id']}: {counts['accepted']} accepted, "
              f"{counts['rejected']} rejected, {counts['unresolved']} unresolved", flush=True)
    from collections import Counter
    category_counts = Counter(category for row in decisions if not row["accepted"]
                              and row.get("review_status") != "unresolved"
                              for category in set(row.get("rejection_categories", [])))
    trace.save("artifacts/extraction_rejections.json", dict(
        scope="Completed semantic reviews; categories can overlap",
        counts=dict(category_counts.most_common()),
        rejected=[{k: row[k] for k in ("id", "chunk_id", "source", "relation", "target", "decision_reason")}
                  | {"categories": row.get("rejection_categories", [])}
                  for row in decisions if not row["accepted"] and row.get("review_status") != "unresolved"]))
    print("  Rejection categories (may overlap): " + ", ".join(
        f"{category}={count}" for category, count in category_counts.most_common()), flush=True)
    return decisions


def check_novelty(row, chunks, facts, models, trace):
    duplicate = facts.find(row)
    if duplicate:
        return dict(status="duplicate", evidence_ids=[duplicate["id"]],
                    reason="Canonical fact already present, including symmetric or inverse forms")
    return check_novelty_many([row], chunks, facts, models, trace)[row["id"]]


def check_novelty_many(rows, chunks, facts, models, trace):
    """Compare information only; truth and relevance belong to the debate."""
    results, pending = {}, []
    for row in rows:
        duplicate = facts.find(row)
        if duplicate:
            results[row["id"]] = dict(status="duplicate", evidence_ids=[duplicate["id"]],
                                     reason="Canonical fact already present")
        else:
            pending.append(row)
    references = [dict(id=chunk["id"], text=chunk["text"]) for chunk in chunks]
    references += [{key: fact.get(key) for key in
                    ("id", "source", "target", "relation", "relation_definition", "conditions", "modality")}
                   for fact in facts.rows]
    related = {row["id"]: {} for row in pending}
    checked = []
    for index, page in enumerate(batches(references, models.batch_size)):
        if not pending:
            break
        available = {row["id"]: ({ref["id"]: ref for ref in page} | related[row["id"]])
                     for row in pending}

        def validate(item, result):
            allowed = set(available[item["id"]])
            if not set(result.evidence_ids + result.related_reference_ids) <= allowed:
                raise ValueError("Novelty references must identify supplied information")
            if result.status == "duplicate" and not result.evidence_ids:
                raise ValueError("An already known assertion requires supporting reference IDs")

        items = [dict(id=row["id"],
                      candidate={key: row.get(key) for key in
                                 ("source", "target", "relation", "relation_definition", "conditions", "modality")},
                      earlier_references=list(related[row["id"]].values()))
                 for row in pending]
        errors = {}
        judgments = ask_keyed(models, "novelty_checker", NOVELTY_POLICY,
            items, Novelty, f"novelty_batch_{pending[0]['id']}_{index}",
            shared={"references": page}, validate=validate,
            on_error=lambda item, exc: errors.update({item["id"]: str(exc)}))
        checked.extend(ref["id"] for ref in page)
        remaining = []
        for row in pending:
            identifier = row["id"]
            if identifier in errors:
                results[identifier] = dict(status="unresolved", evidence_ids=[], reason=errors[identifier])
                continue
            judgment = judgments[identifier]
            for ref_id in judgment["related_reference_ids"] + judgment["evidence_ids"]:
                related[identifier][ref_id] = available[identifier][ref_id]
            saved_context = {ref["id"]: ref for ref in row.get("novelty_references", [])}
            row["novelty_references"] = list((saved_context | related[identifier]).values())
            trace.emit("debate.novelty_checked", entity_id=identifier,
                       references=list(available[identifier]), result=judgment)
            if judgment["status"] == "new":
                remaining.append(row)
            else:
                results[identifier] = judgment
        pending = remaining
    for row in pending:
        results[row["id"]] = dict(status="new", evidence_ids=[], checked_references=checked,
            related_reference_ids=list(related[row["id"]]),
            reason="The references do not already supply the candidate's asserted information")
    return results


def unresolved_candidate(row, error, trace):
    row.update(accepted=False, review_status="unresolved", score=None,
               decision_reason="No validated background decision: " + str(error))
    trace.emit("debate.unresolved", entity_id=row["id"], decision=row, error=str(error))


def review_background_many(rows, by_chunk, outline, concepts, models, trace):
    if not rows:
        return
    items = [dict(id=row["id"], **review_context(row, by_chunk[row["chunk_id"]], outline, concepts))
             for row in rows]
    chapter = items[0]["chapter"]
    for item in items:
        item.pop("chapter")
    by_id = {row["id"]: row for row in rows}

    def on_error(item, exc):
        unresolved_candidate(by_id[item["id"]], exc, trace)

    def validate(item, result):
        if result.candidate_id != item["id"]:
            raise ValueError("candidate_id must match item ID")
        if isinstance(result, BackgroundReview):
            validate_background_review(result, chapter)
        validate_review_consistency(result, models, item["id"] + "_" + type(result).__name__)

    reviews = ask_keyed(models, "critic", BACKGROUND_POLICY +
        "Act as a fair critic of EACH actual assertion, not as an opponent required to reject it. "
        "List only substantive objections supported by a specific flaw or concrete uncertainty. "
        "Return objections=[] when you find none, and explain why the assertion is sound. "
        "Do not manufacture an objection because the knowledge is absent from the chapter; that absence "
        "is intentional. Evaluate the stated relation rather than an interpretation that changes its scope. "
        "Check whether the addition actually helps answer its supplied knowledge gap. Judge truth using "
        "your own general understanding, not source entailment. Keep validity checks consistent with objections.",
        items, BackgroundCritique, rows[0]["id"], shared={"chapter": chapter},
        validate=validate, on_error=on_error)
    for identifier, review in reviews.items():
        by_id[identifier]["critic"] = review
    items = [item for item in items if item["id"] in reviews]

    replies = ask_keyed(models, "proposer_rebuttal", BACKGROUND_POLICY +
        "You are the original proposer of each supplied claim. Your original_proposal and gap_analysis "
        "restore the claim and justification you proposed. Explain and defend that same assertion using "
        "your general subject knowledge, addressing every actual objection directly. If objections is "
        "empty, maintain and briefly justify your sound claim; do not invent an objection to rebut. "
        "Do not switch to the critic's role or concede merely because an objection was raised. "
        "Withdraw only if you identify a real error, unresolved uncertainty, or inability of this exact "
        "claim to address the gap. Explain the specific defect when withdrawing. "
        "A changed endpoint, predicate, condition, or modality would be a different claim: do not silently "
        "repair the assertion during rebuttal. Do not invent evidence or external citations.",
        [dict(item, objections=reviews[item["id"]]["objections"],
              original_proposal={key: value for key, value in by_id[item["id"]].get("original_proposal", {}).items()
                                 if key != "confidence"})
         for item in items],
        Response, rows[0]["id"], shared={"chapter": chapter}, validate=validate, on_error=on_error)
    for identifier, response in replies.items():
        row = by_id[identifier]
        row["rebuttal"] = response
        if response["position"] == "withdraw":
            withdraw_candidate(row, response, trace)

    # Withdrawals are terminal. The judge receives arguments only, never critic
    # scores/checks, confidence, or a proposer position to follow.
    items = [item for item in items if item["id"] in replies and replies[item["id"]]["position"] == "defend"]
    verdicts = ask_keyed(models, "judge", BACKGROUND_POLICY +
        "Independently adjudicate EACH exact assertion using your own general knowledge, its source "
        "context and knowledge gap, and the supplied objections and defense. Neither an argument nor "
        "agreement between roles is evidence. An empty objections list does not force acceptance; do "
        "your own assessment. A criticism is not automatically valid. Decide each semantic condition "
        "independently. Mark gap_addressed only when the actual added information helps resolve a "
        "supplied gap at the chapter's scope. Accept when the assertion is sound, useful, correctly "
        "qualified, and all substantive objections are resolved. Reject for a concrete remaining defect. "
        "Explain why each substantive objection is resolved or still valid. Source absence is expected "
        "for background knowledge and is not a reason to reject it.",
        [dict(item, objections=reviews[item["id"]]["objections"], reply=replies[item["id"]]["reason"])
         for item in items],
        BackgroundVerdict, rows[0]["id"], shared={"chapter": chapter}, validate=validate, on_error=on_error)
    for identifier, verdict in verdicts.items():
        apply_verdict(by_id[identifier], verdict, trace, threshold=None)


def connected_explanation(rows, seed, facts):
    """Find links reachable from the seed; semantic direction is checked separately.

    Existing direct seed facts, admitted links from this seed, and known links
    between the proposed endpoints can supply bridges. Unrelated paths through
    the rest of the chapter do not make a disconnected proposal admissible.
    """
    endpoints = {seed["concept"]} | {row[side] for row in rows for side in ("source", "target")}
    bridges = [fact for fact in facts.rows
               if seed["concept"] in (fact["source"], fact["target"])
               or fact.get("seed_id") == seed["id"]
               or {fact["source"], fact["target"]} <= endpoints]
    links = bridges + rows
    reachable = {seed["concept"]}
    while True:
        expanded = reachable | {node for link in links
                                if link["source"] in reachable or link["target"] in reachable
                                for node in (link["source"], link["target"])}
        if expanded == reachable:
            break
        reachable = expanded
    return {row["id"] for row in rows if row["source"] in reachable and row["target"] in reachable}


def debate(seeds, chunks, outline, concepts, relations, facts, models, trace, document_reviews=None,
           *, proposal_limit=0):
    if proposal_limit < 0:
        raise ValueError("background proposal limit must be nonnegative")
    candidates, transcripts = [], []
    by_chunk = {chunk["id"]: chunk for chunk in chunks}

    def persist():
        trace.save("artifacts/debate_progress.json", dict(candidates=candidates, transcripts=transcripts))

    for seed in seeds:
        print(f"  Debate {seed['id']}: {seed['concept']}", flush=True)
        gaps = seed.get("gaps", [])
        transcript = dict(seed=seed, proposal=None, fact_plan=None, candidate_ids=[], repairs=[])
        transcripts.append(transcript)
        if not gaps:
            transcript.update(status="skipped", reason="No validated unanswered knowledge gap")
            persist()
            finish_item(trace, "background_proposal", seed["id"])
            continue
        source_context = [dict(id=cid, text=by_chunk[cid]["text"])
                          for cid in seed.get("chunk_ids", [seed["chunk_id"]])]
        unknowns = seed.get("case_specific_unknowns", [])
        gap_by_id = {gap["id"]: gap for gap in gaps}
        chapter = {**{key: outline[key] for key in ("overview", "topics")},
                   "concepts": getattr(concepts, "chapter_names", []) or sorted(concepts.entries)}

        def known_seed_facts():
            return [{key: fact.get(key) for key in
                     ("id", "source", "relation", "target", "relation_definition", "origin", "conditions", "modality")}
                    for fact in facts.rows
                    if seed["concept"] in (fact["source"], fact["target"]) or fact.get("seed_id") == seed["id"]]

        def validate_plan(result):
            if proposal_limit and len(result.facts) > proposal_limit:
                raise ValueError("Fact count exceeds the configured initial per-seed budget")
            for value in result.facts:
                if not set(value.gap_ids) <= set(gap_by_id):
                    raise ValueError("Each intended fact must address supplied gap IDs")

        try:
            plan = models.ask("proposer", BACKGROUND_POLICY +
                "First assess what is still missing and record a concise conclusion in gap_analysis. "
                "Then write each intended_fact as a simple factual sentence BEFORE choosing any graph "
                "predicate or endpoint. Include necessary qualifications in the sentence. Use your own "
                "general understanding to supply information not obtainable merely by paraphrasing, "
                "recombining or reversing the chapter. Identify its gap_ids, added_knowledge and substantive "
                "justification in reason. Keep the sentence and explanation consistent. "
                "Produce a small, minimal connected explanation around the seed: include a direct connection "
                "and only the supporting facts needed to answer the original questions. Supporting facts "
                "may relate newly introduced concepts to each other. Existing known facts may provide "
                "connections; do not repeat them solely to connect the explanation. Do not recursively "
                "expand incidental concepts. There is no quota; honor proposal_limit when non-null. "
                "Do not infer an unknown case-specific choice from what is generally possible. Leave "
                "case_specific_unknowns unknown while explaining general possibilities or mechanisms. "
                "Return no facts if no useful responsible addition remains. Do not construct graph links "
                "in this step and do not invent citations.",
                {"seed": {key: seed[key] for key in ("concept", "definition", "kind")},
                 "chapter": chapter, "source_context": source_context,
                 "document_coverage": seed.get("document_coverage"),
                 "gaps": gaps, "case_specific_unknowns": unknowns,
                 "known_seed_facts": known_seed_facts(), "proposal_limit": proposal_limit or None},
                FactPlan, seed["id"], validator=validate_plan)
        except ModelResponseError as exc:
            transcript.update(status="unresolved", reason=str(exc))
            persist()
            finish_item(trace, "background_proposal", seed["id"], exc)
            continue
        transcript["fact_plan"] = plan.model_dump()
        transcript["proposal"] = dict(gap_analysis=plan.gap_analysis, proposals=[], reason=plan.reason)
        persist()
        finish_item(trace, "background_proposal", seed["id"])

        def new_candidate(value, parent=None):
            # The sentence is saved before the link-construction request. Every
            # correction gets a new ID; a rejected record is never overwritten.
            fact = value.model_dump() if isinstance(value, IntendedFact) else value
            row = dict(fact, id=f"candidate_{len(candidates)+1:04d}", seed_id=seed["id"],
                       source=None, target=None, relation=None, relation_definition=None,
                       conditions=None, modality=None, origin="background",
                       chunk_id=seed["chunk_id"], paragraph_id=seed["paragraph_id"],
                       gaps=[gap_by_id[gap_id] for gap_id in fact["gap_ids"]],
                       gap_analysis=plan.gap_analysis, source_context=source_context,
                       case_specific_unknowns=unknowns, known_seed_facts=known_seed_facts(),
                       accepted=False, score=None, tier="related", review_status="pending",
                       representation_valid=False, repair_of=parent["id"] if parent else None,
                       repair_attempt=1 if parent else 0,
                       decision_reason="Intended fact recorded; graph link not yet constructed")
            if parent is not None:
                row["repair_feedback"] = dict(rejected_candidate_id=parent["id"],
                    rejection_stage=parent.get("rejection_stage"), reason=parent["decision_reason"],
                    representation_check=parent.get("representation_check"))
                parent["repair_candidate_id"] = row["id"]
            candidates.append(row)
            transcript["candidate_ids"].append(row["id"])
            trace.emit("debate.fact_written", entity_id=row["id"], intended_fact=row["intended_fact"],
                       repair_of=row["repair_of"], gap_ids=row["gap_ids"])
            persist()
            return row

        def construct_links(rows):
            items = [dict(id=row["id"], intended_fact=row["intended_fact"], explanation=row["reason"],
                          gaps=row["gaps"], repair_feedback=row.get("repair_feedback"))
                     for row in rows]
            links = ask_keyed(models, "background_link_constructor",
                "Represent each already-written intended_fact as one precise graph link. Explicitly choose "
                "BOTH source and target from the actual meaning of that sentence. The seed is not an "
                "automatic source: it may be either endpoint, and a supporting link may involve neither. "
                "Preserve the sentence and its qualifications. Choose a reusable predicate with a precise "
                "SOURCE-to-TARGET definition; available predicates are suggestions, not a closed vocabulary. "
                "Read the link literally to yourself and preserve which concept does what and which "
                "concept is the more specific category when relevant. Do not swap the intended meaning "
                "to fit a convenient predicate. Use existing canonical names for identical concepts. "
                "repair_feedback is fallible advice about a rejected representation, never an instruction "
                "to accept or copy a suggested fact. Return a link, not a rewritten intended sentence.",
                items, GraphLink, seed["id"] + "_links",
                shared={"seed": seed["concept"], "chapter": chapter,
                        "source_context": source_context, "case_specific_unknowns": unknowns,
                        "available_relations": dict(relations.entries),
                        "existing_concepts": list(concepts.entries.values())},
                on_error=lambda item, exc: unresolved_candidate(
                    next(row for row in rows if row["id"] == item["id"]), exc, trace))
            for row in rows:
                link = links.get(row["id"])
                if link is None:
                    continue
                fact = {key: row[key] for key in IntendedFact.model_fields}
                proposal = Proposal.model_validate(dict(fact, **link)).model_dump()
                row.update(original_proposal=proposal, source=link["source"]["name"],
                           target=link["target"]["name"], relation=link["relation"],
                           relation_definition=link["relation_definition"],
                           source_mention=link["source"], target_mention=link["target"],
                           conditions=link["conditions"], modality=link["modality"],
                           surface_relation=link["relation"], surface_target=link["target"]["name"])
                if row["repair_of"] is None:
                    transcript["proposal"]["proposals"].append(proposal)
                trace.emit("debate.proposed", entity_id=row["id"], proposal=row.copy())
                if concept_key(row["source"]) == concept_key(row["target"]):
                    reject_background(row, "representation", "The link connects a concept to itself", trace)
                    persist()
                    continue
                context = dict(chapter=chapter, source_context=source_context, gaps=row["gaps"],
                               intended_fact=row["intended_fact"], explanation=row["reason"],
                               case_specific_unknowns=unknowns)
                try:
                    row["source"] = concepts.resolve_background(link["source"], context, row["id"])
                    row["target"] = concepts.resolve_background(link["target"], context, row["id"])
                    if row["source"] == row["target"]:
                        reject_background(row, "representation",
                                          "Both endpoints resolve to the same canonical concept", trace)
                        persist()
                        continue
                    relation = relations.resolve(link["relation"], link["relation_definition"],
                                                 row["source"], row["target"], context, row["id"])
                    if relation is None:
                        reject_background(row, "representation",
                                          "The proposed predicate has no validated meaning-preserving contract", trace)
                        persist()
                        continue
                    row.update(relation=relation, relation_definition=relations.entries[relation]["definition"])
                    if not check_representation(row, models, trace):
                        reject_background(row, "representation", row["representation_check"]["reason"], trace)
                        persist()
                        continue
                    row["representation_valid"] = True
                except ModelResponseError as exc:
                    unresolved_candidate(row, exc, trace)
                persist()

        def review_wave(rows):
            current = [row for row in rows if row["representation_valid"]]
            connected = connected_explanation(current, seed, facts)
            for row in current:
                if row["id"] not in connected:
                    reject_background(row, "connectivity",
                        "No path connects this proposed explanation to the seed through proposed or known links", trace)
            current = [row for row in current if row["id"] in connected]
            for row in current:
                row["explanation_context"] = [
                    dict(id=peer["id"], intended_fact=peer["intended_fact"], source=peer["source"],
                         relation=peer["relation"], relation_definition=peer["relation_definition"],
                         target=peer["target"], conditions=peer.get("conditions"), modality=peer.get("modality"),
                         status="unverified_companion")
                    for peer in current if peer["id"] != row["id"] and set(peer["gap_ids"]) & set(row["gap_ids"])]
            novelties = check_novelty_many(current, chunks, facts, models, trace)
            novel = []
            for row in current:
                row["novelty"] = novelties[row["id"]]
                if row["novelty"]["status"] == "new":
                    novel.append(row)
                elif row["novelty"]["status"] in ("unresolved", "uncertain"):
                    unresolved_candidate(row, row["novelty"]["reason"], trace)
                else:
                    reject_background(row, "novelty", row["novelty"]["reason"], trace)
            review_background_many(novel, by_chunk, outline, concepts, models, trace)
            for row in novel:
                if not row["accepted"] and row["review_status"] != "unresolved":
                    if row["review_status"] == "withdrawn":
                        row["rejection_stage"] = "withdrawal"
                    else:
                        reject_background(row, "debate", row["decision_reason"], trace)

            delta = FactIndex(relations)
            approved = []
            for row in novel:
                if not row["accepted"]:
                    continue
                peer = check_novelty(row, [], delta, models, trace)
                row["peer_novelty"] = peer
                if peer["status"] in ("unresolved", "uncertain"):
                    unresolved_candidate(row, peer["reason"], trace)
                elif peer["status"] == "duplicate":
                    reject_background(row, "novelty", peer["reason"], trace)
                else:
                    delta.add(row)
                    approved.append(row)
            # A rejected anchor must never leave accepted supporting links
            # disconnected. Only final accepted links can establish this path.
            connected = connected_explanation(approved, seed, facts)
            for row in approved:
                row.setdefault("gates", {})["connected_to_seed"] = row["id"] in connected
                if row["id"] not in connected:
                    reject_background(row, "connectivity",
                        "The supporting link lost its connection to the seed after other links were rejected", trace)
                else:
                    row["review_status"] = "completed"
                    facts.add(row)
            for row in rows:
                if row["review_status"] == "pending":
                    unresolved_candidate(row, "No complete admission decision was produced", trace)
                trace.emit("debate.decision", entity_id=row["id"], decision=row)
                persist()
                finish_item(trace, "background_candidate", row["id"],
                            row["decision_reason"] if row["review_status"] == "unresolved" else None)

        originals = [new_candidate(value) for value in plan.facts]
        construct_links(originals)
        review_wave(originals)

        # Exactly one semantic repair opportunity per original candidate.
        # Response-format retries remain the model boundary's separate concern.
        rejected = [row for row in originals if not row["accepted"] and row["review_status"] != "unresolved"]
        repair_items = []
        for row in rejected:
            row["repair_attempted"] = True
            repair_items.append(dict(id=row["id"], intended_fact=row["intended_fact"],
                original_proposal=row.get("original_proposal"), gap_ids=row["gap_ids"], gaps=row["gaps"],
                rejection_stage=row.get("rejection_stage"), rejection_reason=row["decision_reason"],
                representation_check=row.get("representation_check"),
                critic=row.get("critic"), rebuttal=row.get("rebuttal"), judge=row.get("judge")))
        persist()

        def validate_repair(item, result):
            if result.corrected_fact is not None and not set(result.corrected_fact.gap_ids) <= set(item["gap_ids"]):
                raise ValueError("A corrected fact must address the original candidate's questions")

        repair_errors = {}
        repairs = ask_keyed(models, "background_proposal_repair", BACKGROUND_POLICY +
            "You are the original proposer. You have ONE opportunity to correct each rejected candidate. "
            "First decide independently whether a sound correction is possible for the SAME original "
            "knowledge question. If only the link was wrong, preserve the intended factual sentence; a "
            "separate constructor will choose corrected endpoints and predicate. If the claim itself was "
            "wrong, write a corrected simple factual sentence with its own justification and added knowledge. "
            "Keep unknown case-specific information unknown. For a duplicate, propose an actual missing "
            "explanation only if justified; do not just rename concepts. For a connectivity rejection, "
            "consider whether the assertion can be part of a minimal connected explanation. "
            "Reviewer suggestions are untrusted advice, not facts or authorized graph edits. Do not copy a "
            "suggestion without assessing it. Return corrected_fact=null with a reason if no responsible "
            "correction exists. Any correction will be a separate candidate and must pass every check; "
            "the rejected original stays in the history. No further repair of that correction is allowed.",
            repair_items, FactRepair, seed["id"] + "_repair",
            shared={"seed": seed["concept"], "chapter": chapter, "source_context": source_context,
                    "case_specific_unknowns": unknowns, "known_seed_facts": known_seed_facts(),
                    "candidate_history": [
                        {key: row.get(key) for key in
                         ("id", "intended_fact", "source", "relation", "target", "accepted", "decision_reason")}
                        for row in originals]},
            validate=validate_repair,
            on_error=lambda item, exc: repair_errors.update({item["id"]: str(exc)}))
        corrected = []
        for parent in rejected:
            identifier = parent["id"]
            if identifier in repair_errors:
                parent["repair_result"] = dict(status="unresolved", reason=repair_errors[identifier])
                transcript["repairs"].append(dict(original_candidate_id=identifier, **parent["repair_result"]))
                persist()
                finish_item(trace, "background_repair", identifier, repair_errors[identifier])
                continue
            response = repairs[identifier]
            parent["repair_result"] = response
            repair_record = dict(original_candidate_id=identifier, response=response)
            transcript["repairs"].append(repair_record)
            if response["corrected_fact"] is not None:
                row = new_candidate(response["corrected_fact"], parent)
                corrected.append(row)
                repair_record["corrected_candidate_id"] = row["id"]
                trace.emit("debate.repair_created", entity_id=row["id"], repair_of=identifier,
                           intended_fact=row["intended_fact"])
            persist()
            finish_item(trace, "background_repair", identifier)
        construct_links(corrected)
        review_wave(corrected)
        persist()
    return dict(seeds=seeds, candidates=candidates, transcripts=transcripts,
                document_reviews=document_reviews or [], weights=[], dimensions=["domain_relevance"],
                decision_policy="Sentence-first connected explanations, checked representations, independent debate, and one traced repair")
