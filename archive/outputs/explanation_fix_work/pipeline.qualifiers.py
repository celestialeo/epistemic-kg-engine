"""Representation checks that request model correction without inventing facts."""
import re
from pydantic import model_validator, Field
from .records import Record


def validate_polarity(predicate, modality):
    """Explicit negation in two fields is ambiguous; require an unambiguous rewrite.

    This does not remove a negation or guess which polarity the author intended.
    Implicitly negative verbs (prevents, excludes, etc.) are left to semantic review.
    """
    pattern = r"\b(?:not|never|cannot|can't|doesn't|don't|didn't|isn't|aren't|won't|without)\b"
    if re.search(pattern, predicate.replace('_', ' ').casefold()) and re.search(pattern, (modality or '').casefold()):
        raise ValueError(f'Explicit negation occurs in both predicate={predicate!r} and modality={modality!r}. '
                         'Rewrite using a positive predicate and the complete polarity in modality, '
                         'preserving the source meaning; do not negate the same assertion twice.')


class Polarity(Record):
    relation: str
    relation_definition: str
    modality: str | None

    @model_validator(mode='after')
    def unambiguous(self):
        validate_polarity(self.relation, self.modality)
        return self


def correct_polarity(row, source, models, trace, entity_id):
    try:
        validate_polarity(row['relation'], row.get('modality'))
        return row
    except ValueError as exc:
        problem = str(exc)
    correction = models.ask('polarity_repair',
        'Correct an ambiguous graph representation against its authoritative source sentence. '
        'The draft accidentally encodes explicit negation in both the predicate and modality. '
        'Read the source to determine the intended meaning; do not cancel accidental duplicated negation. '
        'Use an affirmative reusable predicate and definition, with the complete negation or uncertainty '
        'in modality exactly once. Keep endpoints, participants and conditions unchanged. '
        'For example, a negative use assertion has predicate uses, definition SOURCE employs TARGET, '
        'and modality does not. This is a representation correction, not permission to add facts.',
        dict(source=source, draft=row, problem=problem), Polarity, entity_id)
    revised = dict(row, **correction.model_dump())
    trace.emit('representation.polarity_repaired', entity_id=entity_id, original=row, corrected=revised)
    return revised


class SourceRoles(Record):
    reason: str = Field(min_length=1, max_length=400, description='One short conclusion identifying the grammatical roles')
    predicate_subject: str | None
    predicate_object: str | None


def explicit_reversed_clause(row):
    """Recognize an explicit active relative clause, never infer a new fact.

    'X that Y does not verb' has Y as subject and X as object. Exact named
    bindings plus this surface syntax can disprove the reversed candidate.
    All unmatched constructions continue to model-based semantic review.
    """
    from .identity import concept_key
    def bare(value):
        return re.sub(r'^(?:a|an|the)\s+', '', concept_key(value))
    source, target = bare(row['source']), bare(row['target'])
    if source == target:
        return False
    verb = re.sub(r'^(?:does not|do not|did not|not)\s+', '', concept_key(row['relation']))
    verbs = [verb]
    if verb.endswith('s') and not verb.endswith('ss'):
        verbs.append(verb[:-1])
    pattern = (r'\b' + re.escape(source) + r'\s+(?:that|which)\s+(?:(?:a|an|the)\s+)?' +
               re.escape(target) + r'\s+(?:does not|do not|did not|doesnt|dont|didnt|cannot|can not)\s+(?:' +
               '|'.join(re.escape(v) for v in verbs) + r')\b')
    return bool(re.search(pattern, concept_key(row['evidence'])))


