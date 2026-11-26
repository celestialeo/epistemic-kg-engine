from .settings import setting
"""Reviewed graph refinement and a content-bound publication gate.

Model review checks representation and source support, not external factual truth.
Original graphs and decisions remain in the trace; failed reviews cannot publish.
"""
import copy
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import hashlib
import json
import re
from pathlib import Path
from typing import Literal
from pydantic import Field, create_model
from .records import Record
from .identity import concept_key
from .relations import DEFAULT_RELATIONS
from .models import ModelResponseError, OutputLimitError
from .settings import budgeted_pages, predicate_pattern, estimated_tokens

VERSION = 4
SHORT_KEY = predicate_pattern()
CONTRACTS = {k: v[0] for k, v in DEFAULT_RELATIONS.items() if re.fullmatch(SHORT_KEY, k)}
CONTRACTS.update({
    'uses': 'SOURCE uses TARGET as a resource or mechanism.',
    'processes': 'SOURCE processes TARGET as input.',
    'improves': 'SOURCE improves the performance or quality of TARGET.',
    'reduces': 'SOURCE decreases the amount or degree of TARGET.',
    'constrains': 'SOURCE limits the capacity or extent of TARGET.',
    'applies': 'SOURCE applies the rule or method TARGET.',
    'accesses': 'SOURCE accesses information from TARGET.',
    'supplements': 'SOURCE supplies information in addition to TARGET.',
    'supports': 'SOURCE assists or contributes to TARGET without guaranteeing it.',
})


class Endpoint(Record):
    label: str = Field(min_length=1, max_length=setting('text', 'graph_label_chars'))
    definition: str = Field(min_length=1, max_length=setting('text', 'display_definition_chars'))


class NodeDecision(Record):
    id: str
    label: str = Field(min_length=1, max_length=setting('text', 'graph_label_chars'))
    definition: str = Field(min_length=1, max_length=setting('text', 'graph_definition_chars'))
    merge_into: str | None
    reason: str = Field(min_length=1, max_length=setting('text', 'definition_chars'))


class NodePlan(Record):
    nodes: list[NodeDecision]


class NodeVerdict(Record):
    id: str
    valid: bool
    reason: str = Field(min_length=1, max_length=setting('text', 'definition_chars'))


class NodeReview(Record):
    nodes: list[NodeVerdict]


class Participant(Record):
    role: Literal['agent', 'owner', 'patient', 'beneficiary', 'instrument', 'resource', 'location', 'recipient', 'experiencer'] = Field(
        description='Semantic role such as owner, agent, patient, beneficiary, instrument, or resource. Not a new factual predicate.')
    scope: Literal['source', 'target', 'assertion', 'purpose']
    entity: Endpoint


CONTEXT_POLICY = (
    'Preserve who does what to whom, shared entities, pronoun antecedents and ownership. '
    'Use participants to reference an existing entity by its canonical name with a precise role '
    'and scope (source, target, assertion, or purpose), only where needed to preserve meaning. '
    'For an owned property, record its owner with scope=source or target as appropriate. '
    'For an enabled action, record its agent. For a purpose, retain its agent and affected object '
    'when not already explicit in the main endpoints. Do not repeat source/target endpoints merely '
    'to label them source and target; give only additional semantic roles. Reuse the same entity across assertions. '
    'Resolve references only from the supplied source context; preserve ambiguity when unresolved. '
    'Put intended goals in purpose, temporal qualifications in timing, other circumstances in '
    'conditions, and uncertainty/negation in modality. These fields are graph content, not descriptions. '
    'A purpose is not a guaranteed result. Apply shared temporal scope to coordinated clauses only '
    'when supported. Never rely on node definitions or evidence quotes to supply missing participants. '
    'Do not add a node for every noun, invent an event, or create connections merely for connectivity. '
    'Prefer the same reusable predicate for the same action across different objects; do not append '
    'an object name to a predicate already expressed by the target. Keep different meanings distinct. '
)


class Fact(Record):
    # Require explicit decisions in generated JSON while retaining defaults when
    # loading legacy records and constructing existing programmatic callers.
    model_config = {'json_schema_extra': {'required': ['source', 'relation', 'definition', 'target',
        'conditions', 'modality', 'evidence', 'participants', 'purpose', 'timing', 'anchor']}}
    source: Endpoint
    relation: str = Field(pattern=SHORT_KEY, max_length=setting('labels', 'predicate_chars'))
    definition: str = Field(min_length=1, max_length=setting('text', 'display_definition_chars'))
    target: Endpoint
    conditions: str | None = Field(description='Circumstances, time, purpose, or scope of this assertion; null when unspecified')
    modality: str | None = Field(max_length=setting('text', 'modality_chars'), description='Possibility, necessity, recommendation, or other claim strength; null when unspecified. Do not put time or purpose here.')
    evidence: str | None
    participants: list[Participant] = Field(default_factory=list)
    purpose: str | None = None
    timing: str | None = None
    anchor: str | None = Field(default=None, description='Exact short phrase in evidence identifying this specific assertion, for source ordering; not the entire shared sentence')


def fact_endpoints(fact):
    return [fact.source, fact.target] + [p.entity for p in fact.participants]


def background_assertion(fact):
    """Retain entity meanings so reviewers do not challenge a different sense."""
    return dict(source=fact.source.label, relation=fact.relation, definition=fact.definition,
                source_definition=fact.source.definition, target_definition=fact.target.definition,
                target=fact.target.label, conditions=fact.conditions, modality=fact.modality,
                purpose=fact.purpose, timing=fact.timing,
                participants=[dict(role=p.role, scope=p.scope, entity=p.entity.label,
                                   definition=p.entity.definition) for p in fact.participants])


def edge_node_ids(edge):
    return {edge['source'], edge['target']} | {p['node'] for p in edge.get('participants', [])}


def context_view(edge, nodes):
    return dict(purpose=edge.get('purpose'), timing=edge.get('timing'),
                participants=[dict(role=p['role'], scope=p['scope'], entity=nodes[p['node']]['label'])
                              for p in edge.get('participants', [])])


class FactPlan(Record):
    facts: list[Fact] = Field()
    reason: str = Field(min_length=1, max_length=setting('text', 'question_chars'))


class SingleFactPlan(FactPlan):
    facts: list[Fact] = Field(max_length=1)


@dataclass(frozen=True)
class ReviewPolicy:
    """Topic-independent resource limits; these never establish semantic truth."""
    node_batch_size: int | None = None
    repair_attempts: int = setting('review', 'repair_attempts')
    candidate_limit: int | None = None
    alias_similarity: float = setting('review', 'alias_similarity')
    edge_batch_size: int | None = None
    reasoning: bool = setting('review', 'reasoning')
    reasoning_output_tokens: int = setting('model', 'max_output_tokens')
    reasoning_fallback: bool = setting('review', 'reasoning_fallback')

    def __post_init__(self):
        if any(v is not None and v < 1 for v in (self.node_batch_size, self.repair_attempts, self.candidate_limit, self.edge_batch_size, self.reasoning_output_tokens)):
            raise ValueError('Review batch sizes, candidate limit and attempts must be positive')
        if not 0 <= self.alias_similarity <= 1:
            raise ValueError('Alias candidate similarity must be between zero and one')


def nearest_nodes(focus, candidates, limit):
    """Bound retrieval context. Similar wording only retrieves; reviewers decide identity."""
    def rank(node):
        return max(SequenceMatcher(None, (f['label']+' '+f['definition']).casefold(),
                                   (node['label']+' '+node['definition']).casefold()).ratio() for f in focus)
    return sorted(candidates, key=rank, reverse=True)[:limit]


def source_units(graph):
    provenance = graph.get('provenance', {})
    return provenance.get('chunks') or [dict(id='source', text=provenance.get('text', ''))]


def node_context(focus, graph, limit=None):
    """Retrieve source mentions as well as incident evidence without narrowing a shared concept."""
    ids = {n['id'] for n in focus}
    passages = [c['text'] for c in source_units(graph)
                if any(ch.isalnum() for ch in c['text']) and
                any(concept_key(n['label']) in concept_key(c['text']) for n in focus)]
    quotes = [e['evidence'] for e in graph['edges'] if e.get('evidence') and
              (e['source'] in ids or e['target'] in ids)]
    passages.extend(q for q in quotes if not any(q in p for p in passages))
    passages = list(dict.fromkeys(passages))
    if limit is not None and len(passages) > limit:
        passages = [passages[round(i * (len(passages)-1) / max(1, limit-1))] for i in range(limit)]
    return '\n\n'.join(passages)


class DisplayedReading(Record):
    meaning: str = Field(min_length=1, max_length=setting('text', 'definition_chars'))


class FactVerdict(Record):
    index: int
    literal_meaning: str = Field(min_length=1, max_length=setting('text', 'definition_chars'))
    faithful: bool
    supported: bool
    direction_valid: bool
    label_matches_contract: bool = Field(description='The short predicate name agrees with the contract meaning and SOURCE-to-TARGET direction')
    endpoints_valid: bool
    qualifications_preserved: bool
    reason: str = Field(min_length=1, max_length=setting('text', 'short_explanation_chars'))


class FactReview(Record):
    facts: list[FactVerdict]
    omission_valid: bool
    reason: str = Field(min_length=1, max_length=setting('text', 'short_explanation_chars'))


class GraphReview(Record):
    consistent: bool
    concepts_distinct: bool
    issues: list[str]


class ClaimCoverage(Record):
    assertion: str
    edge_ids: list[str]
    represented: bool
    reason: str


class SentenceCoverage(Record):
    index: int
    claims: list[ClaimCoverage]
    no_claim_reason: str | None


class SourceCoverage(Record):
    sentences: list[SentenceCoverage]
    bad_edge_ids: list[str]
    complete: bool
    issues: list[str]


class SourceRepairReview(FactReview):
    makes_progress: bool = Field(description='The proposed facts correct at least one reported gap or incorrect assertion; merely repeating correct facts is not progress')


class RepairScopeReview(Record):
    omission_valid: bool
    makes_progress: bool
    reason: str = Field(min_length=1, max_length=setting('text', 'short_explanation_chars'))


class BackgroundChallenge(Record):
    valid: bool
    counterexample: str | None
    required_qualification: str | None
    reason: str


class ChallengeAssessment(Record):
    counterexample_applies: bool
    qualification_needed: bool
    assertion_supported: bool
    reason: str


class SourceRevision(Record):
    remove_ids: list[str] = Field(description='Only supplied document-edge IDs that need replacement; keep correct edges')
    facts: list[Fact] = Field(description='Only missing or corrected assertions supported by the source chunk')
    reason: str = Field(min_length=1, max_length=setting('text', 'question_chars'))


class ReferenceBinding(Record):
    model_config = {'json_schema_extra': {'required': ['mention','antecedent','resolved_meaning','evidence',
        'ambiguous','antecedent_node','owned_property_node','performed_action_node']}}
    mention: str = Field(description='Exact referring phrase, including its property where possessive; distinguish separate occurrences')
    expression: str | None = None
    antecedent: str | None
    resolved_meaning: str
    evidence: str
    ambiguous: bool
    antecedent_node: str | None = Field(default=None, description='Existing node ID for the antecedent; null only if no supplied node names it or it is ambiguous')
    owned_property_node: str | None = Field(default=None, description='For a possessive reference, the existing node ID of the PROPERTY being owned, not the owner; otherwise null')
    performed_action_node: str | None = Field(default=None, description='For a subject reference, the existing node ID of the ACTION it performs, not the actor; otherwise null')


