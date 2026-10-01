"""Self-contained relation endpoints, local repair and adaptive extraction."""
from typing import Literal
import re
from pydantic import Field, ValidationError
from .records import Record, normalize, normalize_name, name_occurs
from .registry import Concept, ConceptKind
from .models import ModelResponseError, OutputLimitError
from .health import finish_item
from .events import EVENT_POLICY, kind_error


class Endpoint(Record):
    """Complete metadata is required by the generation schema, not repaired later."""
    name: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=400, description="Required concise definition of this concept in context")
    kind: ConceptKind = Field(description="Choose one broad semantic kind from the enum")
    kind_detail: str | None = Field(default=None, max_length=120,
        description="Optional short domain category such as cell_type or system; not a definition or function")


class Relation(Record):
    source: Endpoint
    relation: str = Field(min_length=1, max_length=80)
    relation_definition: str = Field(min_length=1, max_length=400)
    target: Endpoint
    evidence: str = Field(min_length=1, description="Exact continuous quote from EVIDENCE_CONTEXT, overlapping CURRENT_CHUNK; include adjacent sentences when needed")


class Claim(Record):
    text: str = Field(min_length=1)
    evidence: str = Field(min_length=1, description="Exact continuous quote from EVIDENCE_CONTEXT overlapping CURRENT_CHUNK")


class Extraction(Record):
    unit_kind: Literal["core_statement", "definition", "example", "other"]
    concepts: list[Endpoint] = Field(description="Standalone concepts useful for seeds; relation endpoints need not be repeated here")
    claims: list[Claim]
    relations: list[Relation]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=800)


class EndpointRepair(Record):
    concept: Concept | None
    reason: str = Field(min_length=1, max_length=800)


