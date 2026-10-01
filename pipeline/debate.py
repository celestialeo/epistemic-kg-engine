"""Shared semantic review and chapter-wide novelty checks."""
from typing import Literal
from pydantic import Field, create_model
from .records import Record, batches
from .registry import Concept, FactIndex
from .batching import ask_keyed
from .models import ModelResponseError
from .health import finish_item
from .events import EVENT_POLICY, kind_error


from .relations import DEFAULT_RELATIONS

# Starting vocabulary, not an admission whitelist. New predicates undergo registry review.
BACKGROUND_RELATIONS = set(DEFAULT_RELATIONS)


class Proposal(Record):
    source: Concept | None = None
    target: Concept
    relation: str = Field(min_length=1, max_length=80)
    relation_definition: str = Field(min_length=1, max_length=400)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=800)


class Expansion(Record):
    proposals: list[Proposal] = Field(max_length=3)
    reason: str = Field(min_length=1, max_length=800)


class Review(Record):
    candidate_id: str
    semantics_valid: bool
    direction_valid: bool
    types_valid: bool
    no_contradiction: bool
    certain: bool
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


class BackgroundVerdict(BackgroundReview):
    accept: bool
    objections_resolved: bool


class Novelty(Record):
    status: Literal["new", "duplicate", "contradiction", "uncertain"]
    evidence_ids: list[str]
    reason: str = Field(min_length=1, max_length=800)


COMMON_POLICY = (
    "Evaluate the literal SOURCE relation TARGET under the supplied relation definition and concept senses. "
    "A structural part is not a subtype; an event's location is not its physical component. "
    "Keep direction, causal strength, negation, conditions and specificity. "
    "Never broaden a concept, invent an omitted action, or upgrade 'helps' to 'primary'. "
)
DOCUMENT_POLICY = EVENT_POLICY + COMMON_POLICY + (
    "These are DOCUMENT candidates. The exact quote must entail THIS relation, including both endpoints, meaning, "
    "direction and qualifications; co-occurrence is insufficient. Outside knowledge cannot repair missing evidence. "
    "A quote may span multiple adjacent sentences. Judge entailment, not whether it literally contains the "
    "relation key. Mark quote_too_short only if the supplied source context contains the missing support. "
)
BACKGROUND_POLICY = COMMON_POLICY + (
    "Use a precise predicate appropriate to the asserted meaning; new predicates require schema validation. "
    "These are BACKGROUND candidates. Use well-established general knowledge. Accept a true, correctly directed "
    "relation with compatible endpoint kinds when it involves or explains a topic of the WHOLE chapter. "
    "The overview, topic list and chapter concepts establish scope; no source paragraph or quote is required. "
    "Absence from the text is NOT an objection. Missing text support is never a contradiction. Reject false, uncertain, or off-topic claims. "
    "Set chapter_related=true when you can identify the chapter topic it explains; copy that exact topic into "
    "related_topic. Relevance is to the whole chapter, never just the seed's original paragraph. "
    "Preserve scientific conditions and do not contradict the chapter. Contradiction requires incompatible "
    "assertions, not absence of support. Keep verdicts and explanations consistent and concise. "
    "Background evidence_status must be not_applicable. A model judgment is not external factual verification. "
)
NOVELTY_POLICY = COMMON_POLICY + (
    "Compare background facts against supplied references using their exact meanings. General knowledge may "
    "resolve aliases and implications, but missing text support is not contradiction or uncertainty. "
    "A contradiction needs two incompatible assertions under matching conditions. Do not apply document "
    "quote-entailment requirements to background facts. Do not judge chapter relevance in this comparison. "
)


def index_complete(rows, candidates, trace, role):
    expected = {c["id"] for c in candidates}
    actual = [r.candidate_id for r in rows]
    valid = len(actual) == len(set(actual)) and set(actual) == expected
    trace.emit("debate.ids_validated", role=role, expected=sorted(expected), actual=actual, valid=valid)
    if not valid:
        raise ValueError(f"{role}: return exactly one record per candidate; expected {sorted(expected)}, got {actual}")
    return {r.candidate_id: r.model_dump() for r in rows}


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
            if isinstance(value, BackgroundReview) and value.chapter_related and value.related_topic not in payload["chapter"]["topics"]:
                raise ValueError("A related background fact must cite an exact supplied chapter topic")
    result = models.ask(role, instruction + " Return an object keyed by the exact candidate IDs.",
        payload, schema, entity_id, validator=validate)
    return {identifier: getattr(result, identifier).model_dump() for identifier in fields}


