"""Collect canonical concepts and suppress semantically redundant expansion seeds."""
from collections import Counter, defaultdict
import math
from typing import Annotated, Literal
import re
from pydantic import Field
from .batching import ask_keyed
from .records import Record, batches, normalize_name
from .models import ModelResponseError
from .health import finish_item

Topic = Annotated[str, Field(min_length=1, max_length=120)]


class SegmentSummary(Record):
    summary: str = Field(min_length=1, max_length=500)
    topics: list[Topic] = Field(min_length=1, max_length=4)


class ChapterSummary(Record):
    overview: str = Field(min_length=1, max_length=1800)
    topics: list[Topic] = Field(min_length=1, max_length=16)


class SeedScores(Record):
    importance: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    expansion_value: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=600)


class EligibleSeedAssessment(SeedScores):
    decision: Literal["eligible"]
    chapter_topic: Topic
    background_question: str = Field(min_length=1, max_length=600,
        description="A specific unanswered question identifying the missing background knowledge.")


class ExcludedSeedAssessment(SeedScores):
    decision: Literal["excluded"]
    exclusion: Literal["vague", "quantified", "fragment", "duplicate", "off_topic", "already_explained"]


SeedAssessment = Annotated[
    EligibleSeedAssessment | ExcludedSeedAssessment, Field(discriminator="decision")]


def build_outline(chunks, models, trace):
    paragraphs = defaultdict(list)
    for chunk in chunks:
        paragraphs[chunk["paragraph_id"]].append(chunk)
    segments = []
    for group in paragraphs.values():
        for page in batches(group, 3):
            identifier = f"segment_{len(segments)+1:03d}"
            try:
                result = models.ask("segment_summarizer",
                    "Identify the main ideas of this chapter segment using only the supplied text. "
                    "Preserve scientific qualifications. Give a concise summary and specific topics.",
                    {"chunks": [{"id": c["id"], "text": c["text"]} for c in page]}, SegmentSummary, identifier)
                row = dict(id=identifier, chunk_ids=[c["id"] for c in page], **result.model_dump())
            except ModelResponseError as exc:
                row = dict(id=identifier, chunk_ids=[c["id"] for c in page], summary="",
                           topics=[], status="unresolved", reason=str(exc))
            segments.append(row)
            trace.emit("outline.segment", entity_id=identifier, segment=row)
            trace.save("artifacts/outline_progress.json", segments)
            finish_item(trace, "outline_segment", identifier, row.get("reason") if row.get("status") == "unresolved" else None)
    if not segments:
        raise ValueError("Cannot outline an empty chapter")
    level = [{"overview": s["summary"], "topics": s["topics"]} for s in segments if s.get("status") != "unresolved"]
    if not level:
        outline = dict(overview="", topics=[], segments=segments, status="unresolved")
        trace.save("artifacts/chapter_outline.json", outline)
        return outline
    while True:
        reduced = []
        for index, page in enumerate(batches(level, 8)):
            identifier = f"outline_{len(level)}_{index}"
            try:
                result = models.ask("chapter_summarizer",
                    "Combine all these segment summaries into a concise chapter overview and topic map. "
                    "Cover distinct subjects across every supplied segment; do not add outside knowledge.",
                    {"segments": page}, ChapterSummary, identifier)
                reduced.append(result.model_dump())
            except ModelResponseError as exc:
                # Retain validated lower-level summaries; never invent replacement topics.
                reduced.append(dict(overview="\n".join(s["overview"] for s in page),
                    topics=list(dict.fromkeys(t for s in page for t in s["topics"]))))
                finish_item(trace, "outline_chapter", identifier, exc)
            else:
                finish_item(trace, "outline_chapter", identifier)
        if len(reduced) == 1:
            outline = dict(reduced[0], segments=segments)
            trace.save("artifacts/chapter_outline.json", outline)
            return outline
        level = reduced


