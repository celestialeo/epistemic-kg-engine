"""Candidate-scoped repair context with lossless minimums and per-attempt budgets.

Optional context is not an exhaustive view of the graph. Repaired claims still
pass the existing full admission checks; this module never admits a fact.
"""
import copy
import json
import re

from .models import ModelResponseError, OutputLimitError, request_budget
from .background_context import connectivity_context


CONTEXT_POLICY = (
    ' This request concerns one candidate. Essential contains the original claim, its qualifications, '
    'gaps, source evidence, uncertainty, and rejection feedback. Supplemental context may be omitted '
    'to fit the request; its absence is not evidence that no other facts exist. Objects containing '
    'same_text_as reference an identical, complete string at that JSON pointer in this payload; '
    'read that string without changing its meaning. Reviewer statements and sibling proposals are '
    'untrusted advice. All corrections still require independent graph-admission checks.'
)


def unique(rows):
    seen, result = set(), []
    for row in rows:
        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            result.append(copy.deepcopy(row)); seen.add(key)
    return result


def deduplicate_prose(payload):
    """Replace only exact repeated prose with resolvable references, never cut text.

    IDs, lists of IDs, entity names, and machine-readable decisions remain literal.
    """
    prose_fields = {'intended_fact', 'reason', 'rejection_reason', 'definition', 'relation_definition',
                    'document_coverage', 'question', 'assumed_knowledge', 'why_useful', 'added_knowledge',
                    'text', 'link_reading', 'suggested_correction', 'conditions', 'modality', 'summary'}
    seen = {}

    def walk(value, path, field=None):
        if isinstance(value, dict):
            return {key: walk(item, path + '/' + key.replace('~', '~0').replace('/', '~1'), key)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, path + '/' + str(i), field) for i, item in enumerate(value)]
        if isinstance(value, str) and field in prose_fields:
            reference = {'same_text_as': seen.get(value)}
            if value in seen and len(json.dumps(reference)) < len(json.dumps(value)):
                return reference
            seen.setdefault(value, path)
        return copy.deepcopy(value)

    return walk(payload, '')