INSTRUCTION = EVENT_POLICY + (
    "Extract factual claims and explicit directional relations anchored in CURRENT_CHUNK. "
    "First capture the substantive assertions in every sentence as claims, including definitions, negations "
    "and each item in coordinated lists. Retain supported claims even when no suitable graph relation exists. "
    "Preserve negation, conditions and qualifications; omit a relation if its precise meaning cannot be expressed. "
    "Evidence must be an exact continuous quote that entails that specific SOURCE relation TARGET. "
    "Quote enough text: include two adjacent sentences when one describes an action and the next names it. "
    "EVIDENCE_CONTEXT includes neighboring sentences for that purpose. Every quote must overlap CURRENT_CHUNK; "
    "do not extract unrelated facts found only in neighboring context. "
    "Never abbreviate quotes with ellipses, combine noncontiguous quotes, or merely quote co-occurring endpoints. "
    "Each relation contains complete SOURCE and TARGET objects with name, definition and semantic kind. "
    "kind MUST be one of the schema enum values. Put specific labels such as cell_type or system in kind_detail. "
    "Use other only when none of the broad kinds fits; always preserve specific detail in kind_detail. "
    "Do not use bare names or references to a separate concept list. "
    "The concepts list is for additional standalone concepts; it may be empty. "
    "Use canonical singular concept names, consistent spelling, and no leading quantifiers in names. "
    "Keep some/every/can and other qualifications in the statement's meaning and evidence, never generalize them away. "
    "If an acts_on edge is supported, give it its own exact quote; it is never a mandatory companion. "
    "There is no quota or maximum number of concepts, claims or relations; return the facts present without filling a quota. "
    "Lists of topics, narrative summaries and explanatory groupings do not imply subtype or structural parthood. "
    "A summary sentence may yield a grounded claim and zero relations. Only propose a new predicate when the "
    "quote entails its precise meaning; do not force an edge for every sentence or listed concept. "
    "Preserve the precise assertion before choosing a predicate. For example, 'soil structure affects how "
    "quickly infiltration occurs' supports affects_rate_of, not enables or causes. New predicates are allowed "
    "and undergo independent meaning/direction checks; the available vocabulary is not a closed list. "
    "Use an available relation key and copy its definition exactly when appropriate. Otherwise propose a precise "
    "new key and reusable directional definition without extra exclusions: influencing a rate does not imply "
    "absence of a causal mechanism. Never force parts into types, enabling into causation, "
    "or event locations into structural parts. Neighboring evidence may resolve names or complete support for "
    "a current-chunk assertion, never supply unrelated new claims."
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
    """One adjacent sentence on each side, with exact source offsets."""
    before = paragraph["text"][:chunk["start"] - paragraph["start"]]
    after = paragraph["text"][chunk["end"] - paragraph["start"]:]
    before = before.rstrip()
    boundaries = list(re.finditer(r"(?<=[.!?])\s+(?=\S)", before))
    left = boundaries[-1].end() if boundaries else 0
    ending = re.search(r"[.!?](?=\s|$)", after)
    right = ending.end() if ending else len(after)
    start = paragraph["start"] + left
    end = chunk["end"] + right
    return dict(start=start, end=end, text=paragraph["text"][left:end-paragraph["start"]])


def extraction_units(chunk, models, trace, relations, context=None):
    # Splitting only changes model work units. Original chunk IDs, offsets,
    # outline segments, graph structure and evaluation alignment remain stable.
    stack = [(chunk["id"], 0, chunk["text"])]
    while stack:
        identifier, offset, text = stack.pop()
        unit = dict(id=identifier, start=chunk["start"] + offset,
                    end=chunk["start"] + offset + len(text), text=text)
        payload = {"CURRENT_CHUNK": text, "EVIDENCE_CONTEXT": (context or chunk)["text"],
                   "available_relations": relations.vocabulary()}
        if identifier != chunk["id"]:
            payload["reference_context"] = chunk["text"]
        try:
            result = models.ask("extractor", INSTRUCTION, payload, Extraction, identifier, validator=validate_events)
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
    original = endpoint.model_dump()
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


def extract(chunks, paragraphs, models, trace, concepts, relations):
    results = []
    by_paragraph = {p["id"]: p for p in paragraphs}
    for chunk in chunks:
        context = evidence_context(chunk, by_paragraph[chunk["paragraph_id"]])
        print(f"  Extracting {chunk['id']}", flush=True)
        data = dict(chunk_id=chunk["id"], unit_kind="other", confidence=0., reason="",
                    concepts=[], claims=[], relations=[], relation_proposals=[], units=[], issues=[])
        kinds, reasons, weight = [], [], 0
        serial = 0

        def issue(identifier, reason, record):
            row = dict(id=identifier, reason=reason, record=record)
            data["issues"].append(row)
            trace.emit("extraction.unresolved", entity_id=identifier, chunk_id=chunk["id"], **row)

        def quoted(row, unit, collection, index):
            occurrences = list(re.finditer(re.escape(row["evidence"]), context["text"]))
            match = next((m for m in occurrences if context["start"] + m.start() < unit["end"]
                          and context["start"] + m.end() > unit["start"]), None)
            valid = match is not None
            trace.emit("extraction.evidence_checked", entity_id=unit["id"], collection=collection,
                       index=index, valid=valid, record=row)
            if not valid:
                reason = "Quote is not exact source evidence overlapping the extraction unit"
                trace.emit("extraction.record_rejected", entity_id=unit["id"], record=row, reason=reason)
                issue(f"{unit['id']}_{collection}_{index}", reason, row)
                return False
            row["evidence_start"] = context["start"] + match.start()
            row["evidence_end"] = context["start"] + match.end()
            return True

        for unit, result, error in extraction_units(chunk, models, trace, relations, context):
            issue_count = len(data["issues"])
            if error:
                issue(unit["id"], error, unit)
                data["units"].append(dict(unit, status="incomplete"))
                continue
            value = result.model_dump()
            kinds.append(result.unit_kind)
            reasons.append(result.reason)
            size = len(unit["text"].split())
            data["confidence"] += result.confidence * size
            weight += size
            before_claims = len(data["claims"])
            for index, row in enumerate(value["claims"]):
                if quoted(row, unit, "claims", index):
                    data["claims"].append(row)
            if len(data["claims"]) == before_claims:
                issue(unit["id"] + "_claims", "No grounded claims extracted for this unit", unit)
            for mention_index, mention in enumerate(result.concepts, 1):
                if not name_occurs(mention.name, unit["text"]):
                    continue
                identifier = unit["id"] + "_concept_" + str(mention_index)
                complete = complete_endpoint(mention, mention.model_dump(), "concept", unit["text"], models, trace, identifier)
                if complete is None:
                    issue(identifier, "Standalone concept metadata could not be resolved", mention.model_dump())
                    continue
                try:
                    data["concepts"].append(concepts.resolve(complete, chunk["text"], identifier))
                except ModelResponseError as exc:
                    issue(identifier, f"Concept identity review unresolved: {exc}", mention.model_dump())
            for index, row in enumerate(value["relations"]):
                serial += 1
                identifier = f"{chunk['id']}_relation_{serial:03d}"
                if not quoted(row, unit, "relations", index):
                    continue
                endpoints = []
                for side in ("source", "target"):
                    endpoint = getattr(result.relations[index], side)
                    endpoints.append(complete_endpoint(endpoint, row, side, chunk["text"], models, trace, identifier + "_" + side))
                if any(endpoint is None for endpoint in endpoints):
                    issue(identifier, "Relation endpoint metadata could not be resolved", row)
                    continue
                # Resolve each complete endpoint occurrence independently. A
                # name-only map would conflate distinct senses of the same word.
                try:
                    source, target = [concepts.resolve(e, row["evidence"], identifier) for e in endpoints]
                    data["concepts"].extend((source, target))
                    key = relations.resolve(row["relation"], row["relation_definition"], source, target,
                                            row["evidence"], identifier)
                except ModelResponseError as exc:
                    issue(identifier, f"Relation normalization unresolved: {exc}", row)
                    continue
                if key is None or source == target:
                    trace.emit("extraction.record_rejected", entity_id=identifier, record=row,
                               reason="Unverified relation meaning or self relation")
                    continue
                data["relation_proposals"].append({**row, "source_mention": endpoints[0].model_dump(),
                    "target_mention": endpoints[1].model_dump(), "surface_source": endpoints[0].name,
                    "surface_target": endpoints[1].name, "surface_relation": row["relation"],
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
        finish_item(trace, "extraction_chunk", chunk["id"],
                    "Chunk contains unresolved extraction records" if data["status"] == "incomplete" else None)
    return results
