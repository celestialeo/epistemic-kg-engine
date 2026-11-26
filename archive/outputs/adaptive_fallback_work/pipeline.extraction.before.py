from .settings import setting
"""Self-contained relation endpoints, local repair and adaptive extraction."""
from typing import Literal
import re
from pydantic import Field, ValidationError
from .qualifiers import correct_polarity
from .records import Record, normalize, normalize_name, name_occurs
from .registry import Concept, ConceptKind
from .models import ModelResponseError, OutputLimitError
from .health import finish_item
from .events import EVENT_POLICY, kind_error


class Endpoint(Record):
    """Complete metadata is required by the generation schema, not repaired later."""
    name: str = Field(min_length=1, max_length=setting('text', 'name_chars'),
        description="Standalone concept name, not a statement or descriptive clause")
    definition: str = Field(min_length=1, max_length=setting('text', 'definition_chars'), description="Required concise definition of this concept in context")
    kind: ConceptKind = Field(description="Choose one broad semantic kind from the enum")
    form: Literal["concept"] = Field(default="concept",
        description="Only standalone concepts are allowed as graph endpoints")
    reference_phrase: str | None = Field(default=None,
        description="Exact current-sentence reference phrase, if this mention resolves one")
    kind_detail: str | None = Field(default=None, max_length=setting('text', 'detail_chars'),
        description="Optional short domain category; not a definition or function")


class Relation(Record):
    source: Endpoint
    relation: str = Field(min_length=1, max_length=setting('text', 'raw_predicate_chars'))
    relation_definition: str = Field(min_length=1, max_length=setting('text', 'definition_chars'))
    target: Endpoint
    argument_qualifiers: list[str] = Field(default_factory=list,
        description="Essential action complements, results or additional participants absent from the two endpoints; e.g. what an actor is prevented from doing. These are not if/when conditions. Empty only for a complete binary assertion.")
    conditions: str | None = Field(default=None, description="When or under what circumstances this assertion holds; not additional participants or action complements")
    modality: str | None = Field(default=None, description="Negation or modality such as not, may, can, usually; null if unqualified")
    evidence: str = Field(min_length=1, description="Exact continuous source quote overlapping CURRENT_SENTENCE; include supplied adjacent sentences only to complete support")

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler(core_schema)
        schema = handler.resolve_ref_schema(schema)
        schema['required'] = list(dict.fromkeys([*schema.get('required', []), 'argument_qualifiers', 'conditions', 'modality']))
        return schema


class Claim(Record):
    text: str = Field(min_length=1)
    evidence: str = Field(min_length=1, description="Exact continuous source quote overlapping CURRENT_SENTENCE")


class Extraction(Record):
    unit_kind: Literal["core_statement", "definition", "example", "other"]
    concepts: list[Endpoint] = Field(description="Standalone concepts useful for seeds; relation endpoints need not be repeated here")
    claims: list[Claim]
    relations: list[Relation]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))


class EndpointRepair(Record):
    concept: Concept | None
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))


class QuoteRepair(Record):
    collection: Literal["claims", "relations"]
    index: int = Field(ge=0)
    record: Claim | Relation | None = Field(description="Corrected record, or null if no faithful correction exists")
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))


class QuoteRepairs(Record):
    records: list[QuoteRepair]


REFERENCE_POLICY = (
    "A leading definite article alone does not make a name an unresolved reference: "
    "'the ConceptA' can be named 'ConceptA'. Resolve pronouns and demonstratives anywhere "
    "inside a name, including its, their, them, and those, using the supplied sentences. "
    "Replace each reference with its text-supported antecedent while preserving the full "
    "concept, its owner, and its scope. If ConceptA has parts, 'the structure of its parts' "
    "can become 'structure of ConceptA's parts'; do not reduce it to ConceptA or to parts. "
    "For a chain of references, follow the supplied earlier sentences to the explicit antecedent. "
    "Such a standalone reformulation need not occur verbatim or already exist in the registry. "
    "Do not invent an antecedent when the supplied text leaves it ambiguous. "
)