class SourceContext(Record):
    references: list[ReferenceBinding]


class ReferenceMention(Record):
    mention: str
    expression: str | None = Field(default=None, description='Exact source words naming the possessed property or performed activity, included within mention; null only if no such expression occurs')
    antecedent: str | None
    resolved_meaning: str
    evidence: str
    ambiguous: bool
    owned_property: str | None = None
    performed_action: str | None = None


class ContextCheck(Record):
    valid: bool
    issues: list[str]


class BindingComparison(Record):
    original_valid: bool
    alternative_valid: bool
    reason: str


class FactContextCheck(Record):
    actors_explicit: bool
    ownership_explicit: bool
    purpose_preserved: bool
    timing_preserved: bool
    qualifications_preserved: bool
    role_scopes_correct: bool
    issues: list[str]


CONTEXT_CHECK_FLAGS = ('actors_explicit', 'ownership_explicit', 'purpose_preserved',
                       'timing_preserved', 'qualifications_preserved', 'role_scopes_correct')


def resolve_source_context(unit, ask, attempts, nodes=(), *, focus=None):
    """Resolve references before graph editing; never invent an antecedent by string rules."""
    if focus is None:
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', unit['text']) if s.strip()]
        references = []
        for index, sentence in enumerate(sentences):
            scoped = dict(unit, id=f"{unit['id']}_sentence_{index}")
            references.extend(resolve_source_context(scoped, ask, attempts, nodes, focus=sentence)['references'])
        return dict(references=references)
    feedback = None
    candidates = {n['id']: n['label'] for n in nodes}
    by_label = {n['label']: n['id'] for n in nodes}
    if len(by_label) != len(candidates):
        raise ValueError('Reference candidates require unique canonical labels')
    choice = Literal[tuple(by_label)] | None if by_label else type(None)
    mention_schema = create_model('CanonicalReference', __base__=ReferenceMention,
        antecedent=(choice, Field(description='Canonical name of the referent (owner or actor); null if absent or ambiguous')),
        owned_property=(choice, Field(default=None, description='Canonical name of the possessed property, never its owner; null if no matching property is supplied')),
        performed_action=(choice, Field(default=None, description='Canonical name of the action performed, never its actor; null if no matching action is supplied')))
    mention_schema.model_config['json_schema_extra'] = {'required': list(mention_schema.model_fields)}
    context_schema = create_model('CanonicalReferences', references=(list[mention_schema], ...))
    links_schema = create_model('ReferenceLinks',
        antecedent=(choice, ...), owned_property=(choice, ...), performed_action=(choice, ...))
    def bind(result):
        return SourceContext(references=[ReferenceBinding(
            **r.model_dump(exclude={'owned_property', 'performed_action'}),
            antecedent_node=by_label.get(r.antecedent),
            owned_property_node=by_label.get(r.owned_property),
            performed_action_node=by_label.get(r.performed_action)) for r in result.references])
    for attempt in range(attempts):
        def validate(result):
            result = bind(result)
            for binding in result.references:
                if not binding.mention or binding.mention not in binding.evidence or binding.evidence not in unit['text']:
                    raise ValueError('Each reference needs an exact mention and continuous supporting source quote')
                if binding.mention not in focus:
                    raise ValueError('The referring phrase must occur in the focus sentence')
                if binding.expression is not None and (not binding.expression or binding.expression not in focus):
                    raise ValueError('The property/activity expression must be an exact quote from the focus sentence')
                if binding.ambiguous and binding.antecedent is not None:
                    raise ValueError('An ambiguous reference cannot have an asserted antecedent')
                if binding.ambiguous and binding.antecedent_node is not None:
                    raise ValueError('An ambiguous reference cannot have an asserted node identity')
                if any(key is not None and key not in candidates for key in (binding.antecedent_node, binding.owned_property_node, binding.performed_action_node)):
                    raise ValueError('Reference bindings must use supplied node IDs or null')
                if binding.antecedent_node and binding.antecedent_node in {binding.owned_property_node, binding.performed_action_node}:
                    raise ValueError('owned_property_node and performed_action_node must identify the property/action, not the owner/actor itself. '
                                     'Choose the supplied property/action node, or null only when no such node exists.')
                if binding.antecedent_node:
                    binding.antecedent = candidates[binding.antecedent_node]
        proposed = ask('graph_reference_resolver',
            'Resolve source references ONLY; do not classify goals, timing, or graph predicates. '
            'Resolve each occurrence of every pronoun and possessive IN focus_sentence using source as context; do not collapse '
            'two occurrences that refer to different properties or actions. Record the precise '
            'resolved meaning of owned properties and actions, not just the pronoun antecedent. If ambiguous, '
            'set antecedent=null and ambiguous=true and describe the ambiguity. Quote enough continuous text '
            'to support each reference. mention must include the possessed property or performed action, '
            'not merely a bare pronoun. expression quotes the property/activity words within mention. '
            'Ownership means source-attributed possession or association, not legal ownership. '
            'An actor may exhibit a capability without intending or initiating it. '
            'Return an empty list only if focus_sentence has no references. '
            'Select canonical names from existing_entities. antecedent is the OWNER or ACTOR. '
            'For a possessive mention, owned_property is the possessed PROPERTY name. '
            'For a subject mention, performed_action is the ACTION name. '
            'Use null for inapplicable or unavailable entities; never substitute an unrelated supplied action. '
            'These fields name different entities: the owner is not its property, the actor is not its action. '
            'These canonical names will enforce shared identity '
            'on the final graph. Do not invent background knowledge. Use the source language.',
            dict(source=unit['text'], focus_sentence=focus, existing_entities=list(by_label), correction_needed=feedback), context_schema,
            f"references_{unit['id']}_{attempt}", validator=validate, deliberate=False)
        resolved = bind(proposed)
        checked = ask('graph_reference_verifier',
            'Check reference identity and ownership ONLY. Goal and time scope are checked separately on graph assertions. '
            'Does every pronoun and possessive IN focus_sentence resolve to '
            'the text-supported entity, with ownership retained? Are ambiguous references left unresolved? '
            'Check against the original source, not plausibility. Reject wrong, invented or missing reference '
            'bindings and give concrete issues. Do not require repeated bindings to be copied into other records '
            'or discuss purpose/time classification. antecedent must be the referent (owner/actor), '
            'owned_property its possessed property, performed_action the action it performs. '
            'Reject null links only when a supplied entity actually represents that property/action. '
            'An unavailable property or action must stay null; do not demand an unrelated entity instead. '
            'Correct synonyms or referring expressions are acceptable.',
            dict(source=unit['text'], focus_sentence=focus, existing_entities=list(by_label), proposed=proposed.model_dump()), ContextCheck,
            f"references_{unit['id']}_{attempt}_review", deliberate=False)
        link_issues = []
        for index, reference in enumerate(proposed.references):
            if reference.ambiguous:
                continue
            links = ask('graph_reference_binding_reviewer',
                'Independently resolve ONE reference IN focus_sentence. Other source sentences '
                'may identify its antecedent, but never substitute their properties or actions. '
                'Select canonical entity names only. '
                'antecedent is the entity referred to (owner or actor). owned_property is the '
                'possessed object/property for a possessive reference; performed_action is the action '
                'performed by the subject for a subject reference. Use null for inapplicable fields '
                'or when the precise property/action is not in existing_entities. Do not substitute '
                'a related process for its inputs or objects. Resolve meaning from the source, not '
                'from the vocabulary alone. Actions may have noun-phrase canonical names; a '
                'nominalization of the same activity is a valid action, not automatically its result. '
                'Use expression to distinguish the specific occurrence. Ownership includes a property '
                'or resource attributed to the entity, not only legal ownership. An actor can exhibit '
                'a capability without intending or initiating it. '
                'Both an actor and its action can be present simultaneously.',
                dict(source=unit['text'], focus_sentence=focus, mention=reference.mention,
                     expression=reference.expression,
                     existing_entities=list(by_label)), links_schema,
                f"references_{unit['id']}_{attempt}_binding_{index}", deliberate=False)
            actual = {key:getattr(reference, key) for key in links_schema.model_fields}
            if actual != links.model_dump():
                confirmation = ask('graph_reference_binding_verifier',
                    'Independently assess BOTH proposed bindings of ONE reference IN focus_sentence. '
                    'Other source sentences may identify its antecedent, but must not supply a '
                    'different property or action. '
                    'The antecedent must be the source-supported owner/actor. owned_property must '
                    'name the actual possessed object/property, never a related process. '
                    'performed_action must be the action performed by that subject. '
                    'Canonical graph entities use noun phrases: a nominalization of the same activity '
                    'is a valid action reference. Reject a real change in referent, not noun-versus-verb grammar. '
                    'Ownership includes a source-attributed property or associated resource, not only legal '
                    'ownership. Acting or exhibiting a capability does not require intention or initiation. '
                    'Null is correct for an inapplicable role or a property/action absent from '
                    'existing_entities; do not force a related node instead. Check also that the '
                    'resolved meaning agrees with the source and the proposed binding. Reject '
                    'invented, wrong or missing available identities, and state the concrete error.',
                    dict(source=unit['text'], focus_sentence=focus, mention=reference.mention,
                         expression=reference.expression,
                         resolved_meaning=reference.resolved_meaning, existing_entities=list(by_label),
                         original=actual, alternative=links.model_dump()), BindingComparison,
                    f"references_{unit['id']}_{attempt}_binding_{index}_verify", deliberate=False)
                if confirmation.alternative_valid and not confirmation.original_valid:
                    for key, value in links.model_dump().items():
                        setattr(reference, key, value)
                elif not (confirmation.original_valid and not confirmation.alternative_valid):
                    link_issues.append(dict(mention=reference.mention, proposed=actual,
                        independent_binding=links.model_dump(), review=confirmation.model_dump()))
        if checked.valid and not checked.issues and not link_issues:
            validate(proposed)
            resolved = bind(proposed)
            return resolved.model_dump()
        feedback = dict(**checked.model_dump(), binding_disagreements=link_issues)
    raise ValueError('Source references or clause scope remain unresolved: ' + str(feedback))


def reference_obligations(edge, references, nodes):
    """Check verified identity links against actual scoped roles, not model approval booleans."""
    issues = []
    for binding in references:
        antecedent = binding.get('antecedent_node')
        if binding.get('ambiguous') or not antecedent:
            continue
        for field, role in [('owned_property_node', 'owner'), ('performed_action_node', 'agent')]:
            referent = binding.get(field)
            if not referent:
                continue
            for side in ('source', 'target'):
                if edge[side] != referent:
                    continue
                if not any(p['node'] == antecedent and p['scope'] == side and p['role'] == role
                           for p in edge.get('participants', [])):
                    issues.append(f"The {side} {nodes[referent]['label']} needs its source-supported {role} "
                                  f"{nodes[antecedent]['label']} as an explicit participant with scope={side}. "
                                  f"Reference evidence: {binding['evidence']}")
    return list(dict.fromkeys(issues))


