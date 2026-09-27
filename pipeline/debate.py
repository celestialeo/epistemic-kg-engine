"""Contextual expansion, analogy review, critic, rebuttal and adjudication."""
from collections import Counter
from typing import Literal

from pydantic import Field, create_model

from .extraction import Record, normalize


class Proposal(Record):
    target: str = Field(min_length=1)
    tier: Literal["parent", "sibling", "child"]
    relation: Literal["is_a", "part_of", "has_part", "has_subtype", "requires_understanding_of", "sibling_of"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300, description="One short sentence")


class Expansion(Record):
    proposals: list[Proposal] = Field(max_length=3)
    reason: str = Field(min_length=1, max_length=300, description="One short sentence")


class Review(Record):
    candidate_id: str
    domain_relevance: float = Field(ge=0, le=1)
    hierarchical_plausibility: float = Field(ge=0, le=1)
    prerequisite_value: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300, description="One short sentence")


class Response(Record):
    candidate_id: str
    position: Literal["defend", "withdraw"]
    reason: str = Field(min_length=1, max_length=300, description="One short sentence")


class Verdict(Review):
    accept: bool


class Analogy(Record):
    candidate_id: str
    score: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300, description="One short sentence")


THRESHOLDS = {"parent": .55, "sibling": .60, "child": .68}
FALLBACK_WEIGHTS = [.35, .20, .30, .15]
BANNED = {"thing", "stuff", "content", "object", "information", "concept", "entity", "process"}
PHRASES = {"is_a": "is a type of", "part_of": "is a component of", "has_part": "has as a component",
           "has_subtype": "has as a subtype", "sibling_of": "is a peer concept of",
           "requires_understanding_of": "requires prior understanding of"}


def weights_for(matrix):
    """Leading eigenvector of the uncentered S^T S moment matrix (not covariance)."""
    if len(matrix) < 2:
        return FALLBACK_WEIGHTS[:]
    import numpy as np
    array = np.array(matrix, dtype=float)
    values, vectors = np.linalg.eigh(array.T @ array)
    weights = np.abs(vectors[:, -1])
    if values[-1] < 1e-10 or weights.sum() < 1e-10:
        return FALLBACK_WEIGHTS[:]
    return (weights / weights.sum()).tolist()


def index_complete(rows, candidates, trace, role):
    expected = {c["id"] for c in candidates}
    actual = [r.candidate_id for r in rows]
    valid = len(actual) == len(set(actual)) and set(actual) == expected
    trace.emit("debate.ids_validated", role=role, expected=sorted(expected), actual=actual, valid=valid)
    if not valid:
        raise ValueError(f"{role}: return exactly one record for each of {sorted(expected)}; received IDs {actual}. No duplicates or omissions.")
    return {r.candidate_id: r.model_dump() for r in rows}


def review_batch(models, role, instruction, payload, row_schema, candidates, trace, entity_id):
    """Constrain both the object keys and each nested ID at generation time."""
    fields = {}
    for candidate in candidates:
        identifier = candidate["id"]
        row = create_model(f"{role}_{identifier}", __base__=row_schema,
                           candidate_id=(Literal[identifier], ...))
        fields[identifier] = (row, ...)
    schema = create_model(f"{role}_results", __base__=Record, **fields)
    result = models.ask(role,
        instruction + " Return an object keyed by exactly these candidate IDs: " + ", ".join(fields) + ".",
        payload, schema, entity_id,
        validator=lambda r: index_complete(list(r.__dict__.values()), candidates, trace, role))
    return {identifier: getattr(result, identifier).model_dump() for identifier in fields}