INSTRUCTION = (
    "Extract only from CURRENT_SENTENCE. Use PREVIOUS_SENTENCE, optional REFERENCE_CONTEXT and NEXT_SENTENCE only to resolve "
    "references and clarify its meaning, never to extract their separate claims. "
    "Represent every substantive assertion as one or more directed source-predicate-target relationships. "
    "Predicates are OPEN VOCABULARY: write the verb or phrase that accurately expresses the source. "
    "There is no whitelist and no need for a pre-existing relation name. Ordinary actions, measurements, "
    "descriptions, definitions and NEGATIVE assertions are all valid relationships. "
    "Prefer one to three words in snake_case; use more words when necessary to preserve meaning. "
    "Write a concise reusable definition of the predicate using SOURCE and TARGET. "
    "A negative assertion can use the positive predicate with modality='does not'; never omit negation. "
    "Keep may/can/usually and similar uncertainty in modality. Keep conditions, exceptions, timing and "
    "other necessary participants explicitly in argument_qualifiers or in a complete endpoint name. "
    "Use argument_qualifiers for the activity being prevented/enabled, transformation result, comparison partner "
    "and other essential complements. Do not turn another participant into an if-condition. "
    "Resolve references inside qualifiers to their source-supported antecedents. "
    "Always return argument_qualifiers, conditions and modality: use null only when none is stated. Do not write boilerplate "
    "such as certainty or asserts. A temporal phrase, if-clause, purpose or prerequisite belongs in conditions. "
    "Endpoints name standalone concepts including processes and properties, not whole assertions. "
    "Preserve each participant's owner and scope; a property, change in that property and its owner "
    "are distinct concepts. Use causal predicates only when the source states causation. "
    "Split conjunctions into their distinct assertions without losing their shared conditions. "
    "Abstract examples only: 'ConceptA may influence ConceptB under ConditionC' gives ConceptA -> "
    "influences -> ConceptB, modality='may', conditions='under ConditionC'. 'PropertyQ does not establish "
    "ProcessP' gives PropertyQ -> establishes -> ProcessP, modality='does not'. Never copy these placeholders. "
    + REFERENCE_POLICY +
    "Every claim and relation needs an exact continuous source quote overlapping CURRENT_SENTENCE. "
    "Keep evidence verbatim even when claim text or endpoints resolve a pronoun. Put the original "
    "reference phrase in reference_phrase; never substitute an explanation for a quotation. "
    "The quote may include supplied adjacent text when needed to resolve references. "
    "Capture the literal direction and degree of support; do not strengthen an association into causation "
    "or a possibility into certainty. Do not infer unstated background facts. "
    "Record claims in addition to their relationships so source coverage can be checked. A claim without "
    "a relationship is appropriate only if a faithful connection genuinely cannot express it; lack of an "
    "existing predicate is never a reason. Relation endpoints need not also be repeated in concepts. "
    "Return all substantive relationships without a count quota. Give a short conclusion in reason."
)


def validate_events(result):
    for row in result.relations:
        error = kind_error(row.relation, row.source.kind, row.target.kind)
        if error:
            raise ValueError(error + "; correct the relationship without inventing an event or companion edge")


def split_unit(text):
    """Prefer a sentence boundary near the midpoint; use words for a long sentence."""
    boundaries = [m.end() for m in re.finditer(r"(?<=[.!?])\s+(?=\S)", text)]
    mode = "sentence"
    if not boundaries:
        boundaries = [m.start() for m in list(re.finditer(r"\S+", text))[1:]]
        mode = "word"
    if not boundaries:
        return None
    cut = min(boundaries, key=lambda b: abs(b - len(text) / 2))
    return cut, mode


def evidence_context(chunk, paragraph):
    """Up to three preceding sentences for reference chains, with exact offsets."""
    before = paragraph["text"][:chunk["start"] - paragraph["start"]]
    after = paragraph["text"][chunk["end"] - paragraph["start"]:]
    before = before.rstrip()
    boundaries = list(re.finditer(r"(?<=[.!?])\s+(?=\S)", before))
    # Retain the preceding complete sentence even when the chunk starts midway
    # through a long sentence split at a word boundary.
    boundary_index = -3 if re.search(r"[.!?]$", before) else -4
    left = boundaries[boundary_index].end() if len(boundaries) >= abs(boundary_index) else 0
    ending = re.search(r"[.!?](?=\s|$)", after)
    right = ending.end() if ending else len(after)
    start = paragraph["start"] + left
    end = chunk["end"] + right
    return dict(start=start, end=end, text=paragraph["text"][left:end-paragraph["start"]])