def resolve_graph_context(unit, ask, attempts, nodes):
    """Resolve source roles one existing entity at a time, without guessing node IDs.

    The focus entity is supplied by code. Two independent source readings must
    agree; a disagreement needs a separate source-based adjudication. This avoids
    asking a small model to find pronouns, classify activities and map multiple
    opaque identities in the same response.
    """
    candidates = {node['label']: node['id'] for node in nodes}
    if len(candidates) != len(nodes):
        raise ValueError('Source role candidates require unique canonical labels')
    choice = Literal[tuple(candidates)] | None if candidates else type(None)
    schema = create_model('EntitySourceRoles', __base__=Record,
        owned_by=(choice, Field(description='Which OTHER entity does focus_entity belong to? Return its canonical name, not focus_entity.')),
        performed_by=(choice, Field(description='Which OTHER entity performs or exhibits the activity named focus_entity? Return its canonical name.')),
        ambiguous=(bool, ...),
        reason=(str, Field(min_length=1, max_length=setting('text', 'question_chars'))))
    references = []
    for node in nodes:
        if node.get('origin') == 'background':
            continue
        payload = dict(source=unit['text'], existing_entities=list(candidates), focus_entity=node['label'])
        feedback = None
        def validate_binding(result):
            if result.ambiguous and (result.owned_by is not None or result.performed_by is not None):
                raise ValueError('Do not assign an owner or actor to an ambiguous reference')
            if node['label'] in {result.owned_by, result.performed_by}:
                raise ValueError('An entity cannot be its own owner or the actor of itself')
        for attempt in range(attempts):
            decisions = []
            for role in ('graph_entity_context', 'graph_entity_context_check'):
                decision = ask(role,
                    ('Independently look for an omitted or wrongly attributed owner/actor in the source, then return the complete roles. '
                     if role.endswith('_check') else 'Resolve the roles explicitly attributed by the source. ') +
                    'Resolve source-attributed roles for ONLY focus_entity. owned_by names the OTHER entity '
                    'that owns focus_entity as its property or associated resource. performed_by names the OTHER entity performing '
                    'or exhibiting the activity/capability NAMED BY focus_entity; intention is not required. '
                    'An entity changing, using or enabling focus_entity does not thereby perform focus_entity. '
                    'A property, resource or result is not an activity: its performed_by must be null. Select canonical '
                    'names from existing_entities. A process is not automatically the owner of its '
                    'affected property. Resolve pronouns from the source. Use null for a role that is '
                    'inapplicable or not specified; never fill a role from general knowledge. '
                    'Do not require legal ownership. Noun phrases can name activities. Set ambiguous '
                    'when the source does not distinguish plausible referents, with both roles null. '
                    'A possessive reference explicitly attributes ownership; do not require a separate owns verb. '
                    'The supplied source is the evidence; briefly explain how it supports each assigned role. '
                    'This checks one entity, not every entity mentioned in that quotation.',
                    dict(**payload, correction_needed=feedback), schema,
                    f"entity_context_{unit['id']}_{node['id']}_{attempt}_{role}",
                    validator=validate_binding, deliberate=False)
                decisions.append(decision)
            left, right = decisions
            keys = ('owned_by', 'performed_by', 'ambiguous')
            if all(getattr(left, key) == getattr(right, key) for key in keys):
                approved = left
            else:
                comparison = ask('graph_entity_context_adjudicator',
                    'Independently check both source-role interpretations for focus_entity. '
                    'Which interpretation preserves its source-supported owner and/or actor? '
                    'The actor may exhibit an activity or capability without intention. Ownership '
                    'must perform the activity named by focus_entity, not an action affecting that entity. '
                    'Properties, resources and results require performed_by=null. Ownership means a property '
                    'or resource attributed to an entity, not necessarily legal '
                    'possession. Do not confuse the method affecting a property with its owner. '
                    'Null is required for inapplicable, unstated, or ambiguous roles. Judge each '
                    'interpretation on the source, not its confidence or wording.',
                    dict(**payload, original=left.model_dump(), alternative=right.model_dump()),
                    BindingComparison, f"entity_context_{unit['id']}_{node['id']}_{attempt}_review",
                    deliberate=False)
                approved = (left if comparison.original_valid and not comparison.alternative_valid else
                            right if comparison.alternative_valid and not comparison.original_valid else None)
                feedback = dict(original=left.model_dump(), alternative=right.model_dump(), review=comparison.model_dump())
            if approved is not None:
                validate_binding(approved)
                for field, target in (('owned_by', 'owned_property_node'), ('performed_by', 'performed_action_node')):
                    entity = getattr(approved, field)
                    if entity is not None:
                        references.append(dict(mention=node['label'], expression=None, antecedent=entity,
                            antecedent_node=candidates[entity], resolved_meaning=approved.reason,
                            evidence=unit['text'], ambiguous=False, **{target:node['id']}))
                if approved.ambiguous:
                    references.append(dict(mention=node['label'], antecedent=None, antecedent_node=None,
                        resolved_meaning=approved.reason, evidence=unit['text'], ambiguous=True))
                break
        else:
            raise ValueError('Source entity roles remain unresolved: ' + str(feedback))
    return dict(references=references)


def revision_view(assertions, revision):
    """Show the actual directed claims after replacement, without source quotations."""
    removed = set(revision.remove_ids)
    replacements = [dict(id=f'replacement_{i}', source=f.source.label,
        source_definition=f.source.definition, target=f.target.label,
        target_definition=f.target.definition, label=f.relation, definition=f.definition,
        conditions=f.conditions, modality=f.modality, origin='document')
        for i, f in enumerate(revision.facts)]
    for row, fact in zip(replacements, revision.facts):
        row.update(purpose=fact.purpose, timing=fact.timing,
                   participants=[dict(role=p.role, scope=p.scope, entity=p.entity.label) for p in fact.participants])
    return dict(removed_assertions=[e for e in assertions if e['id'] in removed],
        resulting_assertions=[e for e in assertions if e['id'] not in removed] + replacements)


class AliasReview(Record):
    same_concept: bool
    same_scope: bool
    distinction: str | None
    reason: str = Field(min_length=1, max_length=setting('text', 'short_explanation_chars'))


def fingerprint(graph):
    value = {key: graph.get(key) for key in ('nodes', 'edges', 'relation_registry', 'provenance')}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def structural_issues(graph):
    issues = []
    nodes = graph.get('nodes', [])
    edges = graph.get('edges', [])
    ids = [n['id'] for n in nodes]
    if len(ids) != len(set(ids)):
        issues.append('Duplicate node IDs')
    names = [concept_key(n['label']) for n in nodes]
    if len(names) != len(set(names)):
        issues.append('Duplicate canonical concept names')
    if len({e['id'] for e in edges}) != len(edges):
        issues.append('Duplicate edge IDs')
    contracts = {r['key']: r['definition'] for r in graph.get('relation_registry', [])}
    quality = graph.get('quality', {})
    limits = quality.get('format_limits')
    if limits is None:
        # These are historical schema constraints, not current workload policy.
        limits = (dict(label_chars=90, predicate_chars=32, predicate_words=3)
                  if quality.get('version') in {1, 2, 3} else
                  dict(label_chars=setting('text', 'graph_label_chars'),
                       predicate_chars=setting('labels', 'predicate_chars'),
                       predicate_words=setting('labels', 'predicate_words')))
    key_pattern = rf"^[a-z][a-z0-9]*(?:_[a-z0-9]+){{0,{limits['predicate_words']-1}}}$"
    for n in nodes:
        if not n.get('definition', '').strip() or len(n['label']) > limits['label_chars']:
            issues.append(f"{n['id']}: missing definition or oversized label")
    for e in edges:
        if e['source'] not in ids or e['target'] not in ids:
            issues.append(f"{e['id']}: dangling endpoint")
        if not re.fullmatch(key_pattern, e['label']) or len(e['label']) > limits['predicate_chars']:
            issues.append(f"{e['id']}: relation exceeds configured predicate format limits")
        if contracts.get(e['label']) != e.get('definition'):
            issues.append(f"{e['id']}: conflicting relation contract")
        for participant in e.get('participants', []):
            if participant.get('node') not in ids:
                issues.append(f"{e['id']}: dangling participant")
            if participant.get('scope') not in {'source', 'target', 'assertion', 'purpose'}:
                issues.append(f"{e['id']}: invalid participant scope")
            if participant.get('role') not in Participant.model_fields['role'].annotation.__args__:
                issues.append(f"{e['id']}: invalid participant role")
    return issues


def require_quality(graph, *, required=False):
    """Legacy runs remain inspectable; reviewed runs cannot bypass or stale the gate."""
    quality = graph.get('quality')
    if quality is None and not required:
        return
    if not quality or quality.get('version') not in {1, 2, 3, VERSION} or quality.get('status') != 'passed':
        raise ValueError('Graph quality review is missing or incomplete; refine the saved graph first')
    if quality.get('sha256') != fingerprint(graph):
        raise ValueError('Graph changed after quality review; refine it again before opening')
    problems = structural_issues(graph)
    if problems:
        raise ValueError('Graph quality gate: ' + '; '.join(problems))


