from .settings import setting
from .settings import budgeted_pages
"""Shared semantic review and chapter-wide novelty checks."""
from typing import Literal
from pydantic import Field, create_model
from .qualifiers import correct_polarity, negative_direction
from .records import Record, batches
from .registry import Concept, FactIndex
from .repair_budget import repair_candidates
from .background_context import seed_neighborhood
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
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))
    gap_ids: list[str] = Field(min_length=1, description="Supplied knowledge gaps this assertion helps answer")
    added_knowledge: str = Field(min_length=1,
        description="What this assertion adds beyond the chapter and known facts")


class GraphLink(Record):
    source: Concept
    target: Concept
    relation: str = Field(min_length=1, max_length=setting('text', 'raw_predicate_chars'))
    relation_definition: str = Field(min_length=1, max_length=setting('text', 'definition_chars'),
        description="Reusable SOURCE-to-TARGET meaning, without additional subject-matter premises")
    argument_qualifiers: list[str] = Field(default_factory=list,
        description="Essential action complements, results and additional participants needed for the predicate; not if/when conditions or graph-construction commentary")
    conditions: str | None = Field(default=None,
        description="When or under what circumstances the assertion holds; other arguments belong in argument_qualifiers")
    modality: str | None = None

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema['required'] = list(dict.fromkeys([*schema.get('required', []), 'argument_qualifiers', 'conditions', 'modality']))
        return schema


class Proposal(IntendedFact, GraphLink):
    """A persisted fact plus its separately constructed, explicit graph link."""


class FactPlan(Record):
    gap_analysis: str = Field(min_length=1)
    facts: list[IntendedFact]
    reason: str = Field(min_length=1)


class FactRepair(Record):
    reason: str = Field(min_length=1)
    corrected_fact: IntendedFact | None
    connecting_facts: list[IntendedFact] = Field(default_factory=list,
        description="For connectivity repairs only: separately justified assertions needed to connect the corrected fact to the seed; otherwise empty")


def reject_background(row, stage, reason, trace):
    row.update(accepted=False, review_status="rejected", rejection_stage=stage, decision_reason=reason)
    trace.emit("debate.rejected", entity_id=row["id"], stage_of_rejection=stage, decision=row)


class Expansion(Record):
    gap_analysis: str = Field(min_length=1,
        description="Concise assessment of missing knowledge before proposing assertions, not private chain-of-thought")
    proposals: list[Proposal]
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))


class RepresentationCheck(Record):
    link_reading: str = Field(min_length=1,
        description="Read SOURCE relation TARGET literally using the supplied relation contract and qualifications")
    reason: str = Field(min_length=1,
        description="Briefly compare the link reading to the intended sentence before deciding the fields below")
    meaning_matches: bool = Field(description="Whether the literal graph assertion expresses the intended factual sentence")
    direction_valid: bool = Field(description="Whether the endpoint roles and relation direction preserve the intended sentence")
    explanation_matches: bool = Field(description="Whether the explanation is consistent with the literal graph assertion. A justification of usefulness need not repeat the fact; fail only for an actual disagreement.")
    scope_preserved: bool = Field(description="Whether conditions, quantifiers, modality and level of generality are preserved; this does not assess endpoint direction")
    suggested_correction: str | None


class ReasonedBoolean(Record):
    reason_quote: str | None = Field(description="Exact short quote explicitly deciding this check, otherwise null")
    implied_value: bool | None = Field(description="Value explicitly concluded by that quote; null if not decided")


class ReasonedPosition(Record):
    reason_quote: str | None
    implied_value: Literal["defend", "withdraw"] | None