def previous_sentence(context, start):
    before = context["text"][:max(0, start - context["start"])].rstrip()
    sentences = re.split(r"(?<=[.!?])\s+(?=\S)", before)
    # A word-split unit can have an unfinished current sentence before it.
    if sentences and not re.search(r"[.!?]$", sentences[-1]):
        sentences.pop()
    return sentences[-1].strip() if sentences else context.get("preceding_sentence", "")


def reference_name(name):
    """Detect contextual references anywhere, not ordinary definite noun names."""
    normalized = normalize_name(name)
    return normalized in {"the", "some"} or bool(re.search(
        r"\b(?:this|that|these|those|it|its|itself|they|them|their|theirs|themselves)\b", normalized))


def reference_context(unit, context):
    """Bounded verbatim antecedent context; never a source of separate claims."""
    before = context["text"][:max(0, unit["start"] - context["start"])].rstrip()
    sentences = re.split(r"(?<=[.!?])\s+(?=\S)", before)
    if sentences and not re.search(r"[.!?]$", sentences[-1]):
        sentences.pop()
    return " ".join(sentences[-3:]) or context.get("preceding_sentence", "")


def strip_definite_article(name):
    """Remove only the leading article; preserve the named concept and its scope."""
    return re.sub(r"^the\s+(?=\S)", "", name.strip(), flags=re.IGNORECASE)


def sentence_payload(unit, context, relations):
    """Send each source span once; look ahead only for an adjacent naming clause."""
    payload = dict(CURRENT_SENTENCE=unit["text"],
                   PREVIOUS_SENTENCE=previous_sentence(context, unit["start"]),
                   predicate_policy='Open vocabulary; generate precise source-supported predicates.')
    if reference_name(unit["text"]):
        earlier = reference_context(unit, context)
        if earlier != payload["PREVIOUS_SENTENCE"]:
            payload["REFERENCE_CONTEXT"] = earlier
    after = context["text"][unit["end"] - context["start"]:].lstrip()
    following = re.split(r"(?<=[.!?])\s+(?=\S)", after, maxsplit=1)[0]
    # Explicit anaphoric naming, including short copular definitions. Ordinary
    # following assertions are not context for the current extraction.
    if re.match(r"^(?:this|that|these|those|it|they)\b(?:\s+[\w-]+){0,4}\s+"
                r"(?:is|are|was|were)\s+(?:(?:also\s+)?(?:called|named|termed|known as)\s+.+|"
                r"(?:[\w-]+\s+){0,3}[\w-]+[.!?])$", following, re.IGNORECASE):
        payload["NEXT_SENTENCE"] = following
    return payload


def extraction_units(chunk, models, trace, relations, context=None):
    # Splitting only changes model work units. Original chunk IDs, offsets,
    # outline segments, graph structure and evaluation alignment remain stable.
    boundaries = [0, *[m.end() for m in re.finditer(r"(?<=[.!?])\s+(?=\S)", chunk["text"])], len(chunk["text"])]
    spans = [(left, right) for left, right in zip(boundaries, boundaries[1:]) if chunk["text"][left:right].strip()]
    stack = [(chunk["id"] if len(spans) == 1 else f"{chunk['id']}_sentence_{index:03d}",
              left, chunk["text"][left:right]) for index, (left, right) in enumerate(spans, 1)][::-1]
    while stack:
        identifier, offset, text = stack.pop()
        unit = dict(id=identifier, start=chunk["start"] + offset,
                    end=chunk["start"] + offset + len(text), text=text)
        payload = sentence_payload(unit, context or chunk, relations)
        try:
            # Semantic errors belong to individual records. A single invalid
            # predicate must not discard other valid assertions in the sentence.
            result = models.ask("extractor", INSTRUCTION, payload, Extraction, identifier)
        except OutputLimitError as exc:
            split = split_unit(text)
            if split:
                cut, mode = split
                trace.emit("extraction.unit_split", entity_id=identifier, chunk_id=chunk["id"], unit=unit,
                           boundary=unit["start"] + cut, method=mode, reason=str(exc))
                stack.append((identifier + "_right", offset + cut, text[cut:]))
                stack.append((identifier + "_left", offset, text[:cut]))
                continue
            yield unit, None, str(exc) + "; no smaller word-bounded unit is available"
            continue
        except ModelResponseError as exc:
            yield unit, None, str(exc)
            continue
        yield unit, result, None


