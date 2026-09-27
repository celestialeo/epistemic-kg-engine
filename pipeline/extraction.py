"""Document-grounded extraction with exact source quotations."""
from typing import Literal
import re
from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Relation(Record):
    source: str = Field(min_length=1)
    relation: Literal["defines", "part_of", "causes", "enables", "inhibits", "associated_with"]
    target: str = Field(min_length=1)
    evidence: str = Field(min_length=1, description="An exact verbatim quotation from the CURRENT chunk")


class Claim(Record):
    text: str = Field(min_length=1)
    evidence: str = Field(min_length=1, description="An exact verbatim quotation from the CURRENT chunk")


class Extraction(Record):
    unit_kind: Literal["core_statement", "definition", "example", "other"]
    concepts: list[str] = Field(min_length=1, max_length=12)
    claims: list[Claim] = Field(min_length=1, max_length=12)
    relations: list[Relation] = Field(max_length=12)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)


def normalize(value):
    return " ".join(value.casefold().split())


def extract(chunks, paragraphs, models, trace):
    results = []
    paragraph_map = {p["id"]: p for p in paragraphs}
    for chunk in chunks:
        print(f"  Extracting {chunk['id']}", flush=True)
        result = models.ask("extractor",
            "Extract all factual claims, short concept names, and explicit directed relations from CURRENT_CHUNK. "
            "Keep negations and qualifications. Paragraph context is only for resolving references; "
            "do not extract claims from outside CURRENT_CHUNK. Each evidence value must be an exact "
            "substring of CURRENT_CHUNK. Definitions use the defined concept as source and its category "
            "as target. Association does not imply causation. Include relation endpoints in concepts.",
            {"CURRENT_CHUNK": chunk["text"], "paragraph_context": paragraph_map[chunk["paragraph_id"]]["text"],
             "previous_chunk_id": chunk["previous_id"]}, Extraction, chunk["id"])
        data = result.model_dump()
        proposed_concepts = list(dict.fromkeys(normalize(c) for c in data["concepts"] if normalize(c)))
        concepts = []
        for collection in ("claims", "relations"):
            accepted = []
            for i, row in enumerate(data[collection]):
                valid = row["evidence"] in chunk["text"]
                trace.emit("extraction.evidence_checked", entity_id=chunk["id"], collection=collection,
                           index=i, valid=valid, record=row)
                if not valid:
                    trace.emit("extraction.record_rejected", entity_id=chunk["id"], record=row,
                               reason="Evidence is not an exact substring of the current chunk")
                    continue
                row["evidence_start"] = chunk["start"] + chunk["text"].index(row["evidence"])
                row["evidence_end"] = row["evidence_start"] + len(row["evidence"])
                if collection == "relations":
                    row["source"], row["target"] = normalize(row["source"]), normalize(row["target"])
                    if not row["source"] or not row["target"] or row["source"] == row["target"]:
                        trace.emit("extraction.record_rejected", entity_id=chunk["id"], record=row,
                                   reason="Empty endpoint or self relation")
                        continue
                    concepts.extend([row["source"], row["target"]])
                accepted.append(row)
            data[collection] = accepted
        if not data["claims"]:
            raise ValueError(f"No grounded claims extracted for {chunk['id']}")
        grounding = normalize(chunk["text"] + " " + " ".join(c["text"] for c in data["claims"]))
        for concept in proposed_concepts:
            valid = bool(re.search(r"(?<!\w)" + re.escape(concept) + r"(?!\w)", grounding))
            trace.emit("extraction.concept_checked", entity_id=chunk["id"], concept=concept,
                       valid=valid, rule="Appears in current chunk or a retained claim; accepted relation endpoints are also retained")
            if valid:
                concepts.append(concept)
        data["concepts"] = list(dict.fromkeys(concepts))
        data["chunk_id"] = chunk["id"]
        trace.emit("extraction.normalized", entity_id=chunk["id"], before=result.model_dump(), after=data)
        results.append(data)
    return results
