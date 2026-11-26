"""Bounded same-model source/graph comparisons for semantically risky sentences."""
import re
import json
from pydantic import Field
from .records import Record
from .models import ModelResponseError


class Check(Record):
    reason: str = Field(max_length=400)
    faithful: bool
    missing_or_changed_meaning: str | None


class SourceReading(Record):
    reason: str = Field(max_length=300)
    statements: list[str] = Field(min_length=1,
        description='Explicit source assertions with their actors, actions, arguments, conditions and modality; hypothetical premises remain hypothetical')


class EdgeObjection(Record):
    reason: str = Field(max_length=300)
    unsupported: bool


def needs_precision(row):
    quote = row.get('evidence','').casefold()
    if quote and row.get('source_coverage_repair'): return True
    if re.search(r'\b(?:rather than|instead of|neither|into|onto)\b|\bfrom\s+\w+ing\b',quote):
        return True
    negative=r"\b(?:not|never|cannot|without)\b|n't\b"
    reading=' '.join([row.get('relation','').replace('_',' '),row.get('modality') or '',
        row.get('conditions') or '',*row.get('argument_qualifiers',[])]).casefold()
    if re.search(negative,quote) and not re.search(negative,reading): return True
    # Conditional premises and time restrictions must not become unqualified
    # occurrence claims. Route omissions to verification, never invent a repair.
    for markers in (r'\b(?:if|unless)\b',r'\b(?:during|after|before|when|while)\b',
                    r'\b(?:must|should|may|might|can|could)\b'):
        if re.search(markers,quote) and not re.search(markers,reading): return True
    label=re.sub(r'[^a-z0-9]+','_',row.get('relation','').casefold()).strip('_')
    original=re.sub(r'[^a-z0-9]+','_',row.get('surface_relation',row.get('relation','')).casefold()).strip('_')
    return label != original and bool(re.search(r'_(?:in|into|to|from|by)$',label))


def enclosing_evidence(chunk, row):
    """A valid short quote may omit the clause's governing if/not/must.

    Expand it to complete containing source sentences using its exact offsets;
    repeated quotations retain their original occurrence.
    """
    quote, base = row.get('evidence',''), chunk.get('start',0)
    text = chunk.get('text','')
    start = row.get('evidence_start')
    if start is None:
        found = text.find(quote) if quote else -1
        start = base + found if found >= 0 else None
    if start is None or not quote or text[start-base:start-base+len(quote)] != quote:
        return quote, row.get('evidence_start')
    end = start-base+len(quote)
    local = start-base
    boundaries = [0, *(m.end() for m in re.finditer(r'(?<=[.!?])\s+(?=\S)',text)),len(text)]
    left = max(b for b in boundaries if b <= local)
    right = min(b for b in boundaries if b >= end)
    return text[left:right], base+left


def conditional_premise_without_scope(chunk, row):
    """Conservative grammar veto, not a source-fact or repair generator."""
    if row.get('conditions') or row.get('modality'): return False
    scope=' '.join([row.get('relation','').replace('_',' '),*row.get('argument_qualifiers',[])])
    if re.search(r'\b(?:if|unless|conditional|hypothetical|assuming|provided|cases?|when)\b',scope,re.I):
        return False
    quote,text=row.get('evidence',''),chunk.get('text','')
    if not quote: return False
    start=row.get('evidence_start')
    if start is None:
        if text.count(quote)!=1: return False
        start=chunk.get('start',0)+text.index(quote)
    local=start-chunk.get('start',0)
    if text[local:local+len(quote)]!=quote: return False
    end=local+len(quote.rstrip(' ,'))
    premises=list(re.finditer(r'\b(?:if|unless)\b[^,;.?!]*?(?=,|\bthen\b)',text,re.I))
    if any(match.start()<=local and end<=match.end() for match in premises): return True
    # A quote may include the whole sentence. Bind an explicitly quoted source
    # name and verb to the premise, without fuzzy matching or a word-distance cap.
    def normalized(value):
        return ' '.join(re.findall(r'\w+',str(value or '').casefold().replace('_',' ')))
    subjects={normalized(row.get(k)) for k in ('source','surface_source')}-{''}
    verbs={normalized(row.get(k)) for k in ('relation','surface_relation')}-{''}
    def binding(fragment,subject,verb):
        value=' '+normalized(fragment)+' '
        at=value.find(' '+subject+' ')
        return at>=0 and (' '+verb+' ') in value[at+len(subject)+1:]
    outside=text
    for match in reversed(premises): outside=outside[:match.start()]+' '+outside[match.end():]
    return any(binding(match.group(),subject,verb) and not binding(outside,subject,verb)
        for match in premises if match.start()<end and match.end()>local
        for subject in subjects for verb in verbs)