def complete_endpoint(endpoint, record, side, text, models, trace, identifier):
    original = endpoint.model_dump(exclude={"reference_phrase"})
    try:
        return Concept.model_validate(original)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
    invalid_fields = {e["loc"][0] for e in errors}
    trace.emit("extraction.endpoint_repair_requested", entity_id=identifier, side=side,
               endpoint=original, errors=errors)
    def validate(result):
        if result.concept is None:
            return
        repaired = result.concept.model_dump()
        if normalize(repaired["name"]) != normalize(original["name"]):
            raise ValueError("Repair must preserve the endpoint name; alias resolution happens afterward")
        changed = [k for k in original if k not in invalid_fields and repaired[k] != original[k]]
        if changed:
            raise ValueError(f"Repair changed already valid fields: {changed}; fix only {sorted(invalid_fields)}")
    try:
        result = models.ask("concept_endpoint_repair",
            "Repair only the listed missing or invalid metadata for this one endpoint. "
            "Preserve its name, sense and already valid fields. Do not change the relationship or its direction. "
            "Use the source text and record to identify its meaning; do not invent an unsupported concept. "
            "Return concept=null with a reason if the intended meaning cannot be resolved. "
            "The repaired concept will still undergo identity and semantic evidence review.",
            {"endpoint": original, "side": side, "record": record, "source_text": text,
             "invalid_fields": sorted(invalid_fields), "validation_errors": errors},
            EndpointRepair, identifier, validator=validate)
    except ModelResponseError as exc:
        trace.emit("extraction.endpoint_repair_failed", entity_id=identifier, side=side, error=str(exc))
        return None
    trace.emit("extraction.endpoint_repair_completed", entity_id=identifier, side=side, result=result.model_dump())
    return result.concept


