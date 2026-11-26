"""Plan explanatory gaps by passage, then verify coverage across the whole source.

Every passage is processed. Concept occurrence alone does not commission a
separate explanation. All proposed questions and exclusions remain auditable.
"""
from collections import defaultdict
from typing import Literal
from pydantic import Field, create_model
from .records import Record
from .seeds import KnowledgeGap, CaseSpecificUnknown, GapCoverage, topic_catalog, build_outline
from .batching import ask_keyed
from .settings import budgeted_pages
from .models import ModelResponseError
from .health import finish_item


class PassageSeed(Record):
    concept: str
    topic_id: str
    gaps: list[KnowledgeGap]
    priority: Literal['high', 'medium', 'low']
    reason: str


class PassagePlan(Record):
    document_coverage: str
    seeds: list[PassageSeed]
    case_specific_unknowns: list[CaseSpecificUnknown]
    reason: str


def collect_seeds(extractions, chunks, concepts, trace, limit=0, *, outline=None):
    if limit < 0:
        raise ValueError('seed limit must be nonnegative')
    models = concepts.models
    outline = outline if outline is not None else build_outline(chunks, models, trace)
    topics = topic_catalog(outline)
    topic_by_id = {t['id']: t for t in topics}
    by_chunk = {c['id']: c for c in chunks}
    extracted = {e['chunk_id']: e for e in extractions}
    plans, errors, merged = [], {}, {}
    state = dict(policy='passage_questions_with_whole_source_coverage', limit=limit,
                 allowed_topics=topics, assessments=[], selected=[], excluded=[], omitted_by_limit=0)
    trace.save('artifacts/seeds.json', state)
    if not topics:
        finish_item(trace, 'seed_selection', 'chapter_scope', 'No validated chapter topics')
        return []
    for chunk in chunks:
        names = extracted.get(chunk['id'], {}).get('concepts', [])
        names = list(dict.fromkeys(n for n in names if n in concepts.entries))
        if not names:
            errors[chunk['id']] = 'No extracted concepts are available to anchor background explanations'
            finish_item(trace, 'seed_planning', chunk['id'], errors[chunk['id']])
            continue
        seed_schema = create_model('AnchoredPassageSeed', __base__=PassageSeed,
            concept=(Literal[tuple(names)], ...), topic_id=(Literal[tuple(topic_by_id)], ...))
        schema = create_model('AnchoredPassagePlan', __base__=PassagePlan, seeds=(list[seed_schema], ...))
        def validate(plan):
            for gap in [g for s in plan.seeds for g in s.gaps] + plan.case_specific_unknowns:
                if set(gap.source_chunk_ids) != {chunk['id']}:
                    raise ValueError('Anchor each question to this exact supplied source chunk ID')
        try:
            plan = models.ask('passage_gap_planner',
                'Identify the useful explanatory knowledge this source passage assumes but does not explain, '
                'at the chapter\'s implied level. Read every sentence. First state what the source already '
                'supplies in document_coverage. Then organize genuinely missing explanations around supplied '
                'anchor concepts. Plan for the passage as a whole: do not commission a separate explanation '
                'for every noun or create overlapping questions for the same mechanism. Distinct meanings '
                'and mechanisms must remain distinct questions. There is no question quota. '
                'A stated function need not explain how or why it works. Ask only questions whose answers '
                'materially help understand the actual source; avoid incidental textbook tangents. '
                'Do not ask questions answerable by paraphrasing or combining the source alone. '
                'Choose exact concept names from anchors and exact topic IDs from allowed_topics. '
                'New concepts may be introduced later to answer a gap; they are not needed as anchors now. '
                'Record unspecified case-specific choices or measurements as case_specific_unknowns, '
                'not as requests to invent those details. General mechanisms or qualified possibilities '
                'can be gaps without asserting which possibility applies to this case. '
                'Source text is authoritative; the overview is only a navigation aid. Return seeds=[] '
                'when no substantive explanation is missing. Do not invent facts or citations.',
                dict(source=dict(id=chunk['id'], text=chunk['text']), anchors=names,
                     chapter_overview=outline.get('overview', ''),
                     allowed_topics=[dict(id=t['id'], label=t['label']) for t in topics]),
                schema, chunk['id'] + '_gaps', validator=validate)
        except ModelResponseError as exc:
            errors[chunk['id']] = str(exc)
            finish_item(trace, 'seed_planning', chunk['id'], exc)
            continue
        value = dict(chunk_id=chunk['id'], **plan.model_dump())
        plans.append(value)
        for proposal in value['seeds']:
            key = (proposal['concept'], proposal['topic_id'])
            current = merged.setdefault(key, dict(proposal, gaps=[], chunk_ids=[],
                document_coverage=[], case_specific_unknowns=[]))
            if chunk['id'] not in current['chunk_ids']: current['chunk_ids'].append(chunk['id'])
            current['document_coverage'].append(value['document_coverage'])
            current['gaps'].extend(proposal['gaps'])
            current['case_specific_unknowns'].extend(value['case_specific_unknowns'])
        trace.save('artifacts/seed_progress.json', dict(plans=plans, unresolved=errors))
        finish_item(trace, 'seed_planning', chunk['id'])

    questions, groups = [], []
    for group in merged.values():
        group = dict(group)
        for collection in ('gaps', 'case_specific_unknowns'):
            group[collection] = [dict(q, id=f'question_{len(questions)+i+1:04d}',
                concept=group['concept']) for i, q in enumerate(group[collection])]
            questions.extend(group[collection])
        groups.append(group)
    covered, errors_by_gap, supporting = {}, {}, defaultdict(dict)
    references = [dict(id=c['id'], text=c['text']) for c in chunks]
    for page_index, page in enumerate(budgeted_pages(references, models)):
        pending = [dict(q, earlier_passages=list(supporting[q['id']].values()))
                   for q in questions if q['id'] not in covered and q['id'] not in errors_by_gap]
        if not pending: break
        def check(item, result):
            allowed = {r['id'] for r in page} | set(supporting[item['id']])
            if not set(result.evidence_ids) <= allowed or (result.answered and not result.evidence_ids):
                raise ValueError('A covered question must cite supplied supporting source passage IDs')
        decisions = ask_keyed(models, 'background_gap_coverage',
            'Does the supplied source, together with earlier_passages, already answer the entire question? '
            'Use only stated information and implications needing no outside subject knowledge. A function '
            'or related concept mention is not a mechanism explanation. For a case-specific unknown, '
            'require explicit source information identifying that case; never choose a possible option. '
            'Cite contributing passages even for a partial answer, but answered=true requires a complete '
            'answer at the question\'s scope. Do not answer from your own background knowledge.',
            pending, GapCoverage, f'passage_gap_coverage_{page_index}', shared=dict(references=page),
            validate=check, on_error=lambda item, exc: errors_by_gap.update({item['id']: str(exc)}))
        for item in pending:
            result = decisions.get(item['id'])
            if result is None: continue
            available = {r['id']: r for r in page} | supporting[item['id']]
            for identifier in result['evidence_ids']: supporting[item['id']][identifier] = available[identifier]
            if result['answered']: covered[item['id']] = result
            trace.emit('seed.gap_coverage_checked', entity_id=item['id'], result=result,
                       reference_ids=list(available))
    eligible = []
    for group in groups:
        remaining = [g for g in group['gaps'] if g['id'] not in covered and g['id'] not in errors_by_gap]
        assessment = dict(concept=group['concept'], eligible=bool(remaining), reason=group['reason'],
            gaps=remaining, covered_gaps=[dict(g, coverage=covered[g['id']]) for g in group['gaps'] if g['id'] in covered],
            unresolved_gaps=[dict(g, reason=errors_by_gap[g['id']]) for g in group['gaps'] if g['id'] in errors_by_gap])
        state['assessments'].append(assessment)
        if remaining: eligible.append((group, remaining))
        else: state['excluded'].append(assessment)
    for question in questions:
        finish_item(trace, 'seed_gap_coverage', question['id'], errors_by_gap.get(question['id']))
    if limit: eligible.sort(key=lambda pair: {'high': 0, 'medium': 1, 'low': 2}[pair[0]['priority']])
    state['omitted_by_limit'] = max(0, len(eligible)-limit) if limit else 0
    for group, remaining in eligible[:limit] if limit else eligible:
        entry = concepts.entries[group['concept']]
        chunk = by_chunk[group['chunk_ids'][0]]
        topic = topic_by_id[group['topic_id']]
        seed = dict(id=f"seed_{len(state['selected'])+1:03d}", concept=group['concept'],
            definition=entry['definition'], kind=entry['kind'], chunk_id=chunk['id'],
            paragraph_id=chunk['paragraph_id'], chunk_ids=group['chunk_ids'], reason=group['reason'],
            chapter_topic=topic['label'], topic_id=topic['id'], topic_level=topic['level'],
            document_coverage=' '.join(dict.fromkeys(group['document_coverage'])),
            case_specific_unknowns=[q for q in group['case_specific_unknowns'] if q['id'] not in covered],
            gaps=remaining, background_question='\n'.join(g['question'] for g in remaining))
        state['selected'].append(seed)
        trace.emit('seed.selected', entity_id=seed['id'], seed=seed)
    state.update(plans=plans, unresolved=errors, unresolved_gaps=errors_by_gap)
    trace.save('artifacts/seeds.json', state)
    trace.emit('seed.selection_completed', assessed=len(groups), selected=len(state['selected']),
               omitted=len(groups)-len(state['selected']), limit=limit)
    return state['selected']