def collect_seeds(extractions, chunks, concepts, trace, limit=0, similarity_threshold=.85):
    """After identity reconciliation, pick concepts dissimilar to previously selected seeds."""
    if not 0 <= similarity_threshold <= 1:
        raise ValueError("Seed similarity threshold must be between 0 and 1")
    occurrences = defaultdict(list)
    for extraction in extractions:
        for name in extraction["concepts"]:
            if extraction["chunk_id"] not in occurrences[name]:
                occurrences[name].append(extraction["chunk_id"])
    by_chunk = {c["id"]: c for c in chunks}
    seeds, excluded, vectors = [], [], []
    omitted_by_limit = 0
    for name, chunk_ids in occurrences.items():
        entry = concepts.entries[name]
        if entry.get("form", "concept") == "phrase":
            excluded.append(dict(concept=name, reason="Not a standalone concept"))
            continue
        if limit and len(seeds) >= limit:
            omitted_by_limit += 1
            continue
        vector = concepts.models.embed(f"{name}: {entry['definition']}", f"seed_candidate_{name}")
        magnitude = math.sqrt(sum(value * value for value in vector))
        if not vector or not math.isfinite(magnitude) or magnitude == 0:
            raise ValueError(f"Invalid seed embedding for {name}")
        vector = [value / magnitude for value in vector]
        if vectors and len(vector) != len(vectors[0]):
            raise ValueError("Seed embedding dimensions changed during selection")
        similarities = [sum(a * b for a, b in zip(vector, picked)) for picked in vectors]
        if similarities:
            closest = max(range(len(similarities)), key=similarities.__getitem__)
            similarity = max(-1., min(1., similarities[closest]))
            if similarity >= similarity_threshold:
                decision = dict(concept=name, similar_to=seeds[closest]["concept"],
                                similarity=similarity, chunk_ids=chunk_ids,
                                reason="Embedding is too similar to an already selected seed")
                excluded.append(decision)
                trace.emit("seed.filtered", entity_id=name, decision=decision)
                continue
        chunk = by_chunk[chunk_ids[0]]
        vectors.append(vector)
        seeds.append(dict(id=f"seed_{len(seeds)+1:03d}", concept=name,
                          definition=entry["definition"], kind=entry["kind"],
                          chunk_id=chunk["id"], paragraph_id=chunk["paragraph_id"], chunk_ids=chunk_ids,
                          reason="Canonical concept distinct from previously selected seed embeddings",
                          background_question=None))
    trace.save("artifacts/seeds.json", dict(policy="deduplicated_diverse_concepts", limit=limit,
               similarity_threshold=similarity_threshold, selected=seeds, excluded=excluded,
               omitted_by_limit=omitted_by_limit))
    for seed in seeds:
        trace.emit("seed.selected", entity_id=seed["id"], seed=seed)
    return seeds