def resolve_endpoint(endpoint, record, side, unit, context, concepts, models, trace, identifier, cache):
    reference = endpoint.reference_phrase or (endpoint.name if reference_name(endpoint.name) else None)
    if reference is None:
        # Models sometimes omit reference_phrase while copying only the property noun.
        # Recover an exact possessive mention, leaving antecedent selection to the resolver.
        noun = re.escape(strip_definite_article(endpoint.name))
        mentions = list(re.finditer(r"\b" + noun + r"\b", unit["text"], re.I))
        owned = re.search(r"\b(?:its|their)\s+" + noun + r"\b", unit["text"], re.I)
        if owned and len(mentions) == 1:
            reference = owned.group()
    if reference is None:
        endpoint = endpoint.model_copy(update={"name": strip_definite_article(endpoint.name)})
        return complete_endpoint(endpoint, record, side, context["text"], models, trace, identifier)
    if normalize(reference) not in normalize(unit["text"]):
        return None
    key = (reference, endpoint.name, endpoint.definition)
    if key in cache:
        return cache[key]
    before = previous_sentence(context, unit["start"])
    earlier = reference_context(unit, context)
    available = [entry for entry in concepts.entries.values()
                 if any(name_occurs(name, earlier + " " + unit["text"])
                        for name in [entry["name"], *entry.get("aliases", [])])]

    def validate(result):
        if result.concept is not None and reference_name(result.concept.name):
            raise ValueError("Return a standalone concept name: replace remaining pronouns or demonstratives "
                             "with their text-supported antecedents, preserving the concept and its scope")

    try:
        result = models.ask("concept_reference_resolver",
            "Resolve this reference phrase using CURRENT_SENTENCE and the verbatim REFERENCE_CONTEXT. "
            "Return the standalone concept it denotes, using an available canonical name when it is the same "
            "concept. You may return an existing concept or a standalone reformulation grounded in the "
            "supplied sentences even if it is not registered yet. Not being in the registry is never a "
            "reason to leave a reference unresolved. "
            + REFERENCE_POLICY +
            "For 'This process is ProcessP', return ProcessP; for 'The rate also depends on PropertyQ' "
            "after a sentence about ProcessP, return the rate of ProcessP. A rate is a property of a process, "
            "not the process itself. Do not turn a statement into a concept or invent a referent. "
            "Return concept=null (ambiguous) only when the text genuinely leaves the referent unclear. "
            "The reference joins its referent "
            "and must never become a separate candidate.",
            dict(reference_phrase=reference, proposed_concept=endpoint.model_dump(exclude={"reference_phrase"}),
                 PREVIOUS_SENTENCE=before, REFERENCE_CONTEXT=earlier,
                 CURRENT_SENTENCE=unit["text"], available_concepts=available),
            EndpointRepair, identifier, validator=validate)
    except ModelResponseError as exc:
        trace.emit("extraction.reference_unresolved", entity_id=identifier, reference=reference, error=str(exc))
        cache[key] = None
        return None
    if result.concept is not None:
        result = result.model_copy(update={"concept": result.concept.model_copy(
            update={"name": strip_definite_article(result.concept.name)})})
    trace.emit("extraction.reference_resolved", entity_id=identifier, reference=reference,
               previous_sentence=before, result=result.model_dump())
    cache[key] = result.concept
    return result.concept


def grounded_records(result, unit, context, models, relations, trace):
    """Keep good records and repair quote or endpoint-role errors locally."""
    accepted = {"claims": [], "relations": []}
    failed = []

    def quoted(record, collection, index, attempt):
        row = record.model_dump()
        occurrences = list(re.finditer(re.escape(row["evidence"]), context["text"]))
        match = next((m for m in occurrences if context["start"] + m.start() < unit["end"]
                      and context["start"] + m.end() > unit["start"]), None)
        trace.emit("extraction.evidence_checked", entity_id=unit["id"], collection=collection,
                   index=index, attempt=attempt, valid=match is not None, record=row)
        if match is None:
            return row, ("Quote is not an exact continuous source substring" if not occurrences else
                         "Quote is exact source text but does not overlap CURRENT_SENTENCE")
        row["evidence_start"] = context["start"] + match.start()
        row["evidence_end"] = context["start"] + match.end()
        if isinstance(record, Relation):
            error = kind_error(record.relation, record.source.kind, record.target.kind)
            if error:
                return row, error + '; choose a predicate matching these participants, not a different participant kind'
        return row, None

    for collection in accepted:
        for index, record in enumerate(getattr(result, collection)):
            row, error = quoted(record, collection, index, 0)
            if error:
                failed.append(dict(collection=collection, index=index, record=row, reason=error))
            else:
                accepted[collection].append((index, record, row))
    if not failed:
        return accepted, []

    def validate(repairs):
        expected = {(f["collection"], f["index"]) for f in failed}
        keys = [(r.collection, r.index) for r in repairs.records]
        if len(keys) != len(expected) or set(keys) != expected:
            raise ValueError("Return exactly one repair for each failed collection/index, with no other records")
        for repair in repairs.records:
            if repair.record is None:
                continue
            schema = Claim if repair.collection == "claims" else Relation
            if not isinstance(repair.record, schema):
                raise ValueError("Repair record must match its collection")
            if isinstance(repair.record, Relation):
                error = kind_error(repair.record.relation, repair.record.source.kind, repair.record.target.kind)
                if error:
                    raise ValueError(error)

    payload = sentence_payload(unit, context, relations)
    payload["failed_records"] = failed
    trace.emit("extraction.quote_retry_requested", entity_id=unit["id"], failed_records=failed)
    try:
        repairs = models.ask("extractor_quote_repair", INSTRUCTION +
            " Repair only failed_records for this sentence, using each specific failure reason. "
            "Return exactly one entry with the same collection and index per failed record. "
            "Records that already passed are retained separately; do not return or replace them. "
            "Correct the quote and assertion faithfully, or return record=null with a reason if unsupported. "
            "Every corrected record will undergo the same quote, overlap and semantic checks.",
            payload, QuoteRepairs, unit["id"] + "_quote_retry", validator=validate)
    except ModelResponseError as exc:
        trace.emit("extraction.quote_retry_failed", entity_id=unit["id"], error=str(exc))
        return accepted, [dict(f, reason=f"{f['reason']}; quote retry failed: {exc}") for f in failed]

    originals = {(f["collection"], f["index"]): f for f in failed}
    unresolved = []
    for repair in repairs.records:
        original = originals[(repair.collection, repair.index)]
        if repair.record is None:
            unresolved.append(dict(original, reason=f"{original['reason']}; {repair.reason}"))
            continue
        row, error = quoted(repair.record, repair.collection, repair.index, 1)
        if error:
            unresolved.append(dict(collection=repair.collection, index=repair.index, record=row,
                                   reason=error + "; still invalid after one quote retry"))
        else:
            accepted[repair.collection].append((repair.index, repair.record, row))
    for records in accepted.values():
        records.sort(key=lambda item: item[0])
    trace.emit("extraction.quote_retry_completed", entity_id=unit["id"],
               recovered=len(failed) - len(unresolved), unresolved=len(unresolved))
    return accepted, unresolved