def negative_direction(row, models, trace):
    """Blind source-role reading; only exact reversed bindings can veto an edge.

    This never authorizes acceptance, aliases, or a repaired assertion. Ambiguous
    references and nonmatching names still require the ordinary semantic review.
    """
    text = ((row.get('modality') or '') + ' ' + row['relation'].replace('_', ' ')).casefold()
    if not re.search(r"\b(?:not|never|cannot|can't|doesn't|don't|without)\b", text):
        return None
    if explicit_reversed_clause(row):
        result = dict(predicate_subject=row['target'], predicate_object=row['source'],
            exact_reversed_bindings=True, basis='explicit_active_relative_clause',
            reason='The source clause places the candidate target as verb subject and candidate source as its relative object')
        trace.emit('source.roles_checked', entity_id=row['id'], result=result)
        return result
    quote = row['evidence']
    def validate(result):
        for value in (result.predicate_subject, result.predicate_object):
            if value is not None and not re.search(r'(?<!\w)' + re.escape(value) + r'(?!\w)', quote, re.I):
                raise ValueError('Copy subject/object as exact continuous source phrases, or return null when unclear')
    reading = models.ask('source_role_reader',
        'Find the grammatical arguments of the requested predicate in the source. Who or what performs '
        'that verb, even if it is negated? That is predicate_subject. Who or what receives that action? '
        'That is predicate_object. Parse inside relative clauses rather than treating the outer noun '
        'as the subject. Copy arguments as continuous source phrases. Negation does not remove the '
        'grammatical subject or object. Return null only for an argument absent from this source. '
        'Give one short conclusion, then the arguments. No graph endpoints are supplied: only parse source.',
        dict(source_text=quote, predicate=row['relation'].replace('_', ' ')),
        SourceRoles, row['id'] + '_source_roles', validator=validate)
    from .identity import concept_key
    def name(value):
        if not value or not any(c.isalnum() for c in value):
            return ''
        return concept_key(re.sub(r'^(?:a|an|the)\s+', '', value or '', flags=re.I))
    subject, obj = name(reading.predicate_subject), name(reading.predicate_object)
    source, target = name(row['source']), name(row['target'])
    reversed_bindings = bool(subject and obj and source != target and subject == target and obj == source)
    result = dict(**reading.model_dump(), exact_reversed_bindings=reversed_bindings)
    trace.emit('source.roles_checked', entity_id=row['id'], result=result)
    return result


class SourceArguments(Record):
    prevented_or_enabled_action: str | None = Field(description='If the source prevents/enables a participant from doing something, copy that specified activity including its objects; otherwise null')
    result_or_destination: str | None = Field(description='If the source converts/maps/divides something into a result or destination, copy that stated result; otherwise null')
    other_required_arguments: list[str] = Field(description='Other essential source-stated participants or qualifications absent from the existing edge; empty if none')
    reason: str = Field(max_length=300)


def complete_arguments(extractions, models, trace):
    """Recover quoted action complements before normal independent admission.

    These are model proposals, never automatically accepted facts. The regular
    source review sees the complete qualified edge after this bounded step.
    """
    from .batching import ask_keyed
    from .health import finish_item
    rows = [r for e in extractions for r in e['relation_proposals']]
    pending = [r for r in rows if 'source_arguments' not in r and 'argument_qualifiers' not in r]
    if not pending: return
    items = [dict(id=r['id'], source=r['source'], predicate=r['relation'], target=r['target'],
                  conditions=r.get('conditions'), modality=r.get('modality'), quote=r['evidence']) for r in pending]
    class ArgumentModels:
        # More independent decisions in one answer caused the local model to
        # overlook complements near the end. This caps group size, not content.
        batch_size = min(getattr(models, 'batch_size', None) or 4, 4)
        def __getattr__(self, name): return getattr(models, name)
    def validate(item, result):
        phrases = [result.prevented_or_enabled_action, result.result_or_destination, *result.other_required_arguments]
        quote = ' '.join(item['quote'].casefold().split())
        if any(p and ' '.join(p.casefold().split()) not in quote for p in phrases):
            raise ValueError('Copy each argument as a continuous phrase from this exact quote; do not invent or paraphrase arguments')
    errors = {}
    answers = ask_keyed(ArgumentModels(), 'source_arguments',
        'Read the quoted source and identify essential action complements for the displayed relation. '
        'Copy the stated activity, transformation result, or other necessary participants. '
        'Do not repeat the existing subject/object, conditions or modality. Do not change the direction '
        'or negation. Use null when the source does not state that argument. Return concise quoted '
        'phrases, not background knowledge. These phrases will qualify this edge and undergo source review.',
        items, SourceArguments, 'source_arguments', validate=validate,
        on_error=lambda item, exc: errors.update({item['id']: str(exc)}))
    for row in pending:
        answer = answers.get(row['id'])
        if answer is None:
            finish_item(trace, 'source_arguments', row['id'], errors.get(row['id'], 'No validated argument completion'))
            continue
        original = row.get('conditions')
        represented = ' '.join(str(row.get(k) or '').casefold() for k in ('source','relation','target','conditions','modality'))
        additions = []
        for label, phrase in [('activity', answer['prevented_or_enabled_action']),
                              ('result/destination', answer['result_or_destination']),
                              *[('participant/scope', p) for p in answer['other_required_arguments']]]:
            if phrase and phrase.casefold() not in represented:
                additions.append(label + ': ' + phrase)
                represented += ' ' + phrase.casefold()
        row['source_arguments'] = answer
        row['argument_qualifiers'] = additions
        trace.emit('source.arguments_completed', entity_id=row['id'], original_conditions=original,
                   conditions=row.get('conditions'), argument_qualifiers=additions, proposal=answer, requires_source_review=True)
        finish_item(trace, 'source_arguments', row['id'])
