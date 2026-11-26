from .settings import setting
"""Shared quiz scope, provenance and conservative mastery projection."""
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class AssessmentCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_id: str
    scope: Literal["full_relationship", "component"]
    requested: str = Field(min_length=1, max_length=setting('text', 'question_chars'))
    given: str = Field(max_length=setting('text', 'question_chars'))
    criteria: list[str] = Field(min_length=1)


def validate_spec(spec, identifiers):
    parsed = [AssessmentCriterion.model_validate(item) for item in spec]
    if len(parsed) != len(identifiers) or {c.fact_id for c in parsed} != set(identifiers):
        raise ValueError("Assessment specification must cover exactly the assessed fact IDs, once each")
    if any(not c.requested.strip() or any(not v.strip() or len(v)>setting('text', 'question_chars') for v in c.criteria) for c in parsed):
        raise ValueError("State the requested information and substantive criteria explicitly")
    return [c.model_dump() for c in parsed]


SPEC_RULES = """Write an assessment_spec entry for each assessed fact, with fact_id,
scope, requested, given, and criteria. Distinguish what the learner must retrieve
from information already supplied in the question. Scope is component if asking
only for an endpoint, term, property, or qualification. Such a correct answer does
NOT demonstrate an entire relationship. Use full_relationship only when asking
the learner to explain the connection, its orientation and applicable qualifications,
not when the question supplies that connection and asks for a missing name.
List explicit substantive criteria grounded in the supplied fact. Do not invent
criteria. The question, expected answer and specification must agree exactly on
what is assessed. Short answers and paraphrases can satisfy the requested criteria.
For a full relationship, the expected answer must explain the connection rather
than merely name its endpoints. Never silently expand scope during grading."""


def fingerprint(fact):
    return hashlib.sha256(json.dumps(fact,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def eligible_fact(fact, approvals=None):
    # Background-model consensus is not independent supporting evidence.
    # Until a source-support verifier exists, require explicit professor approval.
    return fact.get('origin') not in {'background', 'student'} or bool((approvals or {}).get(fact['id']))


def validate_graph_consistency(result):
    from .models import ModelResponseError
    conflicts={m['id'] for m in result.get('matches',[]) if m['status']=='conflict'}
    positive={r['fact_id'] for r in result['rubric'] if r['status'] in {'complete','partial'}}
    if conflicts & positive:
        raise ModelResponseError('Question grading and relationship matching disagree for '+', '.join(sorted(conflicts & positive))+'. Relationship assessment remains unresolved; retry or request professor review.')


def mastery_marks(question, result, effective=None, professor_override=False):
    from .quiz_grading import RUBRIC_MARKS
    if result.get('assessment_version') not in {2, 3}:
        return None  # Preserve historical grading policy and progress.
    spec = {c['fact_id']:c for c in result['assessment_spec']}
    marks = effective if effective is not None else {r['fact_id']:RUBRIC_MARKS[r['status']] for r in result['rubric']}
    if result.get('graph_assessment',{}).get('status') == 'unresolved' and not professor_override:
        return {}  # A failed mapping does not change any relationship state.
    matches = {}
    rank={'related':1,'match':2,'conflict':3}
    for m in result.get('matches',[]):
        if rank[m['status']] > rank.get(matches.get(m['id']),0):
            matches[m['id']]=m['status']
    projected={}
    for key, mark in marks.items():
        if key not in spec:
            raise ValueError('Cannot change mastery outside the assessment specification')
        if mark == 'match':
            full=spec[key]['scope']=='full_relationship'
            if result.get('assessment_version') == 3 and not professor_override:
                semantic=next((j for j in result.get('judgments',[]) if j['fact_id']==key), {})
                full=full and semantic.get('relationship_demonstrated') is True and semantic.get('status')=='complete'
                full=full and set(semantic.get('criteria_met',[]))==set(range(len(spec[key]['criteria'])))
                full=full and bool(semantic.get('evidence')) and all(e.get('statement_id')=='answer' and e.get('quote') and e['quote'] in result.get('input','') for e in semantic.get('evidence',[]))
            mark='match' if full and (professor_override or matches.get(key)=='match') else 'related'
        projected[key]=mark
    return projected