def validate_review_consistency(result, models, entity_id):
    """Ask about the review's internal meaning, not the truth of its conclusion.

    Called inside the originating model request's validator. A disagreement
    raises a validation error, so that reviewer must resolve it through the
    existing bounded response-retry mechanism before its result can be used.
    """
    written_reasons = [result.reason, *getattr(result, "objections", [])]
    fields = {name: field for name, field in type(result).model_fields.items()
              if isinstance(getattr(result, name), bool) or name == "position"}
    schema = create_model("ReviewConclusions", __base__=Record, **{
        name: (ReasonedPosition if name == "position" else ReasonedBoolean, ...) for name in fields})

    def validate_audit(audit):
        for name in fields:
            finding = getattr(audit, name)
            # Only a claimed disagreement needs quoted evidence. An agreeing
            # auditor's imperfect quotation must not block a valid review.
            if finding.implied_value is not None and finding.implied_value != getattr(result, name) and (
                not finding.reason_quote or not any(finding.reason_quote in reason for reason in written_reasons)
            ):
                raise ValueError("An explicit conclusion needs an exact quote from the review")

    # Extract conclusions without showing the existing flags. Compare values in
    # code: an auditor cannot call matching values an inconsistency.
    audit = models.ask("background_review_consistency",
        "Read only the reviewer's written conclusions. For each field, extract an explicit final "
        "conclusion and its exact short quote. Use null when the reasoning does not decide that field. "
        "Do not assess the underlying claim or infer one check from another. Wrong direction does not "
        "imply changed scope or incompatible types. A rejection does not imply every check failed. "
        "A resolved objection is not the final conclusion. Return no commentary beyond the quotes.",
        {"reason": result.reason, "objections": getattr(result, "objections", []),
         "field_meanings": {name: field.description or name for name, field in fields.items()}},
        schema, entity_id, validator=validate_audit)
    conflicts = [f"{name}={getattr(result, name)} disagrees with: {getattr(audit, name).reason_quote}"
                 for name in fields if getattr(audit, name).implied_value is not None
                 and getattr(audit, name).implied_value != getattr(result, name)]
    if conflicts:
        raise ValueError("Resolve disagreement between your fields and final reasoning: " + "; ".join(conflicts))


def literal_assertion(row):
    statement = f"({row['source']} --[{row['relation'].replace('_', ' ')}]--> {row['target']})"
    reading = (row.get('modality') or 'ASSERTED') + ' ' + statement
    if row.get('conditions'):
        reading += '; conditions: ' + row['conditions']
    if row.get('argument_qualifiers'):
        reading += '; additional arguments: ' + '; '.join(row['argument_qualifiers'])
    return reading


def check_representation(row, models, trace):
    """Check the canonical graph assertion against its independently written fact."""
    literal = literal_assertion(row)
    schema = create_model('LiteralRepresentationCheck', __base__=RepresentationCheck,
                          link_reading=(Literal[literal], ...))
    result = models.ask("background_representation_checker",
        "COPY literal_candidate_reading exactly into link_reading. Assess the saved endpoints and qualifiers; "
        "do not replace an endpoint with words from intended_fact. "
        "A property is not its reduction or constraint. Never silently insert an action into an endpoint "
        "or use conditions to change its identity. A literal increase must not stand for a decrease. "
        "Does it express the intended fact with the same direction, meaning and scope? Does the explanation "
        "agree with that link? Do not repair or reinterpret it. Check representation only: even a false "
        "sentence can be represented faithfully. Check entailment in BOTH directions: the link must not "
        "add a property, necessity, guarantee or other premise absent from the intended sentence. The "
        "proposer's explanation cannot authorize such extra assertions. "
        "Truth, relevance and support for case-specific details "
        "are judged later in debate. Briefly explain concrete representation errors, if any. "
        "suggested_correction is optional untrusted advice, never an accepted replacement.",
        {"literal_candidate_reading": literal,
         "intended_fact": row["intended_fact"], "explanation": row["reason"],
         "link": {key: row.get(key) for key in
                  ("source", "relation", "relation_definition", "target", "conditions", "modality", "argument_qualifiers")},
         "endpoint_descriptions": {"source": row["source_mention"], "target": row["target_mention"]}},
        schema, row["id"],
        validator=lambda result: validate_review_consistency(result, models, row["id"] + "_representation"))
    row["representation_check"] = result.model_dump()
    row["link_reading"] = result.link_reading
    passed = all((result.meaning_matches, result.direction_valid, result.explanation_matches,
                  result.scope_preserved))
    trace.emit("debate.representation_checked", entity_id=row["id"], passed=passed,
               result=result.model_dump())
    return passed


class CounterexampleCheck(Record):
    reason: str = Field(min_length=1, max_length=400)
    counterexample: str | None = Field(description="A concrete standard case refuting this exact qualified claim, or null")
    sound_as_stated: bool


