"""Bounded source-coverage repair using model-generated, independently reviewed edges.

Source evidence is the authority. Audit judgments are model estimates, not proof.
No topic vocabulary or expected graph is supplied by the developer.
"""
import re
from typing import Literal
from pydantic import Field, create_model
from .records import Record, name_occurs
from .models import ModelResponseError
from .batching import ask_keyed


class MissingClaim(Record):
    evidence: str = Field(min_length=1, description='Exact continuous source quote containing the missing assertion')
    missing_claim: str = Field(min_length=1, description='The source meaning absent from the graph, including qualifications')
    reason: str = Field(min_length=1)
    evidence_start: int | None = None


class UnsupportedAssertion(MissingClaim):
    id: str = Field(min_length=1, description='Exact supplied graph assertion ID whose literal meaning is unsupported')


class Coverage(Record):
    missing: list[MissingClaim]
    unsupported: list[UnsupportedAssertion] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    errors: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        schema = handler.resolve_ref_schema(handler(core_schema))
        schema['required'] = list(dict.fromkeys([*schema.get('required', []), 'unsupported']))
        return schema


def audit_source(chunk, extraction, concepts, models, trace, attempt):
    boundaries = [0, *(m.end() for m in re.finditer(r'(?<=[.!?])\s+(?=\S)', chunk['text'])), len(chunk['text'])]
    sentences = [dict(id=f"{chunk['id']}_s{i+1:03d}", text=chunk['text'][start:end], start=start, end=end)
                 for i, (start, end) in enumerate(zip(boundaries, boundaries[1:])) if start < end]
    spans = {s['id']: s for s in sentences}
    assertions = []
    evidence_sentences = {}
    for row in extraction['relations']:
        if not row.get('accepted'): continue
        start = row.get('evidence_start')
        if start is None and row.get('evidence') and row['evidence'] in chunk['text']:
            start = chunk.get('start', 0) + chunk['text'].index(row['evidence'])
        end = row.get('evidence_end')
        if start is not None and end is None:
            end = start + len(row.get('evidence', ''))
        evidence_sentences[row['id']] = [s['id'] for s in sentences
            if start is not None and end is not None
            and start < chunk.get('start', 0) + s['end']
            and end > chunk.get('start', 0) + s['start']]
        reading = ((row.get('modality') or 'ASSERTED') +
                   f" ({row['source']} --[{row['relation'].replace('_', ' ')}]--> {row['target']})")
        if row.get('argument_qualifiers'): reading += '; additional arguments: ' + '; '.join(row['argument_qualifiers'])
        assertions.append(dict(id=row['id'], source=row['source'], target=row['target'],
            predicate=row['relation'], definition=row['relation_definition'], reading=reading,
            conditions=row.get('conditions'), modality=row.get('modality'),
            source_sentence_ids=evidence_sentences[row['id']],
            argument_qualifiers=row.get('argument_qualifiers', [])))
    class Issue(Record):
        reason: str = Field(min_length=1, max_length=400, description='One concise explanation of the specific missing or wrong meaning')
        missing_claim: str = Field(min_length=1, max_length=600, description='The source meaning needed for a faithful graph assertion')
        source_sentence_ids: list[Literal[tuple(spans)]] = Field(min_length=1)
    bad_schema = create_model('UnsupportedSourceAssertion', __base__=Issue, id=(str, ...))
    class ClaimCoverage(Record):
        source_assertion: str = Field(min_length=1, max_length=600, description='One complete substantive source assertion, preserving all arguments and qualifiers')
        graph_edge_ids: list[str] = Field(description='Only supplied graph edges that actually express this assertion, not merely related concepts')
        graph_reading: str = Field(max_length=600, description='What those edges actually say with saved qualifiers, without supplying absent information from the source')
        preserves_meaning: bool
    class SentenceAudit(Record):
        claims: list[ClaimCoverage] = Field(min_length=1, description='Account separately for every substantive source assertion in the focus sentence')
        reason: str = Field(min_length=1, max_length=400, description='Concise final coverage conclusion before listing genuine issues')
        missing: list[Issue]
        unsupported: list[bad_schema]
    def validate(item, result):
        edge_ids = {r['id'] for r in assertions}
        for claim in result.claims:
            if not set(claim.graph_edge_ids) <= edge_ids:
                raise ValueError('Claim coverage must cite actual supplied graph edge IDs')
            if claim.preserves_meaning and not claim.graph_edge_ids:
                raise ValueError('Preserved source assertions require graph edges expressing their meaning')
        represented = {identifier for claim in result.claims if claim.preserves_meaning for identifier in claim.graph_edge_ids}
        for bad in result.unsupported:
            if bad.id in represented:
                raise ValueError('An edge cannot be faithfully representing a claim and also unsupported. Missing source meaning alone does not invalidate another existing edge.')
            if bad.id not in {r['id'] for r in assertions}:
                raise ValueError('Unsupported assertion must identify a supplied accepted edge')
            known = evidence_sentences[bad.id]
            if known and not set(known).intersection(bad.source_sentence_ids):
                raise ValueError('An unsupported-edge objection must address that edge\'s own source sentence IDs. Missing information in an unrelated sentence does not invalidate this edge.')
    errors = {}
    decisions = ask_keyed(models, 'source_coverage',
        'Audit each focus sentence against the actual graph assertions. Check every substantive claim '
        'in that sentence. Other source_sentences may resolve references. First enumerate each separate '
        'source assertion in claims, then cite the graph edges that express that assertion and write their '
        'actual combined reading. For compound sentences account separately for every operation, contrast, '
        'required participant, outcome and qualification. A graph edge about one part of a sentence does '
        'not cover the other parts. If no edges express a source assertion, graph_edge_ids=[] and '
        'preserves_meaning=false. Conditions and definitions cannot supply an absent action or argument '
        'unless it is actually saved in those fields. A relation to a bare participant does not convey '
        'what that participant does. Mark incomplete, stronger, weaker, or reversed readings false. '
        'Then list only genuine missing meanings or unsupported graph edges; use empty lists when faithful. '
        'Equivalent wording and multiple edges can jointly preserve meaning. Mere concept presence is '
        'not a claim. Read predicates literally with their conditions and modality: modality outside the '
        'parentheses applies to the whole assertion, so NOT (A R B) does not mean A R (NOT B). '
        'Additional arguments supply complements or participants, not if/when restrictions. Never add an omitted qualification while reading the graph. Negation does not reverse arguments. '
        'Flag an edge as unsupported only when the supplied source does not support its literal assertion, '
        'not because it is unrelated to the focus sentence. Do not list a faithful edge as unsupported. '
        'An unsupported-edge objection must cite at least one of that edge\'s source_sentence_ids when supplied. '
        'Preserve necessary complements: "A forbids B from doing C" does not assert "A forbids B" '
        'without the activity qualification. Identify source meaning still missing after unsupported '
        'edges are excluded. Do not demand outside knowledge or edges for narrative filler. '
        'Cite exact source_sentence_ids instead of copying quotations; include adjacent IDs when needed '
        'to resolve references. For unsupported entries also copy the exact graph edge id. '
        'Give concise conclusions, never a reasoning transcript.',
        [dict(id=s['id'], focus_sentence=s['text']) for s in sentences], SentenceAudit,
        chunk['id'] + '_coverage_' + str(attempt),
        shared=dict(source_sentences=[dict(id=s['id'], text=s['text']) for s in sentences], graph_assertions=assertions),
        validate=validate, on_error=lambda item, exc: errors.update({item['id']: str(exc)}))
    missing, unsupported = [], []
    for identifier, decision in decisions.items():
        trace.emit('source.sentence_coverage', entity_id=identifier, attempt=attempt, result=decision)
        for claim in decision['claims']:
            if not claim['preserves_meaning']:
                span = spans[identifier]
                missing.append(dict(evidence=span['text'], evidence_start=chunk.get('start', 0)+span['start'],
                    missing_claim=claim['source_assertion'],
                    reason='Source assertion is not preserved by graph reading: ' + claim['graph_reading']))
        for collection, output in (('missing', missing), ('unsupported', unsupported)):
            for issue in decision[collection]:
                chosen = [spans[i] for i in issue['source_sentence_ids']]
                start, end = min(s['start'] for s in chosen), max(s['end'] for s in chosen)
                value = dict(evidence=chunk['text'][start:end], evidence_start=chunk.get('start', 0)+start,
                             missing_claim=issue['missing_claim'], reason=issue['reason'])
                if collection == 'unsupported': value['id'] = issue['id']
                output.append(value)
    result = Coverage(missing=missing, unsupported=unsupported, errors=errors,
                      reason=f'Audited {len(decisions)} of {len(sentences)} source sentences; judgments are model estimates')
    trace.emit('source.coverage_checked', entity_id=chunk['id'], attempt=attempt, result=result.model_dump())
    return result