def review_context(row, chunk, outline, concepts):
    row["endpoint_kinds"] = {k: concepts.entries[row[k]]["kind"] for k in ("source", "target")}
    context = {"candidate": {k: row[k] for k in (
        "id", "source", "target", "relation", "relation_definition", "origin", "reason")},
        "concept_senses": [concepts.entries[row[k]] for k in ("source", "target")],
        "chapter": {k: outline[k] for k in ("overview", "topics")}}
    if row["origin"] == "document":
        context.update(quote=row.get("evidence"), source_chunk=row.get("evidence_context", chunk["text"]))
    else:
        context["chapter"]["concepts"] = getattr(concepts, "chapter_names", []) or sorted(concepts.entries)
    return context


def review_candidate(row, chunk, outline, concepts, models, trace, threshold):
    context = review_context(row, chunk, outline, concepts)
    background = row["origin"] == "background"
    policy = BACKGROUND_POLICY if background else DOCUMENT_POLICY
    critic = review_batch(models, "critic", policy +
        "Independently challenge the precise relation. Explain any invalidity and keep boolean checks "
        "consistent with your reasoning. Do not give a category error a passing semantics/types check.",
        context, BackgroundReview if background else Review, [row], trace, row["id"])[row["id"]]
    response = review_batch(models, "proposer_rebuttal", policy +
        "Address the critic's concrete objection. Defend a sound relation or withdraw an unsound one. "
        "Do not change the proposed endpoints or meaning.",
        {**context, "objection": critic["reason"]}, Response, [row], trace, row["id"])[row["id"]]
    # No critic scores, boolean verdicts, confidence, or defend/withdraw position
    # are shown to the judge. It must adjudicate the actual statement and arguments.
    verdict = review_batch(models, "judge", policy +
        "Make your own decision. You see arguments, not other agents' verdicts or scores. "
        "Assess each validity condition independently. An argument conceding or defending a claim is not evidence. "
        "Accept only when all semantic conditions pass and all substantive objections are resolved. "
        "Explain explicitly why a raised objection is resolved or still valid.",
        {**context, "objection": critic["reason"], "reply": response["reason"]},
        BackgroundVerdict if background else DocumentVerdict, [row], trace, row["id"])[row["id"]]
    row.update(critic=critic, rebuttal=response)
    return apply_verdict(row, verdict, trace, threshold)


def apply_verdict(row, verdict, trace, threshold):
    gates = {k: verdict[k] for k in ("semantics_valid", "direction_valid", "types_valid",
                                   "no_contradiction", "certain", "objections_resolved")}
    gates["evidence"] = verdict["evidence_status"] == ("supported" if row["origin"] == "document" else "not_applicable")
    gates["relevance"] = verdict.get("chapter_related", False) if row["origin"] == "background" else verdict["domain_relevance"] >= threshold
    kinds = row.get("endpoint_kinds")
    type_error = kind_error(row["relation"], kinds["source"], kinds["target"]) if kinds else None
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
    # Every source chunk and accepted fact participates, not only the current seed.
    # Chunk text also catches document statements the extractor did not turn into edges.
    references = [{"id": c["id"], "text": c["text"]} for c in chunks]
    references += [{"id": f["id"], "source": f["source"], "target": f["target"],
                    "relation": f["relation"], "relation_definition": f["relation_definition"]} for f in facts.rows]
    checked = []
    for index, page in enumerate(batches(references, 6)):
        allowed = {r["id"] for r in page}
        def validate(result):
            if any(identifier not in allowed for identifier in result.evidence_ids):
                raise ValueError("Evidence IDs must refer to supplied references")
            if result.status in ("duplicate", "contradiction") and not result.evidence_ids:
                raise ValueError("A duplicate or contradiction requires specific reference IDs")
        result = models.ask("novelty_checker", NOVELTY_POLICY +
            "Compare the background candidate against EVERY supplied reference. A duplicate expresses the same fact, "
            "including inverse phrasing, true aliases, and paraphrases. A less precise related fact is not necessarily "
            "a duplicate. A contradiction has mutually incompatible assertions about the same senses and conditions. "
            "Opposite direction alone does not prove contradiction. Missing text support is neither contradiction nor "
            "uncertainty. Return new if none establishes repetition/conflict. If a comparison cannot be resolved, "
            "return uncertain. Cite reference IDs for duplicates/contradictions.",
            {"candidate": {k: row.get(k) for k in ("source", "target", "relation", "relation_definition", "origin")},
             "references": page}, Novelty, f"{row['id']}_novelty_{index}", validator=validate)
        checked.extend(r["id"] for r in page)
        trace.emit("debate.novelty_checked", entity_id=row["id"], references=list(allowed), result=result.model_dump())
        if result.status != "new":
            return result.model_dump()
    return dict(status="new", evidence_ids=[], checked_references=checked,
                reason="No equivalent or contradictory statement found across the chapter and accepted facts")