def select_seeds(extractions, chunks, concepts, outline, models, trace, threshold=.7, limit=0, max_words=4):
    """Legacy scored selection, retained for replay callers; the pipeline uses collect_seeds."""
    if not outline["topics"]:
        trace.save("artifacts/seeds.json", dict(threshold=threshold, limit=limit, max_words=max_words,
            assessments=[], selected=[], status="unresolved", reason="No validated chapter topics available"))
        finish_item(trace, "seed_selection", "chapter_scope", "No validated chapter topics; background expansion skipped")
        return []
    occurrences = defaultdict(list)
    for row in extractions:
        for name in row["concepts"]:
            if row["chunk_id"] not in occurrences[name]:
                occurrences[name].append(row["chunk_id"])
    by_chunk = {c["id"]: c for c in chunks}
    by_segment = {c: s for s in outline["segments"] for c in s["chunk_ids"]}
    assessed = []
    unresolved = defaultdict(list)
    decisions_by_name = defaultdict(list)
    work = []
    for name in sorted(occurrences):
        normalized = normalize_name(name)
        words = re.findall(r"\b\w+\b", re.sub(r" \([0-9a-f]{8}\)$", "", normalized))
        exclusion = "quantified" if words and words[0] in {
            "every", "each", "some", "any", "all", "many", "several", "few", "most", "these", "those"
        } else "fragment" if len(words) > max_words else None
        if exclusion:
            row = dict(concept=name, eligible=False, eligible_concept=False, exclusion=exclusion,
                       score=0, importance=0, relevance=0, expansion_value=0,
                       reason="Quantified phrase" if exclusion == "quantified" else f"Name exceeds {max_words} words; retained as graph knowledge, not an expansion seed",
                       chunk_ids=occurrences[name], segment_assessments=[], background_question=None)
            assessed.append(row)
            trace.emit("seed.filtered", entity_id=name, decision=row)
            finish_item(trace, "seed_selection", name)
            continue
        segments = list({by_segment[c]["id"]: by_segment[c] for c in occurrences[name]}.values())
        for page in batches(segments, 3):
            work.append({**concepts.entries[name], "id": f"candidate_{len(work)+1:04d}", "segments": page})
    groups, group = [], []
    for item in work:
        if len(group) >= getattr(models, "batch_size", 4) or item["name"] in {c["name"] for c in group}:
            groups.append(group)
            group = []
        group.append(item)
    if group:
        groups.append(group)
    remaining = Counter(item["name"] for item in work)
    for supplied in groups:
        results = ask_keyed(models, "seed_selector",
            "Assess ONLY the candidates in items for background expansion. Return exactly one answer "
            "under each supplied item ID, with no other entries or echoed concept names. "
            "chapter_reference and each item's segments are reference context only: do not assess "
            "additional concepts mentioned in them. "
            "Score importance to a main idea, direct chapter relevance, and usefulness of additional background "
            "separately from 0 to 1. High means central, directly relevant, and useful. "
            "Frequency alone is not importance. Incidental mentions and tangential topics score low. "
            "Choose exactly one answer type using decision: eligible or excluded. "
            "For eligible, require a specific, standalone concept tied to a chapter topic, "
            "with a useful unanswered background question. Reject vague context-dependent words (activity, rule, "
            "output, mechanisms, connection, communication) when their names fail to identify a specific relevant "
            "concept; judge in chapter context, not by a word blacklist. Reject quantified phrases, sentence "
            "fragments and duplicate aliases. Do not select a definitional restatement as a second seed. "
            "An eligible answer must include chapter_topic and background_question identifying the missing "
            "knowledge as a specific unanswered question; it must not include an exclusion. "
            "An excluded answer must include an exclusion category and a concrete reason; it must not "
            "include a chapter_topic or background_question. Choose excluded with exclusion=already_explained "
            "when no useful background question remains. Scores and the reason "
            "must agree; low expansion value must receive a low score. "
            "Check that the question has a sound premise and is answerable at the chapter's scope. Do not ask "
            "for universal numerical thresholds where values require unspecified conditions or measurements. "
            "Relations can be learned dynamically and the seed can be either endpoint; prefer meaningful gaps "
            "over questions manufactured only to justify expansion. "
            "Give concise concrete reasons.",
            supplied, SeedAssessment, "seed_assessment_" + supplied[0]["id"],
            shared={"chapter_reference": {k: outline[k] for k in ("overview", "topics")}},
            on_error=lambda item, exc: unresolved[item["name"]].append(str(exc)))
        for item in supplied:
            remaining[item["name"]] -= 1
            if remaining[item["name"]] == 0:
                trace.save("artifacts/seed_progress.json", dict(
                    validated=dict(decisions_by_name), unresolved=dict(unresolved), latest_batch=results))
                finish_item(trace, "seed_selection", item["name"],
                            "; ".join(unresolved[item["name"]]) if item["name"] in unresolved else None)
            if item["id"] not in results:
                continue
            assessment = results[item["id"]]
            is_eligible = assessment["decision"] == "eligible"
            # Preserve the artifact/debate contract; eligibility is derived, never model-supplied.
            decision = dict(assessment, concept=item["name"], eligible_concept=is_eligible,
                exclusion="none" if is_eligible else assessment["exclusion"],
                chapter_topic=assessment.get("chapter_topic"),
                background_question=assessment.get("background_question"))
            decisions_by_name[item["name"]].append(dict(decision,
                segment_ids=[s["id"] for s in item["segments"]]))
    for name, decisions in decisions_by_name.items():
        if name in unresolved:
            continue
        eligible_decisions = [a for a in decisions if a["eligible_concept"]]
        best = max(eligible_decisions or decisions, key=lambda a: min(a[k] for k in ("importance", "relevance", "expansion_value")))
        score = min(best[k] for k in ("importance", "relevance", "expansion_value"))
        assessed.append(dict(best, score=score, eligible=best["eligible_concept"] and score >= threshold, segment_assessments=decisions,
                             chunk_ids=occurrences[name]))
    for name, errors in unresolved.items():
        assessed.append(dict(concept=name, status="unresolved", eligible=False, eligible_concept=False,
            score=None, reason="; ".join(errors), chunk_ids=occurrences[name],
            segment_assessments=decisions_by_name[name], background_question=None))
    eligible = sorted((a for a in assessed if a["eligible"]), key=lambda a: (-a["score"], a["concept"]))
    seeds = []
    for row in eligible[:limit] if limit else eligible:
        selected_chunks = {c for s in outline["segments"] if s["id"] in row["segment_ids"] for c in s["chunk_ids"]}
        chunk = by_chunk[next(c for c in row["chunk_ids"] if c in selected_chunks)]
        seed = dict(row, id=f"seed_{len(seeds)+1:03d}", chunk_id=chunk["id"], paragraph_id=chunk["paragraph_id"],
                    definition=concepts.entries[row["concept"]]["definition"],
                    kind=concepts.entries[row["concept"]]["kind"])
        seeds.append(seed)
        trace.emit("seed.selected", entity_id=seed["id"], seed=seed)
    trace.save("artifacts/seeds.json", dict(threshold=threshold, limit=limit, max_words=max_words, assessments=assessed, selected=seeds))
    for row in assessed:
        finish_item(trace, "seed_selection", row["concept"],
                    row["reason"] if row.get("status") == "unresolved" else None)
    trace.emit("seed.selection_completed", assessed=len(assessed), selected=len(seeds), threshold=threshold,
               omitted=len(assessed)-len(seeds), limit=limit)
    return seeds