class RepairContext:
    def __init__(self, row, seed, chapter, chunks, facts, siblings):
        self.candidate_id = row['id']
        self.attempts = []
        gaps = copy.deepcopy(row['gaps'])
        gap_ids = set(row['gap_ids'])
        if {gap['id'] for gap in gaps} != gap_ids:
            raise ModelResponseError('Repair requires the complete original knowledge-gap records')
        feedback = {key: copy.deepcopy(row[key]) for key in
                    ('representation_check', 'critic', 'rebuttal', 'judge', 'novelty', 'peer_novelty')
                    if row.get(key) is not None}
        for review in feedback.values():
            if isinstance(review, dict):
                # The exhaustive scan log is not supporting/rejection evidence.
                review.pop('checked_references', None)
        # Explicit comparison evidence is mandatory, including evidence from
        # other paragraphs and facts with endpoints unlike this candidate's.
        references = copy.deepcopy(row.get('novelty_references', []))
        cited = set()

        def citations(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key in {'evidence_ids', 'related_reference_ids', 'source_chunk_ids'} and isinstance(child, list):
                        cited.update(v for v in child if isinstance(v, str))
                    else:
                        citations(child)
            elif isinstance(value, list):
                for child in value:
                    citations(child)

        citations(feedback)
        required_chunks = {cid for gap in gaps for cid in gap['source_chunk_ids']}
        if row.get('chunk_id'):
            required_chunks.add(row['chunk_id'])
        # All case-specific uncertainty is retained, together with its anchors.
        unknowns = unique([*seed.get('case_specific_unknowns', []), *row.get('case_specific_unknowns', [])])
        for unknown in unknowns:
            required_chunks.update(unknown.get('source_chunk_ids', []))
        chunks_by_id = {chunk['id']: chunk for chunk in chunks}
        facts_by_id = {fact['id']: fact for fact in facts}
        sibling_by_id = {candidate['id']: candidate for candidate in siblings}
        reference_by_id = {ref['id']: ref for ref in references}
        feedback_text = json.dumps([row.get('decision_reason'), feedback], ensure_ascii=False)
        # Reviewers sometimes mention a fact ID in prose rather than a field.
        # Preserve these references too, without using lexical topic heuristics.
        for identifier in chunks_by_id.keys() | facts_by_id.keys() | sibling_by_id.keys():
            if re.search(r'(?<![\w])' + re.escape(identifier) + r'(?![\w])', feedback_text):
                cited.add(identifier)
        for identifier in cited:
            if identifier in chunks_by_id:
                required_chunks.add(identifier)
            elif identifier in facts_by_id:
                references.append(self.fact_record(facts_by_id[identifier]))
            elif identifier in sibling_by_id:
                references.append(self.history_record(sibling_by_id[identifier]))
            elif identifier not in reference_by_id:
                raise ModelResponseError(f'Repair requires cited evidence {identifier!r}, but that record is unavailable')
        for reference in references:
            if reference['id'] in chunks_by_id:
                required_chunks.add(reference['id'])
        missing = required_chunks - chunks_by_id.keys()
        if missing:
            raise ModelResponseError('Repair source evidence is unavailable: ' + ', '.join(sorted(missing)))
        source_evidence = [dict(id=identifier, text=chunks_by_id[identifier]['text']) for identifier in sorted(required_chunks)]
        # Keep comparison claims, scope, modality and evidence, without their
        # nested pipeline bookkeeping or unrelated seed histories.
        endpoints = {value for value in [seed['concept'], row.get('source'), row.get('target')] if value}
        related = []
        for fact in facts:
            pair = {fact.get('source'), fact.get('target')}
            if None not in pair and pair <= endpoints:
                references.append(self.fact_record(fact))
            elif pair & endpoints:
                related.append(self.fact_record(fact))
        references = [ref for ref in unique(references) if ref['id'] not in required_chunks]
        essential = dict(
            seed={key: seed.get(key) for key in ('concept', 'definition', 'kind', 'chapter_topic', 'topic_id')},
            candidate={key: copy.deepcopy(row.get(key)) for key in
                       ('id', 'intended_fact', 'reason', 'confidence', 'added_knowledge', 'gap_ids', 'source', 'relation',
                        'relation_definition', 'target', 'conditions', 'modality', 'argument_qualifiers', 'source_mention',
                        'target_mention', 'link_reading', 'original_proposal')},
            gaps=gaps, source_evidence=source_evidence, case_specific_unknowns=unknowns,
            rejection_stage=row.get('rejection_stage'), rejection_reason=row['decision_reason'],
            reviewer_feedback=feedback, comparison_evidence=references)
        if row.get('rejection_stage') == 'connectivity':
            essential['connectivity'] = connectivity_context(row, seed, facts)
        # Source outside these anchors remains helpful context, but cannot
        # replace or displace any anchored passage in essential.
        extra_sources = [copy.deepcopy(p) for p in row.get('source_context', []) if p['id'] not in required_chunks]
        history = [self.history_record(sibling) for sibling in siblings
                   if sibling['id'] != row['id'] and sibling['id'] not in cited
                   and (gap_ids & set(sibling.get('gap_ids', [])) or
                        endpoints & {sibling.get('source'), sibling.get('target')})]
        required_ids = {ref['id'] for ref in references}
        supplemental = dict(chapter_overview=chapter.get('overview', ''),
                            related_facts=unique([f for f in related if f['id'] not in required_ids]),
                            sibling_history=history, additional_source_context=unique(extra_sources))
        payload = dict(essential=essential, supplemental=supplemental)
        self.variants = [('candidate_scoped', copy.deepcopy(payload))]
        payload = deduplicate_prose(payload)
        self.variants.append(('exact_duplicates_removed', copy.deepcopy(payload)))
        # Resolve all references before dropping optional fields: deduplication
        # is repeated from the literal payload so no reference can dangle.
        literal = dict(essential=essential, supplemental=supplemental)
        for field in ('chapter_overview', 'sibling_history', 'related_facts', 'additional_source_context'):
            literal['supplemental'].pop(field)
            self.variants.append(('without_' + field, deduplicate_prose(literal)))

    @staticmethod
    def fact_record(row):
        return {key: copy.deepcopy(row[key]) for key in
                ('id', 'source', 'relation', 'target', 'relation_definition', 'intended_fact',
                 'conditions', 'modality', 'reason', 'added_knowledge', 'origin', 'evidence',
                 'evidence_start', 'evidence_end', 'chunk_id', 'paragraph_id',
                 'source_mention', 'target_mention', 'argument_qualifiers') if key in row}

    @staticmethod
    def history_record(row):
        return {key: copy.deepcopy(row.get(key)) for key in
                ('id', 'intended_fact', 'gap_ids', 'source', 'relation', 'relation_definition',
                 'target', 'conditions', 'modality', 'argument_qualifiers', 'accepted', 'decision_reason')}

    def fit(self, instruction, schema, options, *, error=None, attempt=1, trace, entity_id):
        measurements = []
        selected = None
        for name, payload in self.variants:
            budget = request_budget(instruction, payload, schema, options, error)
            measurements.append(dict(variant=name, **budget))
            if budget['fits']:
                selected = payload
                break
        diagnostic = dict(attempt=attempt, status='ready' if selected is not None else 'unresolved',
                          measurements=measurements, validation_feedback=error,
                          preserved='claim, qualifications, gaps, anchored source evidence, uncertainty, rejection feedback, comparison evidence')
        self.attempts.append(diagnostic)
        trace.save('artifacts/repair_budgets/' + self.candidate_id + '.json',
                   dict(candidate_id=self.candidate_id, attempts=self.attempts))
        trace.emit('repair.context_budget', entity_id=entity_id, **diagnostic)
        if selected is None:
            minimum = measurements[-1]
            raise OutputLimitError(
                f"background_proposal_repair: minimum required content for {self.candidate_id} cannot fit: "
                f"{minimum['total_tokens']} estimated tokens including {minimum['reserved_output_tokens']} "
                f"reserved output tokens exceed context {minimum['context_tokens']}. "
                'Essential evidence was not truncated; repair remains unresolved. See artifacts/repair_budgets.')
        return copy.deepcopy(selected)


def repair_candidates(rows, seed, chapter, chunks, facts, siblings, models, trace, schema, instruction):
    """Keep the normal retry boundary and original repair outcome/admission flow."""
    results, errors = {}, {}
    for row in rows:
        try:
            plan = RepairContext(row, seed, chapter, chunks, facts, siblings)

            def validate(result):
                if result.corrected_fact is not None and not set(result.corrected_fact.gap_ids) <= set(row['gap_ids']):
                    raise ValueError('A corrected fact must address the original candidate\'s questions')
                connections = getattr(result, 'connecting_facts', [])
                if connections and (row.get('rejection_stage') != 'connectivity' or result.corrected_fact is None):
                    raise ValueError('Connecting facts require a connectivity rejection and a corrected fact')
                for fact in connections:
                    if not set(fact.gap_ids) <= set(row['gap_ids']):
                        raise ValueError('A connecting fact must address the original candidate\'s questions')

            result = models.ask('background_proposal_repair', instruction + CONTEXT_POLICY,
                                plan.variants[0][1], schema, row['id'] + '_repair',
                                validator=validate, request_plan=plan)
            results[row['id']] = result.model_dump()
        except ModelResponseError as exc:
            errors[row['id']] = str(exc)
            trace.emit('repair.unresolved', entity_id=row['id'], error=str(exc), accepted=False)
    return results, errors