def check_background_counterexamples(rows, models, trace):
    pending = {row['id']: row for row in rows if row.get('accepted')}
    if not pending:
        return

    def validate(result):
        if result.sound_as_stated and result.counterexample:
            raise ValueError('A refuting counterexample cannot accompany sound_as_stated=true')

    checks = ask_keyed(models, 'background_counterexample_check',
        'Challenge each literal assertion with a concrete standard counterexample before admission. '
        'Check alternative implementations, necessary versus sufficient conditions, possibility versus '
        'guarantee, and whether the stated evidence actually establishes the conclusion. Distinguish '
        'influence or contribution from sufficiency, determination or guarantees: do not approve a strong '
        'predicate by silently reading it as a weaker one. Other controlling factors may require explicit '
        'qualifications. Logical consistency '
        'alone does not establish factual truth. Respect explicit modality and conditions: an alternative '
        'does not refute a claim that something CAN occur. Do not invent objections or reject background '
        'knowledge merely because the source did not state it. A plausible mechanism is not evidence '
        'that a particular system uses it: respect case_specific_unknowns, and require explicit possibility '
        'or conditions for merely possible methods. Assess the actual endpoints and qualifiers, '
        'not a silently corrected intended sentence. Give a concise reason and any refuting case.',
        [dict(id=row['id'], literal_assertion=literal_assertion(row),
              intended_fact=row['intended_fact'], relation_definition=row['relation_definition'],
              case_specific_unknowns=row.get('case_specific_unknowns', [])) for row in pending.values()],
        CounterexampleCheck, 'background_counterexamples',
        validate=lambda item, result: validate(result),
        on_error=lambda item, exc: unresolved_candidate(pending[item['id']], exc, trace))
    for candidate_id, check in checks.items():
        row = pending[candidate_id]
        row['counterexample_check'] = check
        row.setdefault('gates', {})['counterexample_check'] = check['sound_as_stated']
        trace.emit('debate.counterexample_checked', entity_id=candidate_id, result=check)
        if not check['sound_as_stated']:
            reject_background(row, 'counterexample', check['reason'] +
                              (' Counterexample: ' + check['counterexample'] if check['counterexample'] else ''), trace)


class Review(Record):
    candidate_id: str
    semantics_valid: bool = Field(description="Whether the literal predicate use has a coherent meaning under its contract")
    direction_valid: bool = Field(description="Whether SOURCE and TARGET occupy the correct roles for this asserted relationship")
    types_valid: bool = Field(description="Whether endpoint kinds fit the predicate's contract, independently of whether direction or truth passes")
    no_contradiction: bool = Field(description="Whether no incompatible assertion under matching conditions is established; missing source support is not itself a contradiction")
    certain: bool = Field(description="Whether the claim is sufficiently well established to accept; this is not confidence in the reviewer's rejection")
    evidence_status: Literal["supported", "unsupported", "not_applicable"]
    domain_relevance: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=setting('text', 'long_explanation_chars'))


class Response(Record):
    candidate_id: str
    position: Literal["defend", "withdraw"]
    reason: str = Field(min_length=1, max_length=setting('text', 'long_explanation_chars'))


class Verdict(Review):
    accept: bool
    objections_resolved: bool


class DocumentVerdict(Record):
    qualified_reading: str = Field(default='',
        description='First read the actual SOURCE predicate TARGET with modality and conditions applied. Negation in modality negates the positive predicate. Do not merely quote the evidence.')
    reason: str = Review.model_fields['reason']
    candidate_id: str
    semantics_valid: bool = Review.model_fields['semantics_valid']
    direction_valid: bool = Review.model_fields['direction_valid']
    types_valid: bool = Review.model_fields['types_valid']
    no_contradiction: bool = Review.model_fields['no_contradiction']
    certain: bool = Review.model_fields['certain']
    evidence_status: Literal["supported", "unsupported"] = Field(
        description="Required quote-entailment decision for this DOCUMENT fact; evidence always applies")
    domain_relevance: float = Field(ge=0, le=1)
    accept: bool
    objections_resolved: bool
    rejection_categories: list[Literal["meaning_changed", "quote_too_short", "wrong_direction",
        "wrong_kind", "unsupported_claim", "contradiction", "uncertain"]] = Field(
        description="Empty for acceptance; otherwise all applicable causes. quote_too_short means a longer source span supports the claim.")

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema['required'] = list(dict.fromkeys(['qualified_reading', *schema.get('required', [])]))
        return schema