def check_novelty_many(rows, chunks, facts, models, trace):
    if len(rows) == 1:
        try:
            return {rows[0]["id"]: check_novelty(rows[0], chunks, facts, models, trace)}
        except ModelResponseError as exc:
            return {rows[0]["id"]: dict(status="unresolved", evidence_ids=[], reason=str(exc))}
    results, pending = {}, []
    for row in rows:
        duplicate = facts.find(row)
        if duplicate:
            results[row["id"]] = dict(status="duplicate", evidence_ids=[duplicate["id"]],
                                     reason="Canonical fact already present")
        else:
            pending.append(row)
    references = [{"id": c["id"], "text": c["text"]} for c in chunks]
    references += [{k: f.get(k) for k in ("id", "source", "target", "relation", "relation_definition")} for f in facts.rows]
    checked = []
    for index, page in enumerate(batches(references, 6)):
        if not pending:
            break
        allowed = {r["id"] for r in page}
        def validate(item, result):
            if any(i not in allowed for i in result.evidence_ids):
                raise ValueError("Cite only supplied reference IDs")
            if result.status in ("duplicate", "contradiction") and not result.evidence_ids:
                raise ValueError("Duplicate/contradiction requires specific reference IDs")
        items = [dict(id=r["id"], candidate={k: r.get(k) for k in
                 ("source", "target", "relation", "relation_definition", "origin")}) for r in pending]
        errors = {}
        judgments = ask_keyed(models, "novelty_checker", NOVELTY_POLICY +
            "Compare EACH candidate against EVERY reference. Return duplicate only for equivalent assertions "
            "including inverse phrasing and true aliases; similarity is insufficient. Contradiction requires "
            "mutually incompatible assertions under the same conditions, not just reversed direction. "
            "Missing source support is not contradiction or uncertainty. Return new when no reference repeats "
            "or contradicts it, uncertain only when a specific comparison cannot be resolved. Cite reference IDs.",
            items, Novelty, f"novelty_batch_{pending[0]['id']}_{index}",
            shared={"references": page}, validate=validate,
            on_error=lambda item, exc: errors.update({item["id"]: str(exc)}))
        checked.extend(r["id"] for r in page)
        remaining = []
        for row in pending:
            if row["id"] in errors:
                results[row["id"]] = dict(status="unresolved", evidence_ids=[], reason=errors[row["id"]])
                continue
            judgment = judgments[row["id"]]
            trace.emit("debate.novelty_checked", entity_id=row["id"], references=list(allowed), result=judgment)
            if judgment["status"] == "new":
                remaining.append(row)
            else:
                results[row["id"]] = judgment
        pending = remaining
    for row in pending:
        results[row["id"]] = dict(status="new", evidence_ids=[], checked_references=checked,
                                 reason="No equivalent or contradictory statement found across all references")
    return results


def unresolved_candidate(row, error, trace):
    row.update(accepted=False, review_status="unresolved", score=None,
               decision_reason="No validated background decision: " + str(error))
    trace.emit("debate.unresolved", entity_id=row["id"], decision=row, error=str(error))


