from .settings import budgeted_pages
from .settings import setting
"""Select chapter-relevant concepts and identify useful unstated knowledge."""
from collections import defaultdict
import hashlib
import json
import unicodedata
from typing import Annotated, Literal
from pydantic import Field, create_model, field_validator, model_validator
from .batching import ask_keyed
from .records import Record, batches
from .models import ModelResponseError, OutputLimitError
from .health import finish_item

Topic = Annotated[str, Field(min_length=1, max_length=setting('text', 'detail_chars'))]


class SegmentSummary(Record):
    summary: str = Field(min_length=1, max_length=setting('text', 'short_explanation_chars'))
    topics: list[Topic] = Field(min_length=1)


class ChapterSummary(Record):
    overview: str = Field(min_length=1, max_length=setting('text', 'summary_chars'))
    topics: list[Topic] = Field(min_length=1)


class SeedScores(Record):
    importance: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    expansion_value: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=setting('text', 'question_chars'))


class EligibleSeedAssessment(SeedScores):
    decision: Literal["eligible"]
    chapter_topic: Topic
    background_question: str = Field(min_length=1, max_length=setting('text', 'question_chars'),
        description="A specific unanswered question identifying the missing background knowledge.")


class ExcludedSeedAssessment(SeedScores):
    decision: Literal["excluded"]
    exclusion: Literal["vague", "quantified", "fragment", "duplicate", "off_topic", "already_explained"]


SeedAssessment = Annotated[
    EligibleSeedAssessment | ExcludedSeedAssessment, Field(discriminator="decision")]


class TopicAssessment(Record):
    expand: bool
    topic_id: str | None
    importance: float = Field(ge=0, le=1)
    relevance: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1)

    @model_validator(mode='after')
    def selection_required(self):
        if self.expand and self.topic_id is None:
            raise ValueError('expand=true requires topic_id: copy one exact id from allowed_topics, not a topic label')
        if not self.expand and self.topic_id is not None:
            raise ValueError('expand=false requires topic_id=null; select an allowed topic ID only when expand=true')
        return self


def topic_catalog(outline):
    """One document-derived authority for selectable chapter topics and subtopics.

    IDs depend on level and normalized label, not position in a model response.
    Repeated subtopics retain all their source segments. The outline supplies no
    chapter-to-subtopic mapping, so no such semantic parentage is invented.
    """
    rows = {}

    def add(label, level, segment_id=None):
        normalized = ' '.join(unicodedata.normalize('NFKC', label).split())
        if not normalized:
            raise ValueError('Outline topics must contain non-whitespace text')
        key = json.dumps([level, normalized.casefold()], ensure_ascii=True)
        identifier = level + '_' + hashlib.sha256(key.encode()).hexdigest()[:20]
        row = rows.setdefault(identifier, dict(id=identifier, label=normalized, level=level, segment_ids=[]))
        if segment_id is not None and segment_id not in row['segment_ids']:
            row['segment_ids'].append(segment_id)

    for label in outline.get('topics', []):
        add(label, 'chapter')
    for segment in outline.get('segments', []):
        if segment.get('status') == 'unresolved':
            continue
        for label in segment.get('topics', []):
            add(label, 'subtopic', segment['id'])
    for row in rows.values():
        row['segment_ids'].sort()
    return sorted(rows.values(), key=lambda row: row['id'])


def topic_assessment_schema(allowed_topics):
    """Constrain generation and retries to precisely the supplied topic IDs."""
    identifiers = tuple(row['id'] for row in allowed_topics)
    if not identifiers:
        raise ValueError('Cannot select seeds without validated outline topics')
    allowed = set(identifiers)
    choices = ', '.join(identifiers)

    @field_validator('topic_id', mode='before')
    @classmethod
    def known_id(cls, value):
        if value is not None and (not isinstance(value, str) or value not in allowed):
            raise ValueError(f'Invalid topic_id {value!r}. Copy an exact id from allowed_topics, '
                             f'not a label, candidate ID, segment ID, or an invented ID. '
                             f'Allowed IDs: {choices}. See allowed_topics for their labels and levels. '
                             'Use topic_id=null only with expand=false.')
        return value

    return create_model('DocumentTopicAssessment', __base__=TopicAssessment,
                        __validators__={'known_id': known_id},
                        topic_id=(Literal[identifiers] | None, Field(...,
                            description='An exact id from allowed_topics when expand=true; null when expand=false. '
                                        'Both chapter and subtopic entries in that list are selectable.')))