def exact_ids(rows, expected):
    ids = [r.id for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        raise ValueError('Return exactly one decision for every supplied ID')


def refine_graph(original, models, trace, *, policy=None):
    from .graph_view import canonicalize_graph, concept_id
    policy = policy or ReviewPolicy(candidate_limit=getattr(models, 'identity_candidates', None))
    graph = copy.deepcopy(original)
    graph.pop('quality', None)
    report = dict(version=VERSION, policy=asdict(policy), status='running', nodes=[], aliases=[], relationships=[], role_checks=[], mentions=[], source_repairs=[],
                  excluded_background=[], unresolved_attachments=[], errors=[],
                  scope='Source fidelity and model semantic review; not independent factual verification')
    trace.save('artifacts/graph_before_review.json', original)

    def save():
        trace.save('artifacts/graph_quality.json', report)

    exhausted_roles = set()

    def ask(*args, deliberate=None, **kwargs):
        # Semantic review benefits from deliberation even when extraction uses
        # the faster mode. Record the effective setting in the policy and each
        # model request; restore the caller's setting even when a request fails.
        if not hasattr(models, 'think'):
            return models.ask(*args, **kwargs)
        previous = models.think
        previous_options = dict(models.options) if hasattr(models, 'options') else None
        try:
            role = args[0]
            if deliberate is None:
                deliberate = role in {'graph_node_repair_verifier',
                    'graph_background_challenge', 'graph_source_coverage',
                    'graph_source_repair', 'graph_source_repair_verifier', 'graph_source_fact_verifier', 'graph_final_reviewer'}
            models.think = (policy.reasoning and deliberate) or previous
            if models.think and policy.reasoning_fallback and role in exhausted_roles:
                entry = dict(role=role, entity_id=args[4], mode='direct_structured_check',
                    reason='An earlier reasoning request for this role exhausted its budget in this review.',
                    criteria_unchanged=True, reasoning_attempted=False)
                report.setdefault('direct_fallbacks', []).append(entry)
                trace.emit('graph.review_mode_fallback', **entry)
                save()
                models.think = False
            if models.think and previous_options is not None:
                # Conservative UTF-8 size estimate leaves room for the input;
                # exact token counts are recorded in the model response trace.
                prompt_tokens = estimated_tokens(args[1]) + estimated_tokens(args[2]) + estimated_tokens(args[3].model_json_schema())
                available = models.options['num_ctx'] - prompt_tokens - setting('model', 'prompt_reserve_tokens')
                if available <= 0:
                    raise OutputLimitError('Review input leaves too little output space; reduce review batch sizes')
                models.options['num_predict'] = min(policy.reasoning_output_tokens, available)
            try:
                return models.ask(*args, **kwargs)
            except OutputLimitError as exc:
                source_check = role in {'graph_node_repair_verifier', 'graph_source_coverage',
                    'graph_source_repair', 'graph_source_repair_verifier', 'graph_source_fact_verifier',
                    'graph_final_reviewer', 'graph_background_challenge', 'graph_fact_reviewer',
                    'graph_reference_resolver', 'graph_reference_verifier'}
                if not models.think or not policy.reasoning_fallback or not source_check:
                    raise
                entry = dict(role=role, entity_id=args[4], reason=str(exc),
                    mode='direct_structured_check', criteria_unchanged=True, reasoning_attempted=True)
                exhausted_roles.add(role)
                report.setdefault('direct_fallbacks', []).append(entry)
                trace.emit('graph.review_mode_fallback', **entry)
                save()
                models.think = False
                if previous_options is not None:
                    models.options['num_predict'] = min(previous_options['num_predict'], models.options['num_predict'])
                return models.ask(*args, **kwargs)
        finally:
            models.think = previous
            if previous_options is not None:
                models.options.clear()
                models.options.update(previous_options)

    def read_displayed_fact(fact, identifier):
        return ask('graph_displayed_fact_reader',
            'Read this displayed directed arrow as ordinary language. Explain the claim actually '
            'communicated by its endpoint labels, short predicate, conditions and modality. '
            'Do not repair its wording or insert missing participants, goals, circumstances, '
            'uncertainty or negation. Endpoint definitions explain referents; they do not supply '
            'missing conditions on the arrow. Read the short predicate literally: TARGET must '
            'fill the role implied by that predicate. Abstract concepts, qualities and processes '
            'are valid participants. Include supplied conditions and modality in the paraphrase. '
            'Your task is interpretation, not a grammatical or factual judgment. '
            'You have no source quotation or predicate contract; do not guess what an author intended. ' + CONTEXT_POLICY,
            dict(displayed=f'{fact.source.label} --{fact.relation.replace("_", " ")}--> {fact.target.label}',
                source=fact.source.model_dump(), target=fact.target.model_dump(),
                conditions=fact.conditions, modality=fact.modality, purpose=fact.purpose, timing=fact.timing,
                participants=[p.model_dump() for p in fact.participants]), DisplayedReading, identifier,
            deliberate=False)

    try:
        nodes = {n['id']: dict(n) for n in graph['nodes']}
        if len(nodes) != len(graph['nodes']):
            raise ValueError('Duplicate input node IDs')
        if not graph['edges']:
            raise ValueError('No relationships available for a usable reference graph')
        redirects = {}
        def collapsed_relationship(mapping):
            def resolve(key):
                while mapping.get(key, key) != key:
                    key = mapping[key]
                return key
            return next((e['id'] for e in graph['edges'] if e['source'] != e['target']
                         and resolve(e['source']) == resolve(e['target'])), None)
        # Every node gets a decision and a separate verification. Earlier retained
        # nodes are the only merge targets, preventing cycles and silent collisions.
        source_text = graph.get('provenance', {}).get('text', '')
        reviewed_count = 0
        for offset, focus in enumerate(budgeted_pages(list(nodes.values()), models, size=policy.node_batch_size, schema=NodeDecision)):
            retained = nearest_nodes(focus, [n for k, n in nodes.items() if k in redirects and redirects[k] == k], policy.candidate_limit)
            payload = dict(nodes=focus, existing=retained, source=node_context(focus, graph, policy.candidate_limit))
            allowed_id = Literal[tuple(n['id'] for n in focus)]
            merge_type = Literal[tuple(n['id'] for n in retained)] | None if retained else type(None)
            decision_type = create_model('ScopedNodeDecision', __base__=NodeDecision,
                                         id=(allowed_id, ...), merge_into=(merge_type, ...))
            plan_type = create_model('ScopedNodePlan', __base__=NodePlan,
                nodes=(list[decision_type], Field(min_length=len(focus), max_length=len(focus))))
            verdict_type = create_model('ScopedNodeVerdict', __base__=NodeVerdict, id=(allowed_id, ...))
            review_type = create_model('ScopedNodeReview', __base__=NodeReview,
                nodes=(list[verdict_type], Field(min_length=len(focus), max_length=len(focus))))
            def validate_nodes(result):
                exact_ids(result.nodes, [n['id'] for n in focus])
                for row in result.nodes:
                    if row.merge_into is not None and row.merge_into not in {n['id'] for n in retained}:
                        raise ValueError('Merge only into an existing retained ID; otherwise return null')
                proposed_redirects = dict(redirects, **{r.id:r.merge_into or r.id for r in result.nodes})
                collapsed = collapsed_relationship(proposed_redirects)
                if collapsed:
                    raise ValueError(f'Merge collapses the distinct participants of {collapsed} into a self-link. Keep their distinct source roles and labels.')
                kept_names = [concept_key(n['label']) for k,n in nodes.items() if redirects.get(k)==k]
                kept_names += [concept_key(r.label) for r in result.nodes if r.merge_into is None]
                if len(set(kept_names)) != len(kept_names):
                    raise ValueError('Renaming duplicates another retained node without a verified merge. Preserve distinct source labels or propose a valid merge.')
            node_failure = None
            verified_nodes = {}
            for node_attempt in range(policy.repair_attempts):
                try:
                    plan = ask('graph_node_editor',
                    'Edit each supplied node IN PLACE using its original ID; do not insert a second copy. '
                    'merge_into=null retains that node with the edited label and definition. '
                    'Return exactly one decision per node in nodes. existing contains OTHER nodes and is read-only context: '
                    'NEVER return decisions for those IDs. Set merge_into explicitly to an existing ID '
                    'only for true identity, otherwise null. Use concise noun phrases and a short definition. '
                    'Preserve meaning and specificity; do not turn a property into a change of that property. '
                    'Merge only truly interchangeable concepts at the same scope into an existing ID. '
                    'Definition wording alone is not a distinction. A process and its object remain distinct. '
                    'A whole and its component, a function and its output, and an object and an action '
                    'on that object are not identical merely because they participate in the same claim. '
                    'Rewrite inherited definitions when their purpose or scope disagrees with the source. '
                    'Do not narrow a broad source concept to a subtype or add unstated restrictions. '
                    'Do not invent facts in definitions or copy an entire source sentence. '
                    'Define the referent in one concise phrase or sentence, not its surrounding paragraph. '
                    'Keep individual actions and relationships on edges, not in the definition.',
                    dict(**payload, correction_needed=node_failure), plan_type, f'nodes_{offset}_{node_attempt}', validator=validate_nodes)
                except ModelResponseError as exc:
                    node_failure = dict(error=str(exc))
                    break
                plan.nodes = [verified_nodes.get(row.id, row) for row in plan.nodes]
                merge_targets = {row.merge_into for row in plan.nodes if row.merge_into}
                verification_payload = dict(source=payload['source'],
                    nodes=[dict(id=n['id'], original_label=n['label']) for n in focus],
                    existing=[n for n in retained if n['id'] in merge_targets])
                try:
                    review = ask('graph_node_reviewer',
                    'These proposals UPDATE existing nodes in place by ID; they are not new insertions. '
                    'merge_into=null retains that same node and does NOT create a duplicate. Never demand '
                    'a merge into the node itself. Only supplied existing targets are possible other nodes. '
                    'Use the source passage as the authority; original definitions can be wrong or incomplete. '
                    'Definitions may explain information actually supplied by the source. Independently '
                    'verify the proposed concept scope: do not accept an added constraint or subtype '
                    'that excludes cases the source allows. '
                    'Check that names and definitions are concise, coherent and do not add unsupported facts. '
                    'A merge must preserve the same referent and scope; properties, changes and measurements '
                    'are distinct unless the actual definitions clearly denote the same thing. Do not approve '
                    'a merge merely because concepts are related. merge_into=null is valid when the '
                    'concept is distinct; there is no requirement to find a matching existing node. '
                    'A component is not its containing whole; a function is not its output; an action '
                    'is not its affected object. A shared role does not prove identity. Reject only a '
                    'concrete semantic defect, not stylistic alternatives or a merely possible merge. '
                    'Give a complete, concise reason consistent with the valid boolean.',
                    dict(**verification_payload, proposed=dict(nodes=[r.model_dump(exclude={'reason'}) for r in plan.nodes])),
                    review_type, f'nodes_{offset}_{node_attempt}_review',
                    validator=lambda result: exact_ids(result.nodes, [n['id'] for n in focus]))
                except ModelResponseError as exc:
                    node_failure = dict(error=str(exc))
                    break
                report['nodes'].append(dict(proposal=plan.model_dump(), review=review.model_dump()))
                for row, verdict in ((row, next(v for v in review.nodes if v.id == row.id)) for row in plan.nodes):
                    if verdict.valid:
                        verified_nodes[row.id] = row
                save()
                if len(verified_nodes) == len(focus):
                    break
                node_failure = review.model_dump()
            if len(verified_nodes) < len(focus):
                # A failed batch can repeatedly conflate neighboring concepts.
                # Isolate only its unresolved nodes, forbid an unverified merge,
                # and require a fresh source-based edit and separate verification.
                for node in focus:
                    if node['id'] in verified_nodes:
                        continue
                    isolated_type = create_model('IsolatedNodeDecision', __base__=NodeDecision,
                        id=(Literal[node['id']], ...), merge_into=(type(None), ...),
                        label=(Literal[node['label']] if len(node['label']) <= setting('text', 'graph_label_chars') else str,
                               Field(min_length=1, max_length=setting('text', 'graph_label_chars'))))
                    isolated_plan_type = create_model('IsolatedNodePlan', __base__=NodePlan,
                        nodes=(list[isolated_type], Field(min_length=1, max_length=1)))
                    isolated_verdict_type = create_model('IsolatedNodeVerdict', __base__=NodeVerdict,
                        id=(Literal[node['id']], ...))
                    isolated_review_type = create_model('IsolatedNodeReview', __base__=NodeReview,
                        nodes=(list[isolated_verdict_type], Field(min_length=1, max_length=1)))
                    context = dict(node=node, source=node_context([node], graph, policy.candidate_limit))
                    failure = node_failure
                    for retry in range(policy.repair_attempts):
                        repaired = ask('graph_node_repair',
                            'Edit this one node in place, retaining its original ID and label. '
                            'Define the concept accurately. Keep it separate: merge_into must be null. '
                            'The original definition may be wrong. Use the actual source text as authority '
                            'when supplied; otherwise give a conservative definition of the named concept. '
                            'Do not substitute its containing whole, output, actor, process or affected object. '
                            'Do not narrow it to an unstated subtype. Fix the concrete defect in the feedback.',
                            dict(**context, correction_needed=failure), isolated_plan_type,
                            f"node_{node['id']}_{retry}")
                        checked = ask('graph_node_repair_verifier',
                            'Check this in-place update of a single concept against the supplied source text. '
                            'This replaces its definition; it does not insert a duplicate node. '
                            'The original definition is fallible; source-supported corrections are allowed. '
                            'No merge is proposed. Is the proposed label and definition accurate, coherent '
                            'and at the source scope? Reject unsupported constraints or a changed referent. '
                            'A definition may explain the concept rather than repeat its name. '
                            'For a background concept without a source quote, check its ordinary meaning. '
                            'Report only a concrete semantic defect, not stylistic preference.',
                            dict(**context, proposed=dict(nodes=[r.model_dump(exclude={'reason'}) for r in repaired.nodes])), isolated_review_type,
                            f"node_{node['id']}_{retry}_review")
                        report['nodes'].append(dict(stage='isolated_repair', proposal=repaired.model_dump(),
                            review=checked.model_dump()))
                        save()
                        if checked.nodes[0].valid:
                            verified_nodes[node['id']] = repaired.nodes[0]
                            break
                        failure = checked.model_dump()
                    else:
                        raise ValueError('Node review unresolved after isolated repair: ' + str(failure))
                plan = NodePlan(nodes=[verified_nodes[node['id']] for node in focus])
            for row in plan.nodes:
                redirects[row.id] = row.merge_into or row.id
                if row.merge_into is None:
                    nodes[row.id].update(label=concept_key(row.label), definition=row.definition)
                elif nodes[row.id].get('origin') == 'document':
                    nodes[row.merge_into]['origin'] = 'document'
            reviewed_count += len(focus)
            print(f'  Reviewed concepts {reviewed_count}/{len(nodes)}', flush=True)

        # Similar wording only selects a pair for review; it never establishes
        # identity. This catches near-duplicate definitions overlooked in a batch.
        retained_ids = [key for key in nodes if redirects[key] == key]
        for pos, key in enumerate(retained_ids):
            candidates = nearest_nodes([nodes[key]], [nodes[k] for k in retained_ids[:pos]], policy.candidate_limit)
            for candidate in candidates:
                earlier = candidate['id']
                if redirects[earlier] != earlier or redirects[key] != key:
                    continue
                left, right = nodes[earlier], nodes[key]
                if collapsed_relationship(dict(redirects, **{key:earlier})):
                    trace.emit('graph.identity_merge_blocked', entity_id=key, target=earlier,
                               reason='Merging connected participants would create a self-link')
                    continue
                similarity = SequenceMatcher(None, left['definition'].casefold(), right['definition'].casefold()).ratio()
                if similarity < policy.alias_similarity:
                    continue
                pair = dict(first=left, second=right)
                checks = []
                for stage in ('identity', 'verification'):
                    result = ask('graph_alias_' + stage,
                        ('Try to disprove identity by finding a concrete referential difference. '
                         if stage == 'verification' else 'Assess whether these are redundant concepts. ') +
                        'Compare the actual referents of these two concept definitions. Are they '
                        'interchangeable at the same scope? Distinguish a property from its measurement '
                        'ONLY when a definition actually denotes a metric or measurement. Do not invent '
                        'a measurement distinction when both definitions describe the same property. '
                        'Synonymous ordinary wording does not establish '
                        'a distinction. Conversely a process is not its input, outcome, or reduction. '
                        'State a concrete referential distinction, or null if there is none. Similarity '
                        'alone is not equivalence. Decide independently of any other review.',
                        pair, AliasReview, f'alias_{earlier}_{key}_{stage}')
                    checks.append(result)
                report['aliases'].append(dict(pair=[earlier,key], reviews=[r.model_dump() for r in checks]))
                save()
                if all(r.same_concept and r.same_scope and not r.distinction for r in checks):
                    redirects[key] = earlier
                    for alias, target in list(redirects.items()):
                        if target == key:
                            redirects[alias] = earlier
                    if right.get('origin') == 'document':
                        left['origin'] = 'document'

        contracts = dict(CONTRACTS)
        new_nodes = {}
        for key, node in nodes.items():
            if redirects[key] == key:
                identifier = concept_id(node['label'])
                if identifier in new_nodes:
                    raise ValueError('Renaming collided without an explicit verified merge')
                new_nodes[identifier] = dict(node, id=identifier)
        accepted = []
        source_contexts = {u['id']: resolve_graph_context(u, ask, policy.repair_attempts, list(new_nodes.values())) for u in source_units(graph)}
        report['source_references'] = source_contexts
        save()

        def facts_for(item, identifier):
            origin = item['origin']
            available = [item['source'], item['target']] if origin == 'document' else list(new_nodes.values())
            if origin == 'background':
                focus = concept_key(item.get('intended_fact') or '') if item.get('intended_fact') else ''
                available = [n for n in new_nodes.values() if n['label'] in focus or
                             n['label'] in {item['source']['label'], item['target']['label']}]
            plan_schema = SingleFactPlan
            if origin == 'document':
                # A wrong extracted endpoint can be repaired, but the reviewer
                # must verify the same source assertion rather than a nearby one.
                plan_schema = create_model('DocumentFactPlan', __base__=FactPlan,
                    facts=(list[Fact], Field(min_length=1, max_length=1)))
            payload = dict(original=item, existing_nodes=[{k:n[k] for k in ('label','definition')} for n in available],
                           relation_contracts=contracts)
            if origin == 'document':
                payload['source_context'] = item.get('source_context', item.get('evidence'))
                payload['resolved_source_context'] = item.get('resolved_source_context')
                payload['existing_nodes'] = [{k:n[k] for k in ('label','definition')} for n in new_nodes.values()]
            failure = None
            rejected_facts = None
            for attempt in range(policy.repair_attempts):
                def validate_plan(plan):
                    for fact in plan.facts:
                        for endpoint in fact_endpoints(fact):
                            known = new_nodes.get(concept_id(endpoint.label))
                            if known:
                                endpoint.label = known['label']
                                endpoint.definition = known['definition']
                        if fact.relation in contracts:
                            # The registry owns established meanings. Verify the
                            # canonical contract, not the model's transcription.
                            fact.definition = contracts[fact.relation]
                        if origin == 'document':
                            if fact.evidence is None:
                                fact.evidence = item.get('evidence')
                            if fact.conditions is None and item.get('conditions'):
                                fact.conditions = item['conditions']
                            if fact.modality is None and item.get('modality'):
                                fact.modality = item['modality']
                        if fact.source.label == fact.target.label:
                            raise ValueError('Do not introduce self-links')
                        if origin == 'document' and (not fact.evidence or fact.evidence not in item.get('evidence', '')):
                            raise ValueError('Document facts require an exact continuous quote from the supplied evidence')
                        if fact.anchor and (not fact.evidence or fact.anchor not in fact.evidence):
                            raise ValueError('The assertion ordering anchor must occur exactly in its evidence')
                        if fact.conditions and fact.conditions in {fact.purpose, fact.timing}:
                            fact.conditions = None
                    if plan.facts and rejected_facts == [f.model_dump(exclude={'evidence'}) for f in plan.facts]:
                        raise ValueError('semantic review unresolved: the repair repeats the rejected assertion. Changing only a quote or explanation does not repair graph content. Change the actual predicate, endpoints or scope to resolve the feedback.')
                    return plan
                # Review an already concise assertion before asking an editor to
                # rewrite it. Unnecessary rewriting can substitute another claim
                # from the same quote. The original still has to pass every check.
                keep_candidate = (origin == 'background' and attempt == 0 and item.get('definition')
                                  and re.fullmatch(SHORT_KEY, item.get('label', ''))
                                  and len(item['label']) <= setting('labels', 'predicate_chars')
                                  and concept_key(item['source']['label']) != concept_key(item['target']['label']))
                if keep_candidate:
                    draft = plan_schema.model_validate(dict(facts=[dict(
                        source={k:item['source'][k] for k in ('label','definition')},
                        target={k:item['target'][k] for k in ('label','definition')},
                        relation=item['label'], definition=item['definition'],
                        conditions=item.get('conditions'), modality=item.get('modality'),
                        evidence=item.get('evidence'))], reason='Verify the existing concise assertion before rewriting.'))
                else:
                    draft = ask('graph_fact_editor',
                    f"Repair the supplied graph assertion using short reusable predicates: at most {setting('labels', 'predicate_words')} words, "
                    f"at most {setting('labels', 'predicate_chars')} characters, snake_case. Prefer an existing contract and copy its definition exactly. "
                    'New predicates are allowed when existing contracts do not express the claim. '
                    'Keep a correct original predicate and its participants; do not substitute a nearby claim '
                    'merely to fit the supplied contract list. Apply the correction feedback to the actual fact. '
                    'If a label assigns the wrong role to an endpoint, choose a different short predicate '
                    'or correct the endpoint. Rewriting only its definition or explanation cannot fix '
                    'a misleading displayed arrow. '
                    'Keep endpoint names concise; reuse existing nodes only for identical concepts. '
                    'Read the actual endpoints literally: a property is not its reduction or constraint. '
                    'For a claim about reducing X, use a standalone change concept such as reduction in X '
                    'if needed; never hide this semantic change in conditions. Conditions are circumstances. '
                    'Do not encode a whole explanation, endpoint names or a three-party event in a predicate. '
                    'Use supports for helping or contributing, not enables when only assistance is stated. '
                    'Return exactly one repaired assertion (or omit an unsound '
                    'background assertion). Do not extract other facts from a quote that supports several '
                    'relationships. For document facts preserve the full '
                    'focused original claim. Use the smallest exact continuous evidence span supporting '
                    'this focused assertion; do not include other coordinated assertions unnecessarily. Background facts may be '
                    'qualified or omitted if unsupported or misleading; model confidence is not evidence. '
                    'Do not infer additional properties, exclusivity, or mechanisms from a weaker assertion. '
                    'Preserve polarity and degree of certainty from the intended claim; omit an unsound '
                    'background claim instead of asserting its opposite. '
                    'Use resolved_source_context to retain the actual actors, owners, purpose objects and shared '
                    'time scope for THIS focused claim. Transfer required participants into semantic role references '
                    'and purpose/time into their dedicated fields. The reference analysis is not itself graph content. '
                    'Return concise reasons. ' + CONTEXT_POLICY +
                    (' For background repairs, intended_fact supplies the intended meaning; the old '
                     'endpoints may be wrong. Identify the semantic participants and direction from '
                     'the entire assertion, regardless of word order or grammatical construction. '
                     'Represent any asserted process or change explicitly, preserving its affected '
                     'object and scope. Do not substitute a related actor for the stated subject.'
                     if origin == 'background' else ''),
                    dict(**payload, correction_needed=failure), plan_schema,
                    f'{identifier}_{attempt}', validator=validate_plan)
                plan = validate_plan(draft)
                if origin == 'background' and plan.facts:
                    challenge = ask('graph_background_challenge',
                        'Try to falsify this assertion as written. Read the short arrow label literally '
                        'with the named source/target identities, predicate contract, conditions and modality. '
                        'Use entity definitions to disambiguate their meaning and domain. A contextual description '
                        'does not restrict every instance of a named mechanism to that example. '
                        'An alternative mechanism is not an instance of the named subject. A contextual use '
                        'does not claim exclusivity. A disjunction does not require both alternatives. '
                        'Before giving a counterexample, verify it is an instance of SOURCE, satisfies every '
                        'stated condition, and actually contradicts the asserted relationship. Do NOT silently repair it '
                        'or restrict a broad class to a familiar subtype. Give a concrete counterexample '
                        'or a required missing qualification when possible. Check whether the subject '
                        'really performs the action, rather than an operation on that subject doing so. '
                        'Distinguish a possible manifestation from a defining or universal behavior. '
                        'Set valid=false for a misleading label, incompatible participant roles, an '
                        'overclaim, or uncertain factual support. Return null for counterexample and '
                        'required_qualification only if neither is needed. No source citation is required. '
                        'Once a decisive counterexample or qualification is found, return it immediately. '
                        'Do not repeatedly debate the same objection. ' + CONTEXT_POLICY,
                        dict(assertions=[background_assertion(f) for f in plan.facts]),
                        BackgroundChallenge, f'{identifier}_{attempt}_challenge')
                    report.setdefault('background_challenges', []).append(dict(id=identifier, attempt=attempt,
                        proposal=plan.model_dump(), review=challenge.model_dump()))
                    save()
                    if not challenge.valid or challenge.counterexample or challenge.required_qualification:
                        adjudication = ask('graph_background_objection_review',
                            'Independently verify BOTH this background assertion and the objection against it. '
                            'A valid counterexample must satisfy the assertion\'s actual subject definition, '
                            'conditions and modality. A different mechanism or a case outside a stated condition '
                            'does not refute a qualified claim. A contextual description does not assert exclusivity. '
                            'Do not add restrictions about implementations or physical resources that the predicate '
                            'does not state. Conversely, do not dismiss a real counterexample or silently add missing '
                            'qualifications. Set assertion_supported=false if the claim remains uncertain. '
                            'A named method retains its identity: another method with a similar purpose is not '
                            'an instance of it. A claim using "or" need not use both alternatives. '
                            'Decide factual support, not stylistic preference, and explain the concrete discrepancy.',
                            dict(assertions=[background_assertion(f) for f in plan.facts],
                                 objection=challenge.model_dump()), ChallengeAssessment,
                            f'{identifier}_{attempt}_objection_review', deliberate=False)
                        report.setdefault('background_objections', []).append(dict(id=identifier, attempt=attempt,
                            objection=challenge.model_dump(), assessment=adjudication.model_dump()))
                        save()
                        if (adjudication.counterexample_applies or adjudication.qualification_needed
                                or not adjudication.assertion_supported):
                            failure = dict(objection=challenge.model_dump(), assessment=adjudication.model_dump())
                            rejected_facts = [f.model_dump(exclude={'evidence'}) for f in plan.facts]
                            continue
                        # Dismissing an invalid objection is not approval: the
                        # independent literal reading and full verifier still run.
                # Source scope is part of the fact, not optional editorial text.
                # Never let a shorter predicate erase already-recorded source
                # circumstances or modality. Review the actual retained scope.
                if origin == 'document':
                    for fact in plan.facts:
                        if item.get('conditions') and fact.conditions is None:
                            fact.conditions = item['conditions']
                        if item.get('modality') and fact.modality is None:
                            fact.modality = item['modality']
                def validate_review(result):
                    indices = [r.index for r in result.facts]
                    if sorted(indices) != list(range(len(plan.facts))):
                        raise ValueError('Review every proposed fact exactly once by zero-based index')
                readings = [read_displayed_fact(f, f'{identifier}_{attempt}_reading_{i}') for i,f in enumerate(plan.facts)]
                verdict_type = create_model('ScopedFactVerdict', __base__=FactVerdict,
                    index=(Literal[tuple(range(len(plan.facts)))], ...)) if plan.facts else FactVerdict
                review_schema = create_model('ScopedFactReview', __base__=FactReview,
                    facts=(list[verdict_type], Field(min_length=len(plan.facts), max_length=len(plan.facts))))
                review_instructions = (
                    'This is BACKGROUND explanatory knowledge, not document extraction. A source '
                    'quotation is not expected and its absence is NOT a rejection reason. Use domain '
                    'knowledge to check factual plausibility, and reject uncertain inventions, '
                    'case-specific assumptions and overclaims. Look for a concrete counterexample: '
                    'does this mechanism hold only for an unstated subtype or special case? A common '
                    'method is not every method. Distinguish a mathematical object from an operation '
                    'performed on it, and a mechanism from its actor or output. Faithful means preserving the intended '
                    'fact\'s underlying process and direction; correcting the old broken endpoints or '
                    'narrowing an overclaim with may/can is allowed. Do not demand preservation of an '
                    'erroneous original triple. Additional properties, exclusivity, mechanisms and '
                    'polarity changes need their own justification. An enabling '
                    'condition need not guarantee its outcome. omission_valid is true for a retained '
                    'sound explanation or for withholding an unsound claim.'
                    if origin == 'background' else
                    'This is DOCUMENT evidence verification. The provided exact quote must entail '
                    'the claim; co-occurrence is insufficient. Judge against the quote, not a defective '
                    'old predicate. This is one FOCUSED assertion, identified by original source_label '
                    'and target_label. The quote or paragraph may contain several different assertions. '
                    'Do NOT require this fact to express those other assertions: the mandatory final '
                    'source-coverage gate audits sentence completeness separately. Set omission_valid '
                    'true when this focused assertion is retained, even if other assertions from the '
                    'same sentence need separate edges. Preserve this focused claim and its qualifications; '
                    'do not substitute another assertion from a shared quote. A corrected endpoint '
                    'must name the actual participant in that assertion. '
                    'faithful means this focused assertion is source-faithful, not a summary of the entire quote.'
                )
                review_original = item if origin == 'background' else dict(origin='document',
                    source_label=item['source']['label'], target_label=item['target']['label'], evidence=item.get('evidence'))
                review = ask('graph_fact_reviewer',
                    'Compare the independently supplied displayed_readings with the contract and source. '
                    'These readings were made without the source quotation or contract. An explanatory '
                    'contract must not silently replace the meaning of the displayed arrow. '
                    'The reading is a fallible paraphrase: judge the actual proposed endpoints, '
                    'predicate, conditions and modality, not omissions or stylistic preferences in '
                    'that paraphrase. Abstract concepts can be valid participants. '
                    'Independently read each SOURCE relation TARGET literally. '
                    'Do not silently insert reducing, constraining, negation or an unstated participant. '
                    'Check direction, endpoint definitions, meaning and qualifications. Conditions cannot '
                    'turn a property into its reduction. Conditions and modality are part of the assertion: '
                    'do not assess a qualified claim as an absolute guarantee. Identify a concrete '
                    'discrepancy for every negative judgment; stylistic alternatives are not errors. '
                    'Check the ordinary meaning of the predicate label as well as its definition: '
                    'a short label must not reverse the participant roles, change the causal strength, '
                    'or say something different from its contract. A correct explanatory definition '
                    'cannot rescue a misleading arrow label. Judge the facts without relying on the editor reason. '
                    'The original labels identify the focused claim, not an authoritative old predicate. '
                    'The source wording determines strength; do not require other claims from a shared quote. '
                    'Compare resolved_source_context with the proposed graph fields. If it identifies an owner '
                    'or affected participant for this claim, that entity must be in the endpoints or scoped '
                    'participants; merely appearing in the source context or a node definition does not retain it. '
                    + review_instructions + CONTEXT_POLICY,
                    dict(original=review_original, source_context=payload.get('source_context'),
                         resolved_source_context=payload.get('resolved_source_context'), proposed=[f.model_dump() for f in plan.facts],
                         displayed_readings=[r.model_dump() for r in readings]),
                    review_schema, f'{identifier}_{attempt}_review', validator=validate_review,
                    deliberate=origin == 'background' or attempt > 0)
                report['relationships'].append(dict(id=identifier, attempt=attempt,
                    proposal=plan.model_dump(), displayed_readings=[r.model_dump() for r in readings], review=review.model_dump()))
                save()
                flags = ('faithful', 'supported', 'direction_valid', 'label_matches_contract', 'endpoints_valid', 'qualifications_preserved')
                if review.omission_valid and all(all(getattr(r, k) for k in flags) for r in review.facts):
                    if origin == 'background' and not plan.facts:
                        report['excluded_background'].append(dict(id=identifier, original=item,
                            reason=plan.reason, review=review.model_dump()))
                        save()
                    return plan.facts
                failure = review.model_dump()
                rejected_facts = [f.model_dump(exclude={'evidence'}) for f in plan.facts]
            if origin == 'background':
                report['excluded_background'].append(dict(id=identifier, original=item, review=failure,
                    reason='No verified repair; optional enrichment withheld from the reference graph'))
                save()
                return []
            raise ValueError(f'{identifier}: semantic review unresolved after repair: {failure}')

        def add_facts(facts, old, identifier):
            published_ids = set().union(*(edge_node_ids(e) for e in accepted)) if accepted else set()
            for index, fact in enumerate(facts):
                endpoint_ids = []
                for endpoint in fact_endpoints(fact):
                    name = concept_key(endpoint.label)
                    key = concept_id(name)
                    if key not in new_nodes or key not in published_ids:
                        node_origin = 'document' if old['origin']=='document' or new_nodes.get(key, {}).get('origin')=='document' else old['origin']
                        new_nodes[key] = dict(id=key, label=name, kind='concept', definition=endpoint.definition,
                                              origin=node_origin)
                    elif old['origin'] == 'document':
                        new_nodes[key]['origin'] = 'document'
                    endpoint_ids.append(key)
                    published_ids.add(key)
                contracts[fact.relation] = fact.definition
                # Historical scores and justifications belong to the audit, not a
                # corrected fact that they never evaluated.
                edge = dict(id=identifier if index == 0 else f'{identifier}_{index+1}',
                    source=endpoint_ids[0], target=endpoint_ids[1], label=fact.relation,
                    definition=fact.definition, origin=old['origin'], conditions=fact.conditions,
                    modality=fact.modality, verification_basis='quote_entailment_model_review'
                    if old['origin']=='document' else 'model_knowledge', supporting_evidence=[])
                edge.update(purpose=fact.purpose, timing=fact.timing,
                    participants=[dict(role=p.role, scope=p.scope, node=endpoint_ids[i+2])
                                  for i,p in enumerate(fact.participants)])
                if old.get('chunk_id'):
                    edge['chunk_id'] = old['chunk_id']
                if old['origin'] == 'document':
                    # Repeated quotations in different paragraphs must retain
                    # the original occurrence, rather than always using the first.
                    left, right = old.get('evidence_start'), old.get('evidence_end')
                    start = source_text.find(fact.evidence, left, right) if isinstance(left, int) and isinstance(right, int) else -1
                    if start < 0:
                        start = source_text.find(fact.evidence)
                    if start < 0:
                        raise ValueError('Reviewed document quote not found in source text')
                    edge.update(evidence=fact.evidence, evidence_start=start, evidence_end=start+len(fact.evidence))
                    edge['source_order'] = start + (fact.evidence.find(fact.anchor) if fact.anchor else 0)
                    chunks = graph.get('provenance', {}).get('chunks', [])
                    chunk = next((c for c in chunks if c['start'] <= start and start+len(fact.evidence) <= c['end']), None)
                    if chunk:
                        edge['chunk_id'] = chunk['id']
                accepted.append(edge)

        for old in graph['edges']:
            item = {k: old.get(k) for k in ('origin', 'label', 'definition', 'conditions', 'modality', 'evidence', 'intended_fact')}
            for side in ('source', 'target'):
                item[side] = nodes[redirects[old[side]]]
            if old['origin'] == 'document':
                item['source_context'] = next((u['text'] for u in source_units(graph)
                    if u['id'] == old.get('chunk_id')), old.get('evidence'))
                item['resolved_source_context'] = source_contexts.get(old.get('chunk_id'))
            try:
                proposed = facts_for(item, old['id'])
            except (ModelResponseError, ValueError) as exc:
                if old['origin'] != 'background':
                    raise
                report['excluded_background'].append(dict(id=old['id'], original=item, reason=str(exc)))
                save()
                proposed = []
            add_facts(proposed, old, old['id'])
            print(f"  Reviewed relationship {old['id']}", flush=True)

        # Recover missing assertions from their source passages below. Starting
        # from an isolated noun instead encourages invented or duplicate links.
        # Unlinked mentions stay in provenance, outside the assessable graph.
        def assemble():
            incident = set().union(*(edge_node_ids(e) for e in accepted)) if accepted else set()
            # A source mention is not a published concept definition. Keep its
            # identity in provenance; speculative descriptions remain in the
            # pre-review graph and audit rather than the reference graph.
            report['mentions'] = [{k:n[k] for k in ('id','label','origin')} for key,n in new_nodes.items()
                                  if key not in incident and n.get('origin') != 'background']
            report['excluded_concepts'] = [n for key,n in new_nodes.items() if key not in incident and n.get('origin') == 'background']
            graph.update(nodes=[n for key,n in new_nodes.items() if key in incident], edges=accepted,
                relation_registry=[dict(key=k, definition=v, symmetric=DEFAULT_RELATIONS.get(k, ('',None,False))[2],
                                        inverse=DEFAULT_RELATIONS.get(k, ('',None,False))[1]) for k,v in contracts.items()
                                   if any(e['label']==k for e in accepted)])
            graph.setdefault('provenance', {})['unlinked_mentions'] = report['mentions']
            return canonicalize_graph(graph)
        graph = assemble()
        problems = structural_issues(graph)
        if not graph['edges']:
            problems.append('No reviewed relationships remain')
        if problems:
            raise ValueError('; '.join(problems))
        # Review the actual assembled result, rather than extrapolating a graph
        # guarantee from independent local judgments. A failed final review is
        # retained for inspection, but is never available as a completed run.
        coverage_checks = []
        for unit in source_units(graph):
            repair_feedback = None
            sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', unit['text']) if s.strip()]
            for attempt in range(policy.repair_attempts + 1):
                scoped_edges = [e for e in graph['edges'] if e['origin']=='document' and
                    (e.get('chunk_id') == unit['id'] or e.get('evidence', '') in unit['text'] or unit['text'] in e.get('evidence', ''))]
                document_ids = set().union(*(edge_node_ids(e) for e in scoped_edges)) if scoped_edges else set()
                scoped_nodes = {n['id']:n for n in graph['nodes'] if n['id'] in document_ids}
                # Quotes are evidence, not the assertion represented by an edge.
                # Showing them here caused reviewers to mistake a quoted but lost
                # source claim for a claim actually encoded in the graph.
                assertions = [dict(id=e['id'], source=scoped_nodes[e['source']]['label'],
                    source_definition=scoped_nodes[e['source']]['definition'],
                    target=scoped_nodes[e['target']]['label'], target_definition=scoped_nodes[e['target']]['definition'],
                    **{k:e.get(k) for k in ('label','definition','conditions','modality','origin')},
                    **context_view(e, scoped_nodes)) for e in scoped_edges]
                context = dict(source=unit['text'], sentences=sentences, nodes=list(scoped_nodes.values()), edges=assertions)
                def validate_coverage(result):
                    if [row.index for row in result.sentences] != [0]:
                        raise ValueError('Audit every supplied source sentence exactly once by zero-based index')
                    edge_ids = {e['id'] for e in scoped_edges}
                    if not set(result.bad_edge_ids) <= edge_ids:
                        raise ValueError('Flag only supplied document edges as incorrect')
                    missing = []
                    for row in result.sentences:
                        if not row.claims and not row.no_claim_reason:
                            raise ValueError('List the sentence assertions, or explain why it makes no assertion')
                        for claim in row.claims:
                            if not set(claim.edge_ids) <= edge_ids:
                                raise ValueError('Reference only supplied edge IDs')
                            if claim.represented and not claim.edge_ids:
                                raise ValueError('A represented assertion needs at least one actual edge')
                            if not claim.represented:
                                missing.append(claim.assertion + ': ' + claim.reason)
                    result.issues = list(dict.fromkeys(result.issues + missing))
                    result.complete = result.complete and not result.issues and not result.bad_edge_ids
                sentence_checks = []
                for sentence_index, sentence in enumerate(sentences):
                    checked_sentence = ask('graph_source_coverage',
                    'Audit only the single supplied sentence, index=0. The source paragraph supplies '
                    'context; do not require claims from its other sentences in this check. '
                    'First list every explicit '
                    'assertion in that sentence, then map each assertion to actual DOCUMENT edge IDs '
                    'that express its complete meaning. A sentence can contain several assertions. '
                    'Use an empty edge_ids list and represented=false for a missing assertion. '
                    'A node mention, a loose association, or a matching word does not represent an assertion. '
                    'The source text is NOT itself graph content. Verify that every '
                    'explicit source claim is preserved with its direction, conditions and modality, '
                    'without adding unsupported claims. Check the actual participants, their roles and ownership, '
                    'purpose, timing and shared-clause scope explicitly. A generic statement about a property '
                    'does not preserve whose property it is. A purpose must remain a goal, not an achieved fact. '
                    'Context can use structured participant roles and qualifiers without extra event nodes. '
                    'Identify the exact missing or misrepresented source assertion in each issue. '
                    'Do not demand unrelated outside knowledge or stylistic changes. This check contains '
                    'document edges only. Check that node definitions do not add unsupported restrictions. '
                    'List existing wrong or unsupported edges in bad_edge_ids. A missing assertion alone '
                    'does not make already-correct edges wrong. ' + CONTEXT_POLICY,
                    dict(source=unit['text'], sentences=[sentence], edges=assertions,
                         resolved_source_context=source_contexts[unit['id']]), SourceCoverage,
                    f"source_coverage_{unit['id']}_{attempt}_sentence_{sentence_index}", validator=validate_coverage)
                    checked_sentence.sentences[0].index = sentence_index
                    sentence_checks.append(checked_sentence)
                coverage = SourceCoverage(sentences=[s for c in sentence_checks for s in c.sentences],
                    bad_edge_ids=list(dict.fromkeys(e for c in sentence_checks for e in c.bad_edge_ids)),
                    complete=all(c.complete for c in sentence_checks),
                    issues=list(dict.fromkeys(i for c in sentence_checks for i in c.issues)))
                # A core-verb match can conceal absent ownership or shared agents.
                # Check those dimensions separately, without definitions or quotes
                # inside the displayed assertion that could fill its missing roles.
                context_checks = []
                for edge, assertion in zip(scoped_edges, assertions):
                    visible = {k:v for k,v in assertion.items() if k not in {'source_definition','target_definition','definition'}}
                    context_check = ask('graph_fact_context_reviewer',
                        'Check context preservation for ONE focused graph assertion against the full source. '
                        'This is not a check of whether the main verb is plausible. Compare actual displayed '
                        'endpoints and scoped participant references with the verified pronoun/ownership bindings. '
                        'If a property belongs to a particular entity in the source, that owner must appear '
                        'explicitly on the graph assertion; the source text cannot supply it invisibly. '
                        'Similarly retain the actor of an enabled action. scope=source attaches a role to the '
                        'source node, scope=target to the target node/action, and scope=purpose to the intended goal. '
                        'Do not confuse a mechanism with the entity using it. Check purpose versus achieved '
                        'outcome, time and coordinated temporal scope, polarity and uncertainty separately. '
                        'Do not demand other assertions sharing the same sentence. Mark a dimension true when '
                        'it is preserved or genuinely inapplicable. For each false flag, state the exact missing '
                        'entity, wrong role or lost qualification. Do not infer omitted content from a definition.',
                        dict(source=unit['text'], references=source_contexts[unit['id']]['references'],
                             assertion=visible), FactContextCheck,
                        f"context_{unit['id']}_{edge['id']}_{attempt}", deliberate=False)
                    binding_issues = reference_obligations(edge, source_contexts[unit['id']]['references'], new_nodes)
                    good = all(getattr(context_check, key) for key in CONTEXT_CHECK_FLAGS) and not context_check.issues and not binding_issues
                    context_checks.append(dict(edge_id=edge['id'], **context_check.model_dump(), binding_issues=binding_issues, passed=good))
                    if not good:
                        coverage.complete = False
                        coverage.bad_edge_ids = list(dict.fromkeys(coverage.bad_edge_ids + [edge['id']]))
                        coverage.issues.extend([f"{edge['id']}: {issue}" for issue in context_check.issues + binding_issues] or
                            [f"{edge['id']}: missing context: " + ', '.join(k for k in CONTEXT_CHECK_FLAGS if not getattr(context_check,k))])
                report.setdefault('context_coverage', []).append(dict(chunk_id=unit['id'], attempt=attempt, checks=context_checks))
                save()
                if coverage.complete and not coverage.issues or attempt == policy.repair_attempts:
                    break
                missing_claims = [c.model_dump() for s in coverage.sentences for c in s.claims if not c.represented]
                allowed = set(coverage.bad_edge_ids) | {identifier for c in missing_claims for identifier in c['edge_ids']}
                revision_schema = SourceRevision
                def validate_revision(revision):
                    if not set(revision.remove_ids) <= allowed:
                        raise ValueError('Only replace edges flagged incorrect or incomplete by the coverage audit. Add missing claims without rewriting healthy edges.')
                    staged_nodes = {n['id']:{k:n[k] for k in ('label','definition')} for n in graph['nodes']}
                    for fact in revision.facts:
                        if not fact.evidence or fact.evidence not in unit['text']:
                            raise ValueError('Every recovered assertion requires an exact quote from the supplied passage')
                        if concept_key(fact.source.label) == concept_key(fact.target.label):
                            raise ValueError('Do not introduce self-links')
                        if fact.anchor and fact.anchor not in fact.evidence:
                            raise ValueError('Ordering anchor must occur exactly in the evidence')
                        for endpoint in fact_endpoints(fact):
                            key = concept_id(endpoint.label)
                            known = staged_nodes.get(key)
                            if known:
                                endpoint.label, endpoint.definition = known['label'], known['definition']
                            else:
                                staged_nodes[key] = endpoint.model_dump()
                        if fact.relation in contracts:
                            fact.definition = contracts[fact.relation]
                revision = ask('graph_source_repair',
                    'Start with missing_claims and incorrect_edges: repair those specific gaps. '
                    'Use the participants and action stated in each missing claim. Return the smallest '
                    'set of facts needed to express it, without adding associations from other sentences. '
                    'Represent an intended purpose in purpose; a goal does not assert '
                    'that the outcome is achieved. Do not decompose a purpose clause into another '
                    'factual edge asserting that outcome. '
                    'Do not resubmit healthy assertions from other sentences. New nodes and new short '
                    'predicates are allowed; the supplied registry is not a closed vocabulary. '
                    'Recover source assertions even when an earlier extraction omitted them. Return '
                    'remove_ids only for supplied edges that are wrong and need replacement, and facts '
                    'for missing or corrected assertions. Preserve the same source claims, participants, '
                    'conditions, polarity and uncertainty; never invent explanatory knowledge. Use concise '
                    'standalone concepts and short reusable predicates. An edge cannot inherit its meaning '
                    'solely from its quotation: the endpoints, predicate, conditions and modality must '
                    'express it. Choose a short predicate whose ordinary meaning matches the source '
                    'action and define its SOURCE-to-TARGET direction. Do not manufacture extra '
                    'connections for isolated mentions. ' + CONTEXT_POLICY,
                    dict(source=unit['text'], resolved_source_context=source_contexts[unit['id']], missing_claims=missing_claims,
                         incorrect_edges=[e for e in assertions if e['id'] in allowed],
                         existing_nodes=context['nodes'], issues=coverage.issues,
                         correction_needed=repair_feedback), revision_schema, f"source_repair_{unit['id']}_{attempt}",
                    validator=validate_revision)
                verdicts = []
                repair_readings = []
                for position, fact in enumerate(revision.facts):
                    reading = read_displayed_fact(fact, f"source_repair_{unit['id']}_{attempt}_reading_{position}")
                    repair_readings.append(reading)
                    verdict = ask('graph_source_fact_verifier',
                    'Independently check this single proposed source repair, index=0. Read the directed assertion literally '
                    'and compare its independently supplied displayed_reading, made without the source or '
                    'contract, against the actual source claim. Do not silently add missing qualifications. '
                    'The reading is fallible: judge the actual proposed assertion including its '
                    'conditions and modality, not defects introduced only by the paraphrase. '
                    'with its contract, endpoint definitions, conditions and modality. The exact source quote '
                    'must entail it; do not silently supply missing meaning. Check participant roles, direction, '
                    'polarity and all qualifications. The short predicate label must agree with its '
                    'contract and direction rather than relying on a definition to reverse its ordinary meaning. '
                    'faithful means preserving the source assertion. '
                    'supported means entailed by the passage, not merely plausible background knowledge. '
                    'An intended purpose does not guarantee an outcome. One clear mismatch is sufficient '
                    'to reject the assertion; report that concrete discrepancy without repeatedly '
                    'reconsidering it. Return the verdict once the decision is clear. ' + CONTEXT_POLICY,
                    dict(source=unit['text'], proposed=fact.model_dump(), displayed_reading=reading.model_dump()), FactVerdict,
                    f"source_repair_{unit['id']}_{attempt}_fact_{position}")
                    verdict.index = position
                    verdicts.append(verdict)
                facts_valid = all(all(getattr(r,k) for k in
                    ('faithful','supported','direction_valid','label_matches_contract','endpoints_valid','qualifications_preserved')) for r in verdicts)
                if facts_valid:
                    scope = ask('graph_source_repair_verifier',
                        'The proposed assertions have individually passed source entailment checks. '
                        'Check only scope and progress using resulting_assertions: this is the complete '
                        'candidate set after removing old edges and adding replacements. '
                        'removed_assertions is historical context, not part of the candidate result. '
                        'Replacing an edge does not delete a concept reused by a replacement. '
                        'Set omission_valid if the resulting assertions still express every source claim '
                        'previously expressed by the removed assertions. New IDs or equivalent predicates '
                        'are allowed; compare meanings, including conditions and modality. '
                        'Preserve previously source-supported meaning: correcting an audited overclaim, '
                        'missing owner or incorrect role is progress, not loss of a valid assertion. '
                        'Do not count other actions mentioned in a node definition as directed assertions. '
                        'Set makes_progress only if the resulting assertions resolve at least one '
                        'reported gap or incorrect claim. Report the specific lost or unresolved claim '
                        'for any negative judgment. ' + CONTEXT_POLICY,
                        dict(source=unit['text'], previous_issues=coverage.issues,
                             previously_missing_claims=[c['assertion'] for c in missing_claims],
                             **revision_view(assertions, revision)),
                        RepairScopeReview, f"source_repair_{unit['id']}_{attempt}_scope")
                else:
                    scope = RepairScopeReview(omission_valid=False, makes_progress=False,
                        reason='One or more proposed assertions failed independent source verification.')
                check = SourceRepairReview(facts=verdicts, **scope.model_dump())
                valid = check.omission_valid and check.makes_progress and all(all(getattr(r,k) for k in
                    ('faithful','supported','direction_valid','label_matches_contract','endpoints_valid','qualifications_preserved')) for r in check.facts)
                report['source_repairs'].append(dict(chunk_id=unit['id'], attempt=attempt,
                    issues=coverage.issues, proposal=revision.model_dump(), displayed_readings=[r.model_dump() for r in repair_readings],
                    review=check.model_dump(), applied=valid))
                save()
                repair_feedback = None if valid else check.model_dump()
                if valid:
                    accepted = [e for e in graph['edges'] if e['id'] not in revision.remove_ids]
                    add_facts(revision.facts, dict(origin='document', chunk_id=unit['id'],
                        evidence_start=unit.get('start'), evidence_end=unit.get('end')),
                        f"recovered_{unit['id']}_{attempt}")
                    graph = assemble()
            coverage_checks.append(dict(id=unit['id'], **coverage.model_dump()))
            save()
        problems = structural_issues(graph)
        if problems or not graph['edges']:
            raise ValueError('Recovered graph is invalid: ' + str(problems))
        report['source_coverage'] = dict(complete=all(c['complete'] and not c['issues'] for c in coverage_checks),
            issues=[issue for c in coverage_checks for issue in c['issues']], checks=coverage_checks)
        final_checks = []
        for offset, focus_edges in enumerate(budgeted_pages(graph['edges'], models, size=policy.edge_batch_size)):
            focus_ids = set().union(*(edge_node_ids(e) for e in focus_edges))
            neighbors = [e for e in graph['edges'] if e not in focus_edges and
                         edge_node_ids(e) & focus_ids]
            # Every focus edge is checked. Context is paged rather than silently
            # dropping high-degree neighbors or sending an unbounded whole graph.
            pages = list(budgeted_pages(neighbors, models, shared=focus_edges, size=policy.edge_batch_size)) or [[]]
            for page_index, page in enumerate(pages):
                review_edges = focus_edges + page
                review_ids = set().union(*(edge_node_ids(e) for e in review_edges))
                final = ask('graph_final_reviewer',
            'Audit the internal consistency of this assembled knowledge graph. Each fact already '
            'received its own evidence or background-knowledge review. Your job here is cross-fact '
            'consistency, literal direction, meaningful concept identity and duplicate concepts. '
            'Read each predicate with its conditions and modality. A property is not its reduction, '
            'and a predicate label must agree with its contract and direction in ordinary language. '
            'and a mechanism is not its use. Do not invent missing qualifiers or ignore negation. '
            'Disconnected components alone are not errors. Background edges intentionally add '
            'explanatory knowledge; their absence from a source document is not a consistency error. '
            'Source fidelity is checked separately; the original paragraph is deliberately not '
            'part of this task. Report concrete contradictions or semantic errors, not missing '
            'citations or stylistic preferences. This is not independent external verification. ' + CONTEXT_POLICY,
                    dict(nodes=[n for n in graph['nodes'] if n['id'] in review_ids],
                 edges=[{k:e.get(k) for k in ('id','source','target','label','definition','conditions','modality','origin','participants','purpose','timing')}
                        for e in review_edges]), GraphReview, f'final_graph_{offset}_{page_index}')
                final_checks.append(dict(edge_ids=[e['id'] for e in review_edges], **final.model_dump()))
        report['final_review'] = dict(consistent=all(c['consistent'] for c in final_checks),
            concepts_distinct=all(c['concepts_distinct'] for c in final_checks),
            issues=[issue for c in final_checks for issue in c['issues']],
            source_claims_preserved=report['source_coverage']['complete'], checks=final_checks,
            scope='Bounded edge batches with shared-endpoint context; not an exhaustive proof of global consistency')
        if not report['source_coverage']['complete'] or report['final_review']['issues'] or not all(
                (report['final_review']['consistent'], report['final_review']['concepts_distinct'])):
            trace.save('artifacts/graph_review_blocked.json', graph)
            raise ValueError('Final graph review unresolved: ' + str(report['final_review']) + str(report['source_coverage']))
        report.update(status='passed', input_nodes=len(original['nodes']), input_edges=len(original['edges']),
                      final_nodes=len(graph['nodes']), final_edges=len(graph['edges']), sha256=fingerprint(graph))
        graph['quality'] = dict(version=VERSION, status='passed', sha256=report['sha256'], scope=report['scope'],
                               format_limits=dict(label_chars=setting('text', 'graph_label_chars'),
                                                  predicate_chars=setting('labels', 'predicate_chars'),
                                                  predicate_words=setting('labels', 'predicate_words')),
                               excluded_background=len(report['excluded_background']),
                               unresolved_attachments=len(report['unresolved_attachments']))
        save()
        require_quality(graph, required=True)
        return graph
    except BaseException as exc:
        report.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'blocked')
        report['errors'].append(str(exc))
        save()
        raise