def review_background_many(rows, by_chunk, outline, concepts, models, trace):
    if len(rows) == 1:
        row = rows[0]
        try:
            review_candidate(row, by_chunk[row["chunk_id"]], outline, concepts, models, trace, 0)
        except ModelResponseError as exc:
            unresolved_candidate(row, exc, trace)
        return
    if not rows:
        return
    items = [dict(id=r["id"], **review_context(r, by_chunk[r["chunk_id"]], outline, concepts)) for r in rows]
    chapter = items[0]["chapter"]
    for item in items:
        item.pop("chapter")
    by_id = {row["id"]: row for row in rows}
    def on_error(item, exc):
        unresolved_candidate(by_id[item["id"]], exc, trace)
    def validate(item, result):
        if result.candidate_id != item["id"]:
            raise ValueError("candidate_id must match item ID")
        if isinstance(result, BackgroundReview) and result.chapter_related and result.related_topic not in chapter["topics"]:
            raise ValueError("A related background fact must cite an exact supplied chapter topic")
    reviews = ask_keyed(models, "critic", BACKGROUND_POLICY +
        "Challenge EACH precise statement independently. Keep each validity check consistent with your reason.",
        items, BackgroundReview, rows[0]["id"], shared={"chapter": chapter}, validate=validate, on_error=on_error)
    items = [item for item in items if item["id"] in reviews]
    replies = ask_keyed(models, "proposer_rebuttal", BACKGROUND_POLICY +
        "For EACH candidate address its specific objection. Defend sound claims or withdraw unsound ones; "
        "do not alter the relation or endpoints.",
        [dict(item, objection=reviews[item["id"]]["reason"]) for item in items],
        Response, rows[0]["id"], shared={"chapter": chapter}, validate=validate, on_error=on_error)
    items = [item for item in items if item["id"] in replies]
    verdicts = ask_keyed(models, "judge", BACKGROUND_POLICY +
        "Independently adjudicate EACH statement and its arguments. Accept only when every semantic condition "
        "passes and substantive objections are resolved. Concession or confidence is not evidence. "
        "Explain precisely why an objection is resolved or still valid.",
        [dict(item, objection=reviews[item["id"]]["reason"], reply=replies[item["id"]]["reason"]) for item in items],
        BackgroundVerdict, rows[0]["id"], shared={"chapter": chapter}, validate=validate, on_error=on_error)
    for row in rows:
        if row["id"] not in verdicts:
            continue
        row.update(critic=reviews[row["id"]], rebuttal=replies[row["id"]])
        apply_verdict(row, verdicts[row["id"]], trace, 0)