class KnowledgeGap(Record):
    question: str = Field(min_length=1,
        description="A general explanatory question answerable from subject knowledge, not an unspecified fact about this particular case")
    assumed_knowledge: str = Field(min_length=1)
    why_useful: str = Field(min_length=1)
    source_chunk_ids: list[str] = Field(min_length=1)


class CaseSpecificUnknown(Record):
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1,
        description="Why the particular case cannot be determined from the supplied chapter")
    source_chunk_ids: list[str] = Field(min_length=1)
    status: Literal["unknown"] = "unknown"


class GapAssessment(Record):
    document_coverage: str = Field(min_length=1)
    gaps: list[KnowledgeGap]
    case_specific_unknowns: list[CaseSpecificUnknown]
    reason: str = Field(min_length=1)


class GapCoverage(Record):
    answered: bool
    evidence_ids: list[str]
    reason: str = Field(min_length=1)


def build_outline(chunks, models, trace):
    paragraphs = defaultdict(list)
    for chunk in chunks:
        paragraphs[chunk["paragraph_id"]].append(chunk)
    segments = []
    for group in paragraphs.values():
        for page in budgeted_pages(group, models, schema=SegmentSummary):
            identifier = f"segment_{len(segments)+1:03d}"
            try:
                result = models.ask("segment_summarizer",
                    "Identify the main ideas of this chapter segment using only the supplied text. "
                    "Preserve source qualifications. Give a concise summary and specific topics.",
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
        for index, page in enumerate(budgeted_pages(level, models, schema=ChapterSummary)):
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
        if len(reduced) >= len(level):
            raise OutputLimitError('Outline cannot reduce within configured model budgets; increase context/output budget')
        level = reduced


def collect_seeds(extractions, chunks, concepts, trace, limit=0, similarity_threshold=None, *, outline=None):
    """Assess importance and missing knowledge; similarity never authorizes exclusion.

    similarity_threshold is accepted for callers of the previous selector but is
    deliberately unused. Scores order eligible seeds only when a budget is set.
    """
    if limit < 0:
        raise ValueError("seed limit must be nonnegative")
    models = concepts.models
    outline = outline if outline is not None else build_outline(chunks, models, trace)
    allowed_topics = topic_catalog(outline)
    by_topic = {row['id']: row for row in allowed_topics}
    # Context references the same catalog instead of presenting a second set of
    # unselectable topic strings. Unresolved segment summaries are not evidence.
    chapter = dict(overview=outline.get('overview', ''),
                   topic_ids=[row['id'] for row in allowed_topics if row['level'] == 'chapter'],
                   segments=[dict(id=segment['id'], chunk_ids=segment.get('chunk_ids', []),
                                  summary=segment.get('summary', ''),
                                  subtopic_ids=[row['id'] for row in allowed_topics
                                                if segment['id'] in row['segment_ids']])
                             for segment in outline.get('segments', [])
                             if segment.get('status') != 'unresolved'])
    occurrences = defaultdict(list)
    for extraction in extractions:
        for name in extraction["concepts"]:
            if extraction["chunk_id"] not in occurrences[name]:
                occurrences[name].append(extraction["chunk_id"])
    by_chunk = {chunk["id"]: chunk for chunk in chunks}
    assessments, seeds, excluded = [], [], []
    state = dict(policy="chapter_importance_and_knowledge_gaps", limit=limit,
                 assessments=assessments, selected=seeds, excluded=excluded,
                 omitted_by_limit=0, allowed_topics=allowed_topics)
    trace.save("artifacts/seeds.json", state)
    if not allowed_topics:
        state.update(status="unresolved", reason="No validated chapter topics")
        trace.save("artifacts/seeds.json", state)
        finish_item(trace, "seed_selection", "chapter_scope", state["reason"])
        return []

    items = []
    for name, chunk_ids in occurrences.items():
        entry = concepts.entries[name]
        known = [{key: fact.get(key) for key in
                  ("id", "source", "relation", "target", "relation_definition", "conditions", "modality")}
                 for extraction in extractions for fact in extraction.get("relations", [])
                 if fact.get("accepted") and name in (fact["source"], fact["target"])]
        items.append(dict(id=f"seed_candidate_{len(items)+1:04d}", **entry,
                          source_chunks=[dict(id=cid, text=by_chunk[cid]["text"]) for cid in chunk_ids],
                          known_facts=known))

    errors = {}
    def failed(item, exc):
        errors[item["id"]] = str(exc)

    topics = ask_keyed(models, "seed_selector",
        "Choose concepts worth expanding for understanding this chapter. Assess each supplied concept "
        "in its source context and against the whole chapter's main ideas. Select meaningful concepts "
        "whose explanation could materially help a reader; exclude peripheral mentions and generic "
        "concepts that carry no substantive explanatory role here. Judge meaning, not name length, "
        "word choice, or frequency. Closely related concepts can require different explanations: "
        "overlapping definitions never make distinct concepts interchangeable. Do not assume that a "
        "concept is fully understood merely because the chapter states its function. Set expand=false "
        "when further background would add no useful understanding. Scores are fractions from 0 to 1, "
        "not percentages. Scores describe relative importance "
        "and relevance for budget ordering, not pass/fail cutoffs. allowed_topics is the complete "
        "selection list for this document. Both chapter topics and subtopics in that list are valid "
        "choices; level distinguishes them and segment_ids records where subtopics occur. "
        "For expand=true, copy one exact id from allowed_topics into topic_id. Choose the entry "
        "whose meaning best fits the concept; never return its label, a segment ID or a concept ID. "
        "For expand=false, return topic_id=null. Give a concise reason.",
        items, topic_assessment_schema(allowed_topics), "seed_topics",
        shared={"chapter": dict(overview=chapter['overview'], topic_ids=chapter['topic_ids'], segments=[dict(subtopic_ids=s['subtopic_ids']) for s in chapter['segments']]), "allowed_topics": [dict(id=t['id'], label=t['label'], level=t['level']) for t in allowed_topics]}, on_error=failed)
    # Keep the human-readable label for existing reports/debate consumers, but
    # resolve it ourselves from the validated ID rather than asking for a copy.
    for topic in topics.values():
        selected = by_topic.get(topic['topic_id'])
        topic.update(chapter_topic=selected['label'] if selected else None,
                     topic_level=selected['level'] if selected else None)
    trace.save("artifacts/seed_progress.json", dict(allowed_topics=allowed_topics, topics=topics, unresolved=errors))

    relevant = [dict(item, chapter_topic=topics[item["id"]]["chapter_topic"],
                     topic_id=topics[item['id']]['topic_id'], topic_level=topics[item['id']]['topic_level'],
                     selection_reason=topics[item["id"]]["reason"])
                for item in items if item["id"] in topics and topics[item["id"]]["expand"]]
    def validate_gaps(item, result):
        allowed = {chunk["id"] for chunk in item["source_chunks"]}
        for gap in [*result.gaps, *result.case_specific_unknowns]:
            if not set(gap.source_chunk_ids) <= allowed:
                raise ValueError("Gap anchors must identify supplied source chunks")

    plans = ask_keyed(models, "background_gap_planner",
        "Identify what useful knowledge the chapter assumes but does not explain for each concept. "
        "Only the supplied source_chunks establish what the document actually claims. Do not attribute "
        "information from summaries, concept definitions or your general knowledge to the document. "
        "First summarize what the source already supplies in document_coverage. Then identify distinct "
        "unanswered questions using your own general understanding of the subject. For each gap state "
        "the assumed_knowledge, why explaining it would help understand the actual source statement, "
        "and the source_chunk_ids motivating it. A statement of a concept's function is not necessarily "
        "an explanation of its basis. Look beyond the supplied concept list; missing knowledge can "
        "introduce concepts never named in the chapter. Do not use external texts or invent citations. "
        "Do not propose questions answerable by paraphrasing, reversing, or combining the supplied "
        "statements alone. Separate general explanatory gaps from unknown details of the particular case. "
        "Do not ask the proposer to identify an unspecified choice, measurement or implementation in this "
        "case. Record such questions in case_specific_unknowns with status=unknown. When useful, replace "
        "the case-specific question in gaps with a general question about possible approaches, their "
        "mechanisms or relevant considerations. A general explanation must not imply that one of those "
        "possibilities actually applies to this case. Keep the original case-specific uncertainty explicit. "
        "Respect the chapter's scope and implied level; avoid tangents and unnecessary "
        "detail. Return an empty gaps list when nothing meaningful is missing. Give concise conclusions, "
        "not a private reasoning transcript. Treat summaries as navigation aids; source text is authoritative.",
        relevant, GapAssessment, "seed_gaps", shared={"chapter": dict(overview=chapter['overview'], topic_ids=chapter['topic_ids'], segments=[dict(subtopic_ids=s['subtopic_ids']) for s in chapter['segments']]), "allowed_topics": [dict(id=t['id'], label=t['label'], level=t['level']) for t in allowed_topics]},
        validate=validate_gaps, on_error=failed)
    trace.save("artifacts/seed_progress.json", dict(allowed_topics=allowed_topics, topics=topics, plans=plans, unresolved=errors))

    # Check planned gaps against every source chunk, including material outside
    # the seed's occurrences. Retain relevant passages across pages so an answer
    # spread over multiple parts of the chapter can close the gap.
    gap_items, gaps_by_seed, unknowns_by_seed = [], defaultdict(list), defaultdict(list)
    for item in relevant:
        plan = plans.get(item["id"])
        if plan is None:
            continue
        for index, gap in enumerate(plan["gaps"]):
            row = dict(gap, id=f"{item['id']}_gap_{index+1:03d}",
                       seed_candidate_id=item["id"], concept=item["name"],
                       document_coverage=plan["document_coverage"])
            gaps_by_seed[item["id"]].append(row)
            gap_items.append(row)
        for index, unknown in enumerate(plan["case_specific_unknowns"]):
            row = dict(unknown, id=f"{item['id']}_unknown_{index+1:03d}",
                       seed_candidate_id=item["id"], concept=item["name"],
                       document_coverage=plan["document_coverage"])
            unknowns_by_seed[item["id"]].append(row)
            gap_items.append(row)
    covered, supporting = {}, defaultdict(dict)
    gap_errors = {}
    references = [dict(id=chunk["id"], text=chunk["text"]) for chunk in chunks]
    for index, page in enumerate(budgeted_pages(references, models)):
        pending = [dict(item, earlier_passages=list(supporting[item["id"]].values()))
                   for item in gap_items if item["id"] not in covered and item["id"] not in gap_errors]
        if not pending:
            break
        page_ids = {ref["id"] for ref in page}
        def validate_coverage(item, result):
            allowed = page_ids | set(supporting[item["id"]])
            if not set(result.evidence_ids) <= allowed:
                raise ValueError("Gap coverage must cite supplied chapter passages")
            if result.answered and not result.evidence_ids:
                raise ValueError("An already answered gap requires chapter evidence")

        decisions = ask_keyed(models, "background_gap_coverage",
            "For each question decide only whether these chapter passages, together with earlier_passages, "
            "already answer it adequately. Use only their stated information and implications requiring "
            "no additional subject knowledge. An initial unknown label is tentative: a different chapter "
            "passage may specify the case detail. Resolve it only with explicit supplied information, "
            "never by choosing a generally possible option. A concept mention or statement of function is not an answer "
            "to a missing explanatory question. Do not answer from your own knowledge in this coverage check. "
            "Set answered=true only with sufficient source content. Cite passages contributing to the "
            "answer even if answered=false, so partial information can be combined with later passages.",
            pending, GapCoverage, f"gap_coverage_{index}", shared={"references": page},
            validate=validate_coverage,
            on_error=lambda item, exc: gap_errors.update({item["id"]: str(exc)}))
        for item in pending:
            decision = decisions.get(item["id"])
            if decision is None:
                continue
            available = {ref["id"]: ref for ref in page} | supporting[item["id"]]
            for ref_id in decision["evidence_ids"]:
                supporting[item["id"]][ref_id] = available[ref_id]
            item_id = item["id"]
            trace.emit("seed.gap_coverage_checked", entity_id=item_id, result=decision,
                       reference_ids=list(available))
            if decision["answered"]:
                covered[item_id] = decision
        trace.save("artifacts/seed_progress.json", dict(allowed_topics=allowed_topics, topics=topics, plans=plans,
            covered_gaps=covered, unresolved=errors, unresolved_gaps=gap_errors))

    eligible = []
    for item in items:
        identifier, name = item["id"], item["name"]
        topic, plan = topics.get(identifier), plans.get(identifier)
        row = dict(concept=name, chunk_ids=occurrences[name], eligible=False,
                   topic_assessment=topic, gap_assessment=plan,
                   case_specific_unknowns=[unknown for unknown in unknowns_by_seed[identifier]
                                           if unknown["id"] not in covered],
                   specified_case_details=[dict(unknown, status="specified_in_chapter",
                                                coverage=covered[unknown["id"]])
                                           for unknown in unknowns_by_seed[identifier]
                                           if unknown["id"] in covered])
        if identifier in errors:
            row.update(status="unresolved", reason=errors[identifier])
        elif not topic["expand"]:
            row["reason"] = topic["reason"]
        else:
            planned = gaps_by_seed[identifier]
            remaining = [gap for gap in planned if gap["id"] not in covered and gap["id"] not in gap_errors]
            row.update(gaps=remaining,
                       covered_gaps=[dict(gap, coverage=covered[gap["id"]])
                                     for gap in planned if gap["id"] in covered],
                       unresolved_gaps=[dict(gap, reason=gap_errors[gap["id"]])
                                        for gap in planned if gap["id"] in gap_errors])
            for gap in planned + unknowns_by_seed[identifier]:
                finish_item(trace, "seed_gap_coverage", gap["id"], gap_errors.get(gap["id"]))
            row.update(eligible=bool(remaining),
                       reason=plan["reason"] if remaining or not planned else
                       "No validated unanswered gaps remain after chapter coverage checks")
            if remaining:
                eligible.append((item, row))
        assessments.append(row)
        if not row["eligible"]:
            excluded.append(row)
            trace.emit("seed.filtered", entity_id=name, decision=row)
        trace.save("artifacts/seeds.json", state)
        finish_item(trace, "seed_selection", name,
                    row["reason"] if row.get("status") == "unresolved" else None)

    # No score threshold. Rank only to allocate an explicitly requested budget.
    if limit:
        eligible.sort(key=lambda pair: (
            -pair[1]["topic_assessment"]["importance"], -pair[1]["topic_assessment"]["relevance"]))
    state["omitted_by_limit"] = max(0, len(eligible) - limit) if limit else 0
    for item, assessment in eligible[:limit] if limit else eligible:
        chunk = by_chunk[occurrences[item["name"]][0]]
        gaps = assessment["gaps"]
        seed = dict(id=f"seed_{len(seeds)+1:03d}", concept=item["name"],
                    definition=item["definition"], kind=item["kind"],
                    chunk_id=chunk["id"], paragraph_id=chunk["paragraph_id"],
                    chunk_ids=occurrences[item["name"]], reason=assessment["reason"],
                    chapter_topic=assessment["topic_assessment"]["chapter_topic"],
                    topic_id=assessment['topic_assessment']['topic_id'],
                    topic_level=assessment['topic_assessment']['topic_level'],
                    document_coverage=assessment["gap_assessment"]["document_coverage"],
                    case_specific_unknowns=assessment["case_specific_unknowns"],
                    gaps=gaps, background_question="\n".join(gap["question"] for gap in gaps))
        seeds.append(seed)
        trace.emit("seed.selected", entity_id=seed["id"], seed=seed)
    trace.save("artifacts/seeds.json", state)
    trace.emit("seed.selection_completed", assessed=len(assessments), selected=len(seeds),
               omitted=len(assessments)-len(seeds), limit=limit)
    return seeds


def select_seeds(extractions, chunks, concepts, outline, models, trace, threshold=None, limit=0, max_words=None):
    """Compatibility entry point; old numeric/lexical filters no longer select seeds."""
    return collect_seeds(extractions, chunks, concepts, trace, limit=limit, outline=outline)