def select_seeds(extractions, chunks, paragraphs, limit, trace):
    counts = Counter(c for row in extractions for c in set(row["concepts"]))
    first = {}
    for row in extractions:
        for c in row["concepts"]:
            first.setdefault(c, row["chunk_id"])
    by_chunk = {c["id"]: c for c in chunks}
    by_paragraph = {p["id"]: p for p in paragraphs}
    ranked = sorted(counts, key=lambda c: (-counts[c], first[c], c))
    seeds = []
    for concept in ranked[:limit] if limit else ranked:
        chunk = by_chunk[first[concept]]
        seed = {"id": f"seed_{len(seeds)+1:03d}", "concept": concept, "mention_count": counts[concept],
                "chunk_id": chunk["id"], "paragraph_id": chunk["paragraph_id"],
                "context": by_paragraph[chunk["paragraph_id"]]["text"]}
        seeds.append(seed)
        trace.emit("seed.selected", entity_id=seed["id"], **seed)
    trace.emit("seed.selection_completed", ranking=[{"concept": c, "count": counts[c]} for c in ranked],
               limit=limit, selected=len(seeds), omitted=len(ranked)-len(seeds))
    return seeds


def debate(seeds, models, trace):
    candidates, transcripts = [], []
    for seed in seeds:
        print(f"  Debate {seed['id']}: {seed['concept']}", flush=True)
        proposal = models.ask("proposer",
            "Propose zero to three useful background relations for this source concept in context. "
            "Do not invent a relation just to fill a tier. Never use the source concept as its own target. "
            "These are inferred background, not source evidence. Direction is SOURCE relation TARGET. "
            "PARENT tier: is_a points to a broader category, part_of points to a whole containing the source. "
            "CHILD tier: has_subtype points to a narrower TYPE, has_part points to a component. "
            "SIBLING tier: sibling_of points to a peer. A wheel is part_of a car, NOT is_a car. "
            "A car has_part a wheel, NOT has_subtype a wheel. Use the same distinction in the supplied domain.",
            seed, Expansion, seed["id"])
        current, seen = [], set()
        for value in proposal.proposals:
            row = {**value.model_dump(), "id": f"candidate_{len(candidates)+1:03d}", "seed_id": seed["id"],
                   "source": seed["concept"], "chunk_id": seed["chunk_id"], "paragraph_id": seed["paragraph_id"]}
            row["target"] = normalize(row["target"])
            row["statement"] = f"{row['source']} {PHRASES[row['relation']]} {row['target']}."
            trace.emit("debate.proposed", entity_id=row["id"], proposal=row)
            key = (row["relation"], row["target"])
            valid = bool(row["target"]) and row["target"] != row["source"] and row["target"] not in BANNED
            valid = valid and row["confidence"] >= .25 and key not in seen
            valid = valid and not (row["relation"] in {"is_a", "part_of"} and row["tier"] != "parent")
            valid = valid and not (row["relation"] in {"has_subtype", "has_part"} and row["tier"] != "child")
            valid = valid and not (row["relation"] == "sibling_of" and row["tier"] != "sibling")
            seen.add(key)
            row["rule_passed"] = valid
            trace.emit("debate.rule_checked", entity_id=row["id"], passed=valid,
                       rules=["nonempty specific target", "no self relation", "confidence >= .25", "unique", "tier matches direction"])
            candidates.append(row)
            if valid:
                current.append(row)
            else:
                row.update(accepted=False, decision_reason="Failed structural proposal gate", score=None)
                trace.emit("debate.decision", entity_id=row["id"], decision=row)
        if not current:
            transcripts.append({"seed": seed, "proposal": proposal.model_dump(), "status": "no_eligible_proposals"})
            continue
        context = {"seed": seed, "candidates": current,
                   "relation_meanings": {"is_a": "SOURCE is a kind of TARGET", "has_subtype": "TARGET is a kind of SOURCE",
                        "part_of": "SOURCE is a component of TARGET, not a kind of TARGET",
                        "has_part": "TARGET is a component of SOURCE; a component is NOT a subtype",
                        "sibling_of": "SOURCE and TARGET are peers under a common category",
                        "requires_understanding_of": "Understanding SOURCE requires understanding TARGET"}}
        children = [c for c in current if c["tier"] == "child"]
        siblings = [c for c in current if c["tier"] == "sibling"]
        analogy = {}
        if children and siblings:
            analogy = review_batch(models, "analogy_reviewer",
                "For each child candidate assess whether it is specifically related to the source, "
                "or is an overly generic child equally applicable to the proposed siblings. "
                "Return one check per CHILD candidate_id. Score specificity from 0 to 1 with a brief reason.",
                {"seed": seed, "children": children, "siblings": siblings}, Analogy, children, trace, seed["id"])
        else:
            trace.emit("debate.analogy_skipped", entity_id=seed["id"], reason="Requires both a child and sibling")
        reviews = review_batch(models, "critic",
            "Assess the literal STATEMENT of every proposal, not just whether its endpoints are related. "
            "Self-reported confidence is NOT evidence. A component is not a type: a wheel is part of a car, not a type of car. "
            "Challenge reversed directions, generic concepts, "
            "unjustified hierarchies and irrelevant prerequisites. Score relevance, hierarchy and prerequisite "
            "value independently from 0 to 1. Give one review per candidate_id and a concrete objection or rationale.",
            {**context, "analogy": analogy}, Review, current, trace, seed["id"])
        responses = review_batch(models, "proposer_rebuttal",
            "Respond to the critic for EACH candidate_id. Address its specific objection concisely. "
            "Defend a sound relation or withdraw it if the objection is valid. Do not change endpoints or relation.",
            {**context, "analogy": analogy, "critic": reviews}, Response, current, trace, seed["id"])
        verdicts = review_batch(models, "judge",
            "Adjudicate each literal STATEMENT after reading the critic and rebuttal. Return one verdict per candidate_id. "
            "Endpoint relatedness and confidence scores do not establish the claimed relationship. "
            "Reject is_a/has_subtype if the source/target is actually a component rather than a type. "
            "A wheel is part_of a car, never is_a car. Explain the semantic relationship itself, not the confidence score. "
            "Decide whether the directional relation is sound and useful in context. Reject withdrawals and "
            "unresolved objections. Give final relevance, hierarchy, prerequisite scores and a brief reason. "
            "Acceptance is a model judgment, not external factual verification.",
            {**context, "analogy": analogy, "critic": reviews, "rebuttal": responses}, Verdict, current, trace, seed["id"])
        transcripts.append({"seed": seed, "proposal": proposal.model_dump(), "analogy": analogy,
                            "critic": reviews, "rebuttal": responses, "judge": verdicts})
        for row in current:
            verdict = verdicts[row["id"]]
            row.update(critic=reviews[row["id"]], rebuttal=responses[row["id"]], judge=verdict,
                       analogy=analogy.get(row["id"]),
                       score_vector=[verdict[k] for k in ("domain_relevance", "hierarchical_plausibility", "prerequisite_value")]
                                    + [analogy.get(row["id"], {}).get("score", .5)])
            trace.emit("debate.adjudicated", entity_id=row["id"], candidate=row)
    scored = [c for c in candidates if c["rule_passed"]]
    weights = weights_for([c["score_vector"] for c in scored])
    trace.emit("debate.weights_computed", matrix=[c["score_vector"] for c in scored], weights=weights,
               method="absolute leading eigenvector of uncentered S^T S; fixed fallback for <2 or zero scores")
    for row in scored:
        row["score"] = sum(v * w for v, w in zip(row["score_vector"], weights))
        row["threshold"] = THRESHOLDS[row["tier"]]
        row["accepted"] = (row["judge"]["accept"] and row["rebuttal"]["position"] != "withdraw"
                           and row["score"] >= row["threshold"])
        row["decision_reason"] = row["judge"]["reason"]
        trace.emit("debate.decision", entity_id=row["id"], decision=row)
    return {"seeds": seeds, "candidates": candidates, "transcripts": transcripts, "weights": weights,
            "thresholds": THRESHOLDS, "dimensions": ["domain_relevance", "hierarchical_plausibility", "prerequisite_value", "analogy_specificity"]}