class BackgroundReview(Record):
    # Reason first: the small model previously emitted flags before evaluating
    # the claim, then contradicted those flags in its own explanation.
    reason: str = Field(min_length=1, max_length=setting('text', 'long_explanation_chars'))
    candidate_id: str
    semantics_valid: bool = Review.model_fields["semantics_valid"]
    direction_valid: bool = Review.model_fields["direction_valid"]
    types_valid: bool = Review.model_fields["types_valid"]
    no_contradiction: bool = Review.model_fields["no_contradiction"]
    certain: bool = Review.model_fields["certain"]
    evidence_status: Literal["not_applicable"]
    domain_relevance: float = Field(ge=0, le=1)
    chapter_related: bool
    related_topic: str | None = Field(description="Copy one exact chapter topic when related, otherwise null")


class BackgroundCritique(BackgroundReview):
    objections: list[str] = Field(description="Concrete substantive objections; empty when there is no objection")


class BackgroundVerdict(BackgroundReview):
    accept: bool
    objections_resolved: bool
    gap_addressed: bool


class BackgroundResponse(Record):
    reason: str = Field(min_length=1, max_length=setting('text', 'long_explanation_chars'))
    candidate_id: str
    position: Literal["defend", "withdraw"]


class Novelty(Record):
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'),
        description="Compare the complete assertion with the references before deciding what is additional or duplicate")
    additional_information: list[str] = Field(description="Parts of the assertion NOT supplied by the references, including explanatory mechanisms and conditions; empty only when all information is already supplied")
    status: Literal["new", "duplicate", "uncertain"]
    evidence_ids: list[str]
    related_reference_ids: list[str] = Field(default_factory=list,
        description="References containing part of the assertion; retained for comparison across batches")


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
BACKGROUND_POLICY = (
    "Represent general explanatory knowledge as standalone concepts joined by precise directed relations. "
    "Read conditions and modality as part of the assertion. Preserve qualifications and causal strength. "
    "Use a precise predicate appropriate to the asserted meaning; new predicates require schema validation. "
    "These are BACKGROUND candidates. Use well-established general knowledge. Accept a true, correctly directed "
    "relation with compatible endpoint kinds when it answers a useful knowledge gap for the WHOLE chapter. "
    "The source context establishes what needs explaining, not a boundary on what you may know. "
    "Use your own general understanding; no external texts or citations are requested. "
    "New concepts and predicates are permitted. A chapter's mention of a function does not fully explain it. "
    "Distinguish general explanatory knowledge from unknown choices or measurements in the particular case. "
    "Reject an assertion of a particular case's unstated choice or measurement as unsupported uncertainty; "
    "that restriction does not apply to general definitions, mechanisms or qualified possibilities. "
    "Do not turn a possible approach into an assertion that this case actually uses it. "
    "A supporting link may join other concepts when it directly contributes to answering the seed's "
    "original gap through a connected explanation. The seed need not be an endpoint of every link. "
    "explanation_context contains unverified companion claims, not evidence; do not assume their truth. "
    "Summaries and short concept definitions are fallible aids; do not infer restrictions they do not state. "
    "Absence from the text is NOT an objection. Missing text support is never a contradiction. Reject false, uncertain, or off-topic claims. "
    "Set chapter_related=true when you can identify the chapter topic it explains; copy that exact topic into "
    "related_topic. Relevance is to the whole chapter, never just the seed's original paragraph. "
    "Preserve source conditions and do not contradict the chapter. Contradiction requires incompatible "
    "assertions under matching conditions, not absence of support, a different contributor, or different wording. "
    "Do not confuse a concept with text describing it or invent claims about where information originated. "
    "Keep verdicts and explanations consistent and concise. "
    "Background evidence_status must be not_applicable. A model judgment is not external factual verification. "
)
NOVELTY_POLICY = (
    "First list additional_information: what the FULL candidate explains that the references do not. "
    "An explanation of how or why a known outcome happens adds information. A specific mechanism is "
    "not entailed by a general outcome. Include information carried in conditions, not just the triple. "
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
    context["candidate"].update(conditions=row.get("conditions"), modality=row.get("modality"),
                                argument_qualifiers=row.get("argument_qualifiers", []))
    if row["origin"] == "document":
        # This is formatting of the model's saved fields, not another proposed
        # fact. The reviewer must not insert missing qualifiers from the quote.
        context['literal_candidate_reading'] = literal_assertion(row)
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
        ready = []
        for row in page:
            try:
                if 'source_role_reading' not in row:
                    row['source_role_reading'] = negative_direction(row, models, trace)
            except ModelResponseError as exc:
                yield row, None, str(exc)
                continue
            ready.append(row)
        page = ready
        if not page:
            return
        items = [dict(id=row["id"], **review_context(row, by_chunk[row["chunk_id"]], outline, concepts)) for row in page]
        def item_schema(item):
            return create_model('DocumentVerdict_' + item['id'], __base__=DocumentVerdict,
                qualified_reading=(Literal[item['literal_candidate_reading']], ...))
        def validate(item, result):
            if result.candidate_id != item["id"]:
                raise ValueError("Review candidate_id must match its item ID")
            if result.qualified_reading != item['literal_candidate_reading']:
                raise ValueError('Copy literal_candidate_reading exactly into qualified_reading. '
                                 'Judge this existing assertion; do not repair it or add missing negation from the quote.')
            if result.accept and result.rejection_categories:
                raise ValueError("Accepted relations must have no rejection categories")
            if not result.accept and not result.rejection_categories:
                raise ValueError("Rejected relations require at least one rejection category")
        try:
            verdicts = ask_keyed(models, "extraction_reviewer",
                "First COPY literal_candidate_reading EXACTLY into qualified_reading. This string renders the "
                "actual candidate fields; evaluate it as written. You are reviewing, NOT repairing the candidate. "
                "If making the assertion true would require adding a negation, condition or participant, reject it. "
                "argument_qualifiers supply predicate complements and extra participants; they are not if/when restrictions. "
                "The modality outside parentheses applies to the WHOLE parenthesized assertion, never just "
                "to the target. NOT (A R B) denies that relation; it does not mean A R (NOT B). "
                "A positive predicate with modality='does not' is a NEGATIVE assertion, not a contradiction by itself. "
                "For example, A -> affects -> B with modality='does not' means A does not affect B. "
                "Negation does NOT make a directed relation symmetric: A does not affect B does not imply "
                "B does not affect A. Resolve relative clauses carefully: 'a B that A does not affect' "
                "has A as source and B as target, never the reverse. Explicitly compare who does what "
                "to whom in the quote and the candidate; a draft definition cannot override these roles. "
                "Then compare this full reading with the source and explain the decision BEFORE setting flags. " + DOCUMENT_POLICY +
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
                items, DocumentVerdict, page[0]["id"], validate=validate, schema_for_item=item_schema)
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

    for page in budgeted_pages(rows, models, schema=DocumentVerdict):
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
                role_reading = row.get('source_role_reading')
                if (role_reading and role_reading['exact_reversed_bindings']
                        and not facts.relations.entries.get(row['relation'], {}).get('symmetric')):
                    row['accepted'] = False
                    row['gates']['source_role_direction'] = False
                    row['rejection_categories'] = sorted(set(row['rejection_categories']) | {'wrong_direction'})
                    row['decision_reason'] += '; source-only predicate reading identifies reversed endpoint bindings'
                    trace.emit('source.direction_rejected', entity_id=row['id'], reading=role_reading)
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
                    ("id", "source", "target", "relation", "relation_definition", "conditions", "modality", "argument_qualifiers")}
                   for fact in facts.rows]
    related = {row["id"]: {} for row in pending}
    checked = []
    for index, page in enumerate(budgeted_pages(references, models)):
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
            if result.status == "duplicate" and result.additional_information:
                raise ValueError("A claim with additional information is not wholly duplicate")
            if result.status == "new" and not result.additional_information:
                raise ValueError("Identify what information the references do not already supply")

        items = [dict(id=row["id"],
                      candidate={key: row.get(key) for key in
                                 ("intended_fact", "link_reading", "source", "target", "relation", "relation_definition", "conditions", "modality", "argument_qualifiers")},
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
        "Use precise definitions of technical terms. Before deciding, check for confusion between "
        "related concepts and for a counterexample to any asserted generalization. A familiar informal "
        "description does not establish the literal technical claim. Report a flaw only if you find one. "
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
        BackgroundResponse, rows[0]["id"], shared={"chapter": chapter}, validate=validate, on_error=on_error)
    for identifier, response in replies.items():
        row = by_id[identifier]
        row["rebuttal"] = response
        if response["position"] == "withdraw":
            withdraw_candidate(row, response, trace)

    # Withdrawals are terminal. The judge receives arguments only, never critic
    # scores/checks, confidence, or a proposer position to follow.
    items = [item for item in items if item["id"] in replies and replies[item["id"]]["position"] == "defend"]
    verdicts = ask_keyed(models, "judge", BACKGROUND_POLICY +
        "Check the literal technical claim against precise definitions, including the properties named "
        "in its predicate contract. Do not silently replace it with a related true idea. Consider any "
        "counterexample or missing qualification before deciding; agreement between roles is insufficient. "
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
    completed_seeds = []
    checkpoints = getattr(trace, 'checkpoints', None)
    if checkpoints:
        saved = checkpoints.restore('debate')
        if saved is not None:
            candidates, transcripts = saved['candidates'], saved['transcripts']
            completed_seeds = saved['completed_seeds']
    def complete_seed(seed_id):
        completed_seeds.append(seed_id)
        if checkpoints:
            checkpoints.save('debate', dict(candidates=candidates, transcripts=transcripts,
                                          completed_seeds=completed_seeds))
    by_chunk = {chunk["id"]: chunk for chunk in chunks}

    def persist():
        trace.save("artifacts/debate_progress.json", dict(candidates=candidates, transcripts=transcripts))

    for seed in seeds:
        if seed['id'] in completed_seeds:
            continue
        print(f"  Debate {seed['id']}: {seed['concept']}", flush=True)
        gaps = seed.get("gaps", [])
        # Only admitted facts can close a later question. Merely proposing or
        # mentioning a gap never marks it answered.
        accepted = [r for r in facts.rows if r.get('origin') == 'background' and r.get('accepted')]
        reused = {}
        if accepted and gaps:
            from .seeds import GapCoverage
            from .retrieval import shortlist
            items = []
            for gap in gaps:
                choices = shortlist(gap['question'] + ' ' + gap.get('assumed_knowledge', ''),
                    [dict(name=r.get('intended_fact', ''), definition=r.get('relation_definition', ''), row=r) for r in accepted],
                    setting('workload', 'retrieval_candidates'))
                evidence = [dict(id=e['row']['id'], assertion=e['name'], source=e['row']['source'],
                                 relation=e['row']['relation'], target=e['row']['target'],
                                 conditions=e['row'].get('conditions'), modality=e['row'].get('modality'),
                                 argument_qualifiers=e['row'].get('argument_qualifiers', [])) for e in choices]
                items.append(dict(id=gap['id'], question=gap, admitted_facts=evidence))
            def check_gap(item, result):
                allowed = {r['id'] for r in item['admitted_facts']}
                if not set(result.evidence_ids) <= allowed or (result.answered and not result.evidence_ids):
                    raise ValueError('Gap completion requires supplied admitted fact IDs')
            answers = ask_keyed(models, 'background_existing_gap_coverage',
                'Does the supplied admitted background already answer this entire question at its stated scope? '
                'Use only these facts and their qualifications. A related concept or partial answer is insufficient. '
                'Set answered=false if additional knowledge is needed. Cite exact supporting fact IDs.',
                items, GapCoverage, seed['id'] + '_existing_gaps', validate=check_gap,
                on_error=lambda item, exc: trace.emit('seed.gap_reuse_unresolved', entity_id=item['id'], error=str(exc)))
            reused = {identifier: answer for identifier, answer in answers.items() if answer['answered']}
            gaps = [gap for gap in gaps if gap['id'] not in reused]
            trace.emit('seed.existing_gap_coverage', entity_id=seed['id'], reused=reused,
                       remaining=[g['id'] for g in gaps])
        transcript = dict(seed=seed, proposal=None, fact_plan=None, candidate_ids=[], repairs=[])
        transcript['reused_gap_answers'] = reused
        transcripts.append(transcript)
        if not gaps:
            transcript.update(status="skipped", reason="No validated unanswered knowledge gap")
            persist()
            finish_item(trace, "background_proposal", seed["id"])
            complete_seed(seed['id'])
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
                "link. Each sentence must state ONE relationship between two named concepts. Split a "
                "multi-step mechanism into separate connected facts, preserving needed qualifications. "
                "Prefer the missing prerequisite or mechanism itself over repeating a known outcome. "
                "Use your own "
                "general understanding to supply information not obtainable merely by paraphrasing, "
                "recombining or reversing the chapter. Identify its gap_ids, added_knowledge and substantive "
                "justification in reason. Keep the sentence and explanation consistent. "
                "Produce a small, minimal connected explanation around the seed: include a direct connection "
                "and only the supporting facts needed to answer the original questions. Supporting facts "
                "must form an explicit path starting at the seed or an existing connected concept. "
                "When introducing a part or mechanism, state its connection as a separate sentence before "
                "describing its action: A has B; B does C. Do not hide the connection in a relative clause "
                "or a definition. Each sentence must stand as one independently checked assertion. Use "
                "the exact supplied concept names when their referents are the same. Never invent a "
                "connection merely to complete a path; omit an explanation whose connection is not justified. "
                "Supporting facts may relate newly introduced concepts to each other. Existing known facts may provide "
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
            complete_seed(seed['id'])
            continue
        transcript["fact_plan"] = plan.model_dump()
        transcript["proposal"] = dict(gap_analysis=plan.gap_analysis, proposals=[], reason=plan.reason)
        persist()
        finish_item(trace, "background_proposal", seed["id"])

        def new_candidate(value, parent=None, repair_kind='correction'):
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
                row['repair_kind'] = repair_kind
                parent.setdefault('repair_candidate_ids', []).append(row['id'])
                if repair_kind == 'correction':
                    parent["repair_candidate_id"] = row["id"]
            candidates.append(row)
            transcript["candidate_ids"].append(row["id"])
            trace.emit("debate.fact_written", entity_id=row["id"], intended_fact=row["intended_fact"],
                       repair_of=row["repair_of"], gap_ids=row["gap_ids"])
            persist()
            return row

        def construct_links(rows):
            items = [dict(id=row["id"], intended_fact=row["intended_fact"],
                          repair_feedback=row.get("repair_feedback"))
                     for row in rows]
            links = ask_keyed(models, "background_link_constructor",
                "Represent each already-written intended_fact as one precise graph link. Explicitly choose "
                "BOTH source and target from the actual meaning of that sentence. "
                "Use the subject, predicate and object of the MAIN clause. In 'A has B, which does C', "
                "the main link is A has B, not B does C. Preserve subordinate qualifications without "
                "substituting a relative clause for the main assertion. The seed and existing_concepts "
                "are naming context, not evidence for new claims: when the sentence refers to one of "
                "them, use its exact supplied name. Do not replace a distinct concept merely to connect "
                "the graph. A newly introduced concept must retain the same name across the supplied "
                "explanation_sentences when its referent is unchanged. "
                "Choose endpoints for the sentence's main relationship. A reduction or constraint is a "
                "process concept, not the unchanged property. Do not hide that change in conditions. "
                f"Prefer one to three words; when needed for meaning use at most {setting('labels', 'predicate_words')} words and {setting('labels', 'predicate_chars')} characters for a reusable predicate. "
                "Keep if/when circumstances in conditions and essential action/result/participant complements in argument_qualifiers. Do not import premises from surrounding discussion. "
                "Preserve the sentence and its qualifications. Use actual modal language only, or null; "
                "do not invent modality labels such as universal or assertive. Choose a reusable predicate with a precise "
                "SOURCE-to-TARGET definition; available predicates are suggestions, not a closed vocabulary. "
                "Read the link literally to yourself and preserve which concept does what and which "
                "concept is the more specific category when relevant. Do not swap the intended meaning "
                "to fit a convenient predicate. Use existing canonical names for identical concepts. "
                "repair_feedback is fallible advice about a rejected representation, never an instruction "
                "to accept or copy a suggested fact. Return a link, not a rewritten intended sentence.",
                items, GraphLink, seed["id"] + "_links",
                shared={**seed_neighborhood(seed, facts.rows, concepts.entries),
                        'explanation_sentences': [dict(id=row['id'], intended_fact=row['intended_fact']) for row in rows],
                        "case_specific_unknowns": unknowns},
                on_error=lambda item, exc: unresolved_candidate(
                    next(row for row in rows if row["id"] == item["id"]), exc, trace))
            for row in rows:
                link = links.get(row["id"])
                if link is None:
                    continue
                try:
                    link = correct_polarity(link, row['intended_fact'], models, trace, row['id'] + '_polarity')
                except ModelResponseError as exc:
                    unresolved_candidate(row, exc, trace)
                    continue
                fact = {key: row[key] for key in IntendedFact.model_fields}
                proposal = Proposal.model_validate(dict(fact, **link)).model_dump()
                row.update(original_proposal=proposal, source=link["source"]["name"],
                           target=link["target"]["name"], relation=link["relation"],
                           relation_definition=link["relation_definition"],
                           source_mention=link["source"], target_mention=link["target"],
                           conditions=link["conditions"], modality=link["modality"],
                           argument_qualifiers=link.get("argument_qualifiers", []),
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
                    relation = relations.resolve_background(link["relation"], link["relation_definition"],
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
                         argument_qualifiers=peer.get("argument_qualifiers", []),
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
            check_background_counterexamples(novel, models, trace)
            for row in novel:
                if not row["accepted"] and row["review_status"] != "unresolved":
                    if row["review_status"] == "withdrawn":
                        row["rejection_stage"] = "withdrawal"
                    elif not row.get('rejection_stage'):
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
        rejected = [row for row in originals if not row["accepted"]]
        for row in rejected:
            row["repair_attempted"] = True
        persist()
        repairs, repair_errors = repair_candidates(
            rejected, seed, chapter, chunks, facts.rows, originals, models, trace, FactRepair,
            BACKGROUND_POLICY +
            "You are the original proposer. You have ONE opportunity to correct each rejected candidate. "
            "First decide independently whether a sound correction is possible for the SAME original "
            "knowledge question. If only the link was wrong, preserve the intended factual sentence; a "
            "separate constructor will choose corrected endpoints and predicate. If the claim itself was "
            "wrong, write a corrected simple factual sentence with its own justification and added knowledge. "
            "Keep unknown case-specific information unknown. For a duplicate, propose an actual missing "
            "explanation only if justified; do not just rename concepts. For a connectivity rejection, "
            "use essential.connectivity: it identifies the seed, unconnected concepts, attachment concepts "
            "and actual existing connections. Reuse exact supplied names for the same referents. If a "
            "justified connection is missing, preserve or correct the original assertion in corrected_fact "
            "and put the minimal connecting assertions in connecting_facts, each with its own reason "
            "and original gap IDs. For example, A has B and B does C are separate assertions. An existing "
            "link must not be proposed again. Never invent a relationship merely to pass connectivity. "
            "For other rejection stages return connecting_facts=[]. "
            "Reviewer suggestions are untrusted advice, not facts or authorized graph edits. Do not copy a "
            "suggestion without assessing it. Return corrected_fact=null with a reason if no responsible "
            "correction exists. Any correction will be a separate candidate and must pass every check; "
            "the rejected original stays in the history. No further repair of that correction is allowed.")
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
                for fact in response.get('connecting_facts', []):
                    connection = new_candidate(fact, parent, repair_kind='connection')
                    corrected.append(connection)
                    repair_record.setdefault('connecting_candidate_ids', []).append(connection['id'])
                    trace.emit('debate.repair_created', entity_id=connection['id'], repair_of=identifier,
                               intended_fact=connection['intended_fact'], repair_kind='connection')
            persist()
            finish_item(trace, "background_repair", identifier)
        construct_links(corrected)
        review_wave(corrected)
        persist()
        complete_seed(seed['id'])
    return dict(seeds=seeds, candidates=candidates, transcripts=transcripts,
                document_reviews=document_reviews or [], weights=[], dimensions=["domain_relevance"],
                decision_policy="Sentence-first connected explanations, checked representations, independent debate, and one traced repair")