def extract(chunks, paragraphs, models, trace, concepts, relations):
    results = []
    by_paragraph = {p["id"]: p for p in paragraphs}
    preceding = {current["id"]: re.split(r"(?<=[.!?])\s+(?=\S)", previous["text"].strip())[-1]
                 for previous, current in zip(paragraphs, paragraphs[1:])}
    for chunk in chunks:
        context = evidence_context(chunk, by_paragraph[chunk["paragraph_id"]])
        if context["start"] == by_paragraph[chunk["paragraph_id"]]["start"]:
            context["preceding_sentence"] = preceding.get(chunk["paragraph_id"], "")
        print(f"  Extracting {chunk['id']}", flush=True)
        data = dict(chunk_id=chunk["id"], unit_kind="other", confidence=0., reason="",
                    concepts=[], claims=[], relations=[], relation_proposals=[], units=[], issues=[])
        kinds, reasons, weight = [], [], 0
        serial = 0
        outcomes = {}

        def issue(identifier, reason, record):
            row = dict(id=identifier, reason=reason, record=record)
            data["issues"].append(row)
            trace.emit("extraction.unresolved", entity_id=identifier, chunk_id=chunk["id"], **row)
            outcomes[identifier] = reason

        for unit, result, error in extraction_units(chunk, models, trace, relations, context):
            reference_cache = {}
            issue_count = len(data["issues"])
            if error:
                # No usable records exist for this response. Count one final
                # unresolved item alongside the records from healthy sentences.
                issue(unit["id"], error, unit)
                data["units"].append(dict(unit, status="incomplete"))
                continue
            kinds.append(result.unit_kind)
            reasons.append(result.reason)
            size = len(unit["text"].split())
            data["confidence"] += result.confidence * size
            weight += size
            record_ids = {}
            for collection in ("claims", "relations"):
                for index, _ in enumerate(getattr(result, collection)):
                    if collection == "relations":
                        serial += 1
                        identifier = f"{chunk['id']}_relation_{serial:03d}"
                    else:
                        identifier = f"{unit['id']}_claims_{index}"
                    record_ids[(collection, index)] = identifier
                    outcomes[identifier] = None
            grounded, failures = grounded_records(result, unit, context, models, relations, trace)
            for failure in failures:
                identifier = record_ids[(failure["collection"], failure["index"])]
                trace.emit("extraction.record_rejected", entity_id=identifier,
                           record=failure["record"], reason=failure["reason"])
                issue(identifier, failure["reason"], failure["record"])
            for index, _, row in grounded["claims"]:
                data["claims"].append(row)
            for mention_index, mention in enumerate(result.concepts, 1):
                if not name_occurs(mention.reference_phrase or mention.name, unit["text"]):
                    continue
                identifier = unit["id"] + "_concept_" + str(mention_index)
                outcomes[identifier] = None
                complete = resolve_endpoint(mention, mention.model_dump(), "concept", unit, context,
                                            concepts, models, trace, identifier, reference_cache)
                if complete is None:
                    issue(identifier, "Standalone concept metadata could not be resolved", mention.model_dump())
                    continue
                try:
                    data["concepts"].append(concepts.resolve(complete, context["text"], identifier))
                except ModelResponseError as exc:
                    issue(identifier, f"Concept identity review unresolved: {exc}", mention.model_dump())
            for index, relation, row in grounded["relations"]:
                identifier = record_ids[("relations", index)]
                try:
                    row = correct_polarity(row, context['text'], models, trace, identifier + '_polarity')
                    relation = relation.model_copy(update={k: row[k] for k in ('relation', 'relation_definition', 'modality')})
                except ModelResponseError as exc:
                    issue(identifier, f'Polarity correction unresolved: {exc}', row)
                    continue
                endpoints = []
                for side in ("source", "target"):
                    endpoint = getattr(relation, side)
                    endpoints.append(resolve_endpoint(endpoint, row, side, unit, context, concepts,
                                                      models, trace, identifier + "_" + side, reference_cache))
                if any(endpoint is None for endpoint in endpoints):
                    issue(identifier, "Relation endpoint metadata could not be resolved", row)
                    continue
                # Route every complete endpoint through the shared name identity.
                # Context remains on its relationships, never in a second node.
                try:
                    source, target = [concepts.resolve(e, row["evidence"], identifier) for e in endpoints]
                    data["concepts"].extend((source, target))
                    if source == target:
                        trace.emit("extraction.record_rejected", entity_id=identifier, record=row,
                                   reason="Reference resolution produced a self relation; concept and claims retained")
                        continue
                    key = relations.resolve(row["relation"], row["relation_definition"], source, target,
                                            dict(evidence=row["evidence"], conditions=row.get("conditions"),
                                                 modality=row.get("modality"), argument_qualifiers=row.get("argument_qualifiers", [])), identifier)
                except ModelResponseError as exc:
                    issue(identifier, f"Relation normalization unresolved: {exc}", row)
                    continue
                if key is None:
                    trace.emit("extraction.record_rejected", entity_id=identifier, record=row,
                               reason="Unverified relation meaning")
                    continue
                data["relation_proposals"].append({**row, "source_mention": endpoints[0].model_dump(),
                    "target_mention": endpoints[1].model_dump(),
                    "surface_source": relation.source.reference_phrase or relation.source.name,
                    "surface_target": relation.target.reference_phrase or relation.target.name,
                    "surface_relation": row["relation"],
                    "source": source, "target": target, "relation": key,
                    "relation_definition": relations.entries[key]["definition"], "id": identifier,
                    "chunk_id": chunk["id"], "paragraph_id": chunk["paragraph_id"], "origin": "document",
                    "evidence_context": context["text"],
                    "extraction_unit_id": unit["id"], "reason": "Quoted extraction proposed for semantic review"})
            data["units"].append(dict(unit, status="incomplete" if len(data["issues"]) > issue_count else "complete"))
        data["confidence"] = data["confidence"] / weight if weight else 0.
        data["unit_kind"] = kinds[0] if kinds and len(set(kinds)) == 1 else "other"
        data["reason"] = " ".join(reasons)
        data["concepts"] = list(dict.fromkeys(data["concepts"]))
        data["status"] = "incomplete" if data["issues"] else "complete"
        trace.emit("extraction.normalized", entity_id=chunk["id"], after=data)
        results.append(data)
        # Preserve completed records even if a later chunk/service fails.
        trace.save("artifacts/extraction_proposals.json", results)
        trace.save("artifacts/extraction_issues.json", [
            dict(chunk_id=e["chunk_id"], **i) for e in results for i in e["issues"]])
        for identifier, error in outcomes.items():
            finish_item(trace, "extraction_record", identifier, error)
    return results