def main(argv=None):
    """Refine a saved graph into a new version; never rewrite student history."""
    import argparse
    import os
    from datetime import datetime, timezone
    from .trace import Trace
    from .models import Models
    from .graph_view import render_graph
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--resume-review', type=Path, help='Reuse exact validated requests from an interrupted review')
    args = parser.parse_args(argv)
    source = args.source.resolve()
    original = json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    graph = json.loads((source/'artifacts/graph.json').read_text(encoding='utf-8'))
    started = datetime.now(timezone.utc)
    identifier = 'refined_' + started.strftime('%Y%m%d_%H%M%S_%f')
    trace = Trace((args.output_root or source.parent)/identifier, identifier)
    from .settings import snapshot
    config = dict(original.get('config', {}), resolved_settings=snapshot())
    manifest = dict(run_id=identifier, source_run=str(source), scope='graph_refinement',
        status='running', config=config, started_at=started.isoformat(), started_at_utc=started.isoformat(),
        graph_quality_required=True, evaluation_status='not_run', reconstruction_score=None,
        source_graph_sha256=hashlib.sha256((source/'artifacts/graph.json').read_bytes()).hexdigest())
    trace.save('manifest.json', manifest)
    try:
        models = Models(trace, config.get('model', 'qwen3.5:9b'), config.get('embedding_model', 'nomic-embed-text'),
            os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434'))
        models.preflight()
        import _submission_runtime as runtime
        trace.save('artifacts/environment.json', dict(model_details=models.details, code_sha256=runtime.source_hashes()))
        if args.resume_review:
            models.load_cache(args.resume_review)
        with trace.span('graph_quality'):
            result = refine_graph(graph, models, trace)
        result['run_id'] = identifier
        trace.save('artifacts/graph.json', result)
        trace.text('input.txt', graph.get('provenance', {}).get('text', ''))
        trace.text('knowledge_graph.html', render_graph(result))
        audit = json.loads((trace.directory/'artifacts/graph_quality.json').read_text(encoding='utf-8'))
        manifest.update(status='completed_with_issues' if audit['excluded_background'] or audit['unresolved_attachments'] else 'completed',
                        graph_quality_status='passed', excluded_background=len(audit['excluded_background']))
        print(json.dumps(dict(output=str(trace.directory), nodes=len(result['nodes']), edges=len(result['edges']),
                              model_calls=models.calls, cache_hits=models.cache_hits)), flush=True)
    except BaseException as exc:
        manifest.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc))
        raise
    finally:
        manifest.update(artifacts={k:v for k,v in trace.artifacts.items() if k != 'manifest.json'},
                        finished_at_utc=datetime.now(timezone.utc).isoformat())
        trace.save('manifest.json', manifest)
        trace.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