def precise_source_check(chunk, rows, models, trace):
    """Read evidence independently, then compare risky edges and check objections.

    Full-sentence coverage is handled by the separate coverage audit. Keeping the
    Two short non-thinking requests avoid exhausting a local reasoning budget.
    A partial but valid edge is not rejected for facts represented by other edges.
    """
    result = dict(missing=[], unsupported=[], errors={})
    fields=('source','relation','target','relation_definition','conditions','modality')
    failed = getattr(trace, '_precision_failures', {})
    trace._precision_failures = failed
    for row in rows:
        if not row.get('accepted'): continue
        quote,offset=enclosing_evidence(chunk,row)
        if not needs_precision(dict(row,evidence=quote)): continue
        identifier=row['id']+'_precision'
        fingerprint=json.dumps(dict(quote=quote,context=chunk.get('text'),
            assertion={k:row.get(k) for k in (*fields,'argument_qualifiers')}),sort_keys=True)
        if fingerprint in failed:
            result['errors'][identifier]=failed[fingerprint]
            trace.emit('source.precision_failure_reused',entity_id=identifier,error=failed[fingerprint])
            continue
        saved_think,saved_options=models.think,models.options
        try:
            models.think=False
            models.options=dict(saved_options,num_predict=min(saved_options['num_predict'],1536))
            reading=models.ask('source_scope_reader',
                'Read the source quote without making a graph. State each explicit proposition in concise '
                'ordinary language, preserving who does what to whom, essential complements, timing, '
                'negation, uncertainty and conditions. Resolve references using source_context only. '
                'An if/unless premise does NOT assert that the event actually occurred. A contrast or '
                'prohibition does NOT assert its rejected alternative. Do not add outside knowledge.',
                dict(source_quote=quote.strip(),source_context=chunk.get('text',quote)),
                SourceReading,identifier+'_reading')
            if conditional_premise_without_scope(chunk,row):
                issue=dict(evidence=quote,evidence_start=offset,
                    missing_claim='\n'.join(reading.statements),
                    reason='The quoted subject and predicate are inside an if/unless premise; an occurrence edge needs explicit conditional scope.')
                result['missing'].append(issue)
                result['unsupported'].append(dict(id=row['id'],**issue))
                trace.emit('source.conditional_premise_rejected',entity_id=identifier,
                    source_reading=reading.model_dump(),reason=issue['reason'])
                continue
            def validate(answer):
                if answer.faithful == bool(answer.missing_or_changed_meaning):
                    raise ValueError('A faithful assertion needs no correction; an unfaithful assertion must identify the missing or changed meaning')
            assertion={k:row.get(k) for k in fields}
            if row.get('argument_qualifiers'): assertion['argument_qualifiers']=row['argument_qualifiers']
            answer=models.ask('source_fidelity_check',
                'Is this specific graph assertion faithful to the source? Read its predicate as ordinary '
                'language with the fixed source and target, then apply ONLY its saved qualifiers. '
                'The separate source reading is fallible advice: verify it against the quote. Check '
                'Resolve pronouns and property owners using source_context; an antecedent need not be '
                'repeated in source_quote. Context resolves references, not additional claims. Check '
                'argument roles, including whether the target is what is acted on versus a destination, '
                'and essential actions, results, conditions, timing, negation and modality. '
                'A hypothetical premise cannot become an asserted occurrence. Do not mentally repair '
                'the edge with information missing from its fields. Other facts in the quote need not '
                'be repeated, but this edge must preserve all qualifications of its own proposition. '
                'Give a concise concrete verdict.',
                dict(source_quote=quote.strip(),source_context=chunk.get('text',quote),
                     source_reading=reading.model_dump(),graph=assertion),
                Check,identifier,validator=validate)
            trace.emit('source.precision_checked',entity_id=identifier,result=answer.model_dump(),model=models.model)
            if answer.faithful: continue
            models.think=saved_think
            models.options=saved_options
            # Another edge's conditions cannot scope an unqualified occurrence
            # claim. Once the model rejects this assertion, do not let a coverage
            # reviewer excuse it merely because a related conditional edge exists.
            saved_scope=' '.join([row.get('relation','').replace('_',' '),*row.get('argument_qualifiers',[])])
            unqualified_conditional = (re.search(r'\b(?:if|unless)\b',quote,re.I)
                and not row.get('conditions') and not row.get('modality')
                and not re.search(r'\b(?:if|unless|conditional|hypothetical)\b',saved_scope,re.I))
            if unqualified_conditional:
                issue=dict(evidence=quote,evidence_start=offset,
                    missing_claim=answer.missing_or_changed_meaning,reason=answer.reason)
                result['missing'].append(issue)
                result['unsupported'].append(dict(id=row['id'],**issue))
                continue
            from .batching import ask_keyed
            # Other accepted edges may legitimately carry another part of a
            # compound assertion. Include them for objection applicability.
            related=[{k:r.get(k) for k in ('id',*fields,'argument_qualifiers')} for r in rows if r.get('accepted') and
                     (r.get('extraction_unit_id') == row.get('extraction_unit_id') if row.get('extraction_unit_id')
                      else r.get('evidence') == quote)]
            decisions=ask_keyed(models,'source_objection_applicability',
                'Does the supplied objection show that this specific graph edge is itself unsupported or misleading? '
                'Other accepted edges can jointly preserve a compound source assertion. Missing some other fact '
                'does not invalidate a valid edge. But an omitted essential action or argument of this edge, '
                'reversed direction, or lost negation does invalidate it. Judge the saved fields against the '
                'quote and graph context; do not mentally repair this edge. Resolve pronouns and property '
                'owners using source_context before deciding that a named participant is unsupported.',
                [dict(id=row['id'],graph=assertion)],EdgeObjection,identifier+'_objection',
                shared=dict(source_quote=quote,source_context=chunk.get('text',quote),
                            objection=answer.model_dump(),other_accepted_edges=related),
                on_error=lambda item,exc: result['errors'].update({item['id']:str(exc)}))
            decision=decisions.get(row['id'])
            if decision and decision['unsupported']:
                issue=dict(evidence=quote,evidence_start=offset,
                           missing_claim=answer.missing_or_changed_meaning,reason=decision['reason'])
                result['missing'].append(issue)
                result['unsupported'].append(dict(id=row['id'],**issue))
        except ModelResponseError as exc:
            result['errors'][identifier]=str(exc)
            failed[fingerprint]=str(exc)
            trace.emit('source.precision_unresolved',entity_id=identifier,error=str(exc))
        finally:
            models.think=saved_think
            models.options=saved_options
    return result