def preserve_resolved_participants(result, bindings):
    """A repair may change the predicate, but must not erase a resolved participant."""
    for binding in bindings:
        candidates = [r for r in result.relations
                      if any(name_occurs(binding['anchor'], name) for name in (r.source.name, r.target.name))]
        if not any(any(name_occurs(binding['concept'], field) for field in
                       (r.source.name, r.target.name, *(r.argument_qualifiers or []))) for r in candidates):
            raise ValueError(f"Preserve resolved participant {binding['concept']!r} from {binding['mention']!r} "
                             f"in the repair involving {binding['anchor']!r}: name it in an endpoint or "
                             "argument qualifier, including ownership when using a property endpoint.")


def recover_source(extractions, chunks, paragraphs, outline, concepts, relations, facts, models, trace, reviews):
    if not extractions:
        return reviews
    from .extraction import extract, reference_name
    from .debate import review_extractions
    by_chunk = {chunk['id']: chunk for chunk in chunks}
    reports = []
    reviews = list(reviews)
    for extraction in extractions:
        chunk = by_chunk[extraction['chunk_id']]
        record = dict(chunk_id=chunk['id'], attempts=[], status='unresolved')
        reports.append(record)
        attempted = set()
        repair_failures = {}
        for attempt in range(3):
            from .source_precision import precise_source_check
            precision = precise_source_check(chunk, extraction['relations'], models, trace)
            excluded = {r['id'] for r in precision['unsupported']}
            audit_extraction = dict(extraction, relations=[r for r in extraction['relations'] if r['id'] not in excluded])
            try:
                audit = audit_source(chunk, audit_extraction, concepts, models, trace, attempt)
                audit.missing.extend(MissingClaim.model_validate(r) for r in precision['missing'])
                audit.unsupported.extend(UnsupportedAssertion.model_validate(r) for r in precision['unsupported'])
                audit.errors.update(precision['errors'])
            except ModelResponseError as exc:
                record['error'] = str(exc)
                break
            record['attempts'].append(audit.model_dump())
            if audit.errors:
                record['errors'] = audit.errors
            rejected = {item.id: item.model_dump() for item in audit.unsupported}
            if rejected:
                for rows in (extraction['relations'], extraction['relation_proposals'], reviews, facts.rows):
                    for row in rows:
                        if row['id'] in rejected:
                            row.update(accepted=False, source_coverage_objection=rejected[row['id']],
                                review_status='coverage_rejected',
                                decision_reason='Source audit: ' + rejected[row['id']]['reason'])
                            row.setdefault('gates', {})['source_coverage'] = False
                            row['rejection_categories'] = sorted(set(row.get('rejection_categories', [])) | {'unsupported_claim'})
                extraction['relations'][:] = [row for row in extraction['relations'] if row.get('accepted')]
                facts.rows[:] = [row for row in facts.rows if row.get('accepted')]
                trace.emit('source.coverage_rejected', entity_id=chunk['id'], objections=rejected)
            needed = [*audit.missing, *(MissingClaim.model_validate(item.model_dump(exclude={'id'})) for item in audit.unsupported)]
            if not needed:
                record['status'] = 'unresolved' if audit.errors else 'covered_by_model_review'
                break
            if attempt == 2:
                record['status'] = 'remaining_gaps'
                break
            # One corrective request per unique evidence span per pass. It may
            # represent several missing assertions; none are removed from audit.
            spans = {}
            for missing in needed:
                spans.setdefault((missing.evidence, missing.evidence_start), []).append(missing.missing_claim)
            progressed = False
            for index, ((quote, evidence_start), missing_claims) in enumerate(spans.items()):
                missing_claims = list(dict.fromkeys(missing_claims))
                span_key = (quote, evidence_start)
                previous_failures = repair_failures.get(span_key, [])
                rejected_proposals = [dict(source=r['source'], relation=r['relation'], target=r['target'],
                    argument_qualifiers=r.get('argument_qualifiers', []), conditions=r.get('conditions'),
                    modality=r.get('modality'), reason=r.get('decision_reason', ''))
                    for r in reviews if not r.get('accepted') and r.get('evidence')
                    and (quote in r['evidence'] or r['evidence'] in quote)]
                bindings = [dict(mention=r['surface_' + side], concept=r[side],
                                 anchor=r['target' if side == 'source' else 'source'])
                    for r in reviews if not r.get('accepted') and r.get('evidence')
                    and (quote in r['evidence'] or r['evidence'] in quote)
                    for side in ('source', 'target')
                    if reference_name(r.get('surface_' + side, '')) and not reference_name(r[side])]
                signature = (quote, evidence_start, tuple(sorted(missing_claims)), tuple(previous_failures))
                if signature in attempted:
                    continue
                attempted.add(signature)
                start = evidence_start if evidence_start is not None else chunk['start'] + chunk['text'].index(quote)
                repair = dict(chunk, id=f"{chunk['id']}_coverage_{attempt}_{index}",
                              text=quote, start=start, end=start + len(quote), word_count=len(quote.split()))
                class RepairModels:
                    def __getattr__(self, name):
                        return getattr(models, name)
                    def ask(self, role, instruction, payload, schema, entity_id, validator=None, **kwargs):
                        if role == 'extractor':
                            payload = dict(payload, missing_source_meanings=missing_claims,
                                previous_repair_failures=previous_failures,
                                rejected_source_proposals=rejected_proposals,
                                resolved_participants=bindings,
                                already_represented=[dict(source=r['source'], relation=r['relation'], target=r['target'],
                                    conditions=r.get('conditions'), modality=r.get('modality'),
                                    argument_qualifiers=r.get('argument_qualifiers', [])) for r in extraction['relations']])
                            instruction += (' Recover the missing source meanings using precise open-vocabulary predicates. '
                                'The audit is fallible advice: verify each suggestion against the quoted source. '
                                'Preserve negation, uncertainty, conditions and full participant meanings. '
                                'Use rejected_source_proposals and previous_repair_failures to fix the specific error. '
                                'Preserve text-supported resolved actors and property owners; do not replace them '
                                'with an anonymous model, a bare action, or a different participant. '
                                'Do not add background knowledge or merely restate already represented claims.')
                            original_validator = validator
                            def validator(result):
                                if original_validator:
                                    original_validator(result)
                                preserve_resolved_participants(result, bindings)
                        return models.ask(role, instruction, payload, schema, entity_id, validator=validator, **kwargs)
                recovered = extract([repair], paragraphs, RepairModels(), trace, concepts, relations)
                from .qualifiers import complete_arguments
                complete_arguments(recovered, models, trace)
                decisions = review_extractions(recovered, [repair], outline, concepts, facts, models, trace)
                for row in decisions:
                    row['chunk_id'] = chunk['id']
                    row['source_coverage_repair'] = True
                for recovered_chunk in recovered:
                    for row in recovered_chunk['relation_proposals']:
                        row['chunk_id'] = chunk['id']
                    extraction['relation_proposals'].extend(recovered_chunk['relation_proposals'])
                    extraction['relations'].extend(recovered_chunk['relations'])
                    extraction['concepts'] = list(dict.fromkeys(extraction['concepts'] + recovered_chunk['concepts']))
                reviews.extend(decisions)
                failures = list(dict.fromkeys(
                    [issue['reason'] for item in recovered for issue in item.get('issues', [])]
                    + [row['decision_reason'] for row in decisions
                       if not row.get('accepted') and row.get('decision_reason')]))
                repair_failures[span_key] = failures
                # Retry only with new failure information, within the existing two-pass budget.
                progressed |= bool(failures and failures != previous_failures)
                progressed |= any(row.get('accepted') and not row.get('duplicate_of') for row in decisions)
            trace.save('artifacts/extractions.json', extractions)
            if not progressed:
                record['status'] = 'remaining_gaps'
                break
        trace.save('artifacts/source_coverage.json', dict(policy='bounded_model_audit_and_independent_source_review',
                                                        independent_accuracy=False, chunks=reports))
    trace.save('artifacts/extraction_review.json', reviews)
    trace.save('artifacts/extraction_proposals.json', extractions)
    trace.save('artifacts/extractions.json', extractions)
    quality = [dict(chunk_id=e['chunk_id'], reviewed=sum(r['chunk_id']==e['chunk_id'] for r in reviews),
        accepted=sum(r['chunk_id']==e['chunk_id'] and r.get('accepted',False) for r in reviews),
        rejected=sum(r['chunk_id']==e['chunk_id'] and not r.get('accepted',False) and r.get('review_status')!='unresolved' for r in reviews),
        unresolved=sum(r['chunk_id']==e['chunk_id'] and r.get('review_status')=='unresolved' for r in reviews)) for e in extractions]
    trace.save('artifacts/extraction_quality.json', quality)
    for report in reports:
        if report['status'] != 'covered_by_model_review':
            issue = dict(step='source_coverage', id=report['chunk_id'], status='unresolved',
                         reason=report.get('error', 'Source coverage still has gaps; inspect artifacts/source_coverage.json'))
            if not hasattr(trace, 'unresolved_items'): trace.unresolved_items = []
            trace.unresolved_items.append(issue)
            trace.emit('item.unresolved', entity_id=report['chunk_id'], **issue)
    trace.save('artifacts/unresolved_items.json', getattr(trace, 'unresolved_items', []))
    return reviews