def debate(seeds, chunks, outline, concepts, relations, facts, models, trace, document_reviews=None):
    candidates, transcripts = [], []
    seen_proposals = []
    by_chunk = {c["id"]: c for c in chunks}
    for seed in seeds:
        print(f"  Debate {seed['id']}: {seed['concept']}", flush=True)
        known = [{k: fact[k] for k in ("id", "source", "relation", "target", "relation_definition", "origin")}
                 for fact in facts.rows if seed["concept"] in (fact["source"], fact["target"])]
        try:
            proposal = models.ask("proposer", BACKGROUND_POLICY +
                "Propose zero to three precise BACKGROUND relations involving the seed at either endpoint. Add useful unstated "
                "knowledge, not restatements. No requirement for a parent/sibling/child tier. "
                "Reuse an appropriate supplied predicate, or propose a new reusable predicate with its precise definition. "
                "Supply both endpoint definitions/kinds; source=null means the seed itself. "
                "Check the gap question's premise and scope. Abstain when numeric thresholds or mechanisms require "
                "missing measurements, conditions, or external evidence. Never fill a quota or invent a vague peer. "
                "Do not use SOURCE as TARGET. Read known_seed_facts before proposing: do not repeat them, "
                "their inverses, or paraphrases. Prefer answering the seed's background_question. "
                "Use short canonical singular names; definitions may be detailed.",
                {"seed": {k: seed[k] for k in ("concept", "definition", "kind")},
                 "chapter": {**{k: outline[k] for k in ("overview", "topics")},
                             "concepts": getattr(concepts, "chapter_names", []) or sorted(concepts.entries)},
                 "background_question": seed.get("background_question"), "known_seed_facts": known,
                 "available_relations": dict(relations.entries)},
                Expansion, seed["id"])
        except ModelResponseError as exc:
            transcripts.append(dict(seed=seed, proposal=None, candidate_ids=[], status="unresolved", reason=str(exc)))
            trace.save("artifacts/debate_progress.json", dict(candidates=candidates, transcripts=transcripts))
            finish_item(trace, "background_proposal", seed["id"], exc)
            continue
        finish_item(trace, "background_proposal", seed["id"])
        transcript = {"seed": seed, "proposal": proposal.model_dump(), "candidate_ids": []}
        current = []
        pending = [(seed["concept"], value) for value in proposal.proposals]
        for source, value in pending:
            identifier = f"candidate_{len(candidates)+1:04d}"
            context = outline["overview"] + " " + value.reason
            try:
                if value.source is not None:
                    source = concepts.resolve(value.source, context, identifier)
                target = concepts.resolve(value.target, context, identifier)
                relation = relations.resolve(value.relation, value.relation_definition, source, target,
                                             context, identifier)
            except ModelResponseError as exc:
                row = dict(id=identifier, seed_id=seed["id"], source=source, target=value.target.name,
                    relation=value.relation, relation_definition=value.relation_definition,
                    origin="background", reason=value.reason, chunk_id=seed["chunk_id"],
                    paragraph_id=seed["paragraph_id"])
                unresolved_candidate(row, exc, trace)
                candidates.append(row)
                transcript["candidate_ids"].append(identifier)
                continue
            row = dict(id=identifier, seed_id=seed["id"], source=source, target=target,
                relation=relation or value.relation, relation_definition=value.relation_definition,
                surface_relation=value.relation, surface_target=value.target.name,
                confidence=value.confidence, reason=value.reason, chunk_id=seed["chunk_id"],
                paragraph_id=seed["paragraph_id"], origin="background", tier="related",
                accepted=False, score=None, decision_reason="Unverified relation, self relation, or low confidence")
            candidates.append(row)
            transcript["candidate_ids"].append(identifier)
            trace.emit("debate.proposed", entity_id=identifier, proposal=row.copy())
            error = kind_error(relation, concepts.entries[source]["kind"], concepts.entries[target]["kind"])
            if error:
                row["decision_reason"] = error
            if seed["concept"] not in (source, target):
                row["decision_reason"] = "Neither endpoint resolves to the seed"
                continue
            if relation and not error and target != source and value.confidence >= .5:
                row["relation_definition"] = relations.entries[relation]["definition"]
                key = relations.fact_key(row["source"], relation, target)
                previous = next((p for p in seen_proposals
                    if p.get("review_status") != "unresolved"
                    and relations.fact_key(p["source"], p["relation"], p["target"]) == key), None)
                seen_proposals.append(row)
                if previous:
                    row["novelty"] = dict(status="duplicate", evidence_ids=[previous["id"]],
                                         reason="Equivalent proposal already considered under another seed")
                    row["decision_reason"] = row["novelty"]["reason"]
                else:
                    current.append(row)
        novelties = check_novelty_many(current, chunks, facts, models, trace) if current else {}
        novel = []
        for row in current:
            row["novelty"] = novelties[row["id"]]
            if row["novelty"]["status"] == "new":
                novel.append(row)
            elif row["novelty"]["status"] == "unresolved":
                unresolved_candidate(row, row["novelty"]["reason"], trace)
            else:
                row["decision_reason"] = row["novelty"]["reason"]
        review_background_many(novel, by_chunk, outline, concepts, models, trace)
        # Novelty batches used the fact index as it stood before the batch.
        # Recheck against newly admitted batch peers to preserve global novelty.
        delta = FactIndex(relations)
        approved = []
        for row in sorted(novel, key=lambda r: r["relation"] != "acts_on"):
            if row["accepted"]:
                try:
                    peer = check_novelty(row, [], delta, models, trace)
                except ModelResponseError as exc:
                    unresolved_candidate(row, exc, trace)
                    continue
                if peer["status"] != "new":
                    row.update(accepted=False, novelty=peer, decision_reason=peer["reason"])
                else:
                    delta.add(row)
                    approved.append(row)
        for row in approved:
            if row["accepted"]:
                facts.add(row)
        for row in candidates:
            if row["seed_id"] == seed["id"]:
                row.setdefault("review_status", "completed")
                trace.emit("debate.decision", entity_id=row["id"], decision=row)
                trace.save("artifacts/debate_progress.json", dict(candidates=candidates, transcripts=transcripts + [transcript]))
                finish_item(trace, "background_candidate", row["id"],
                            row["decision_reason"] if row["review_status"] == "unresolved" else None)
        transcripts.append(transcript)
        trace.save("artifacts/debate_progress.json", dict(candidates=candidates, transcripts=transcripts))
    return dict(seeds=seeds, candidates=candidates, transcripts=transcripts,
                document_reviews=document_reviews or [], weights=[], dimensions=["domain_relevance"],
                decision_policy="Independent judge plus mandatory semantic, evidence and relevance gates")
