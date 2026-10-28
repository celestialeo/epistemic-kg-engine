"""Name-based concept identity and semantic relationship contracts."""
from typing import Literal
from pydantic import Field
from .records import Record, batches
from .identity import concept_key, short_definition
from .relations import DEFAULT_RELATIONS

ConceptKind = Literal["entity", "structure", "process", "event", "substance", "property", "abstract", "other"]


class Concept(Record):
    name: str = Field(min_length=1, max_length=400,
        description="Canonical name of a standalone concept, never a statement or context-dependent reference")
    definition: str = Field(min_length=1, max_length=400)
    kind: ConceptKind
    form: Literal["concept"] = Field(default="concept",
        description="All graph endpoints are standalone concepts; assertions belong in relations")
    kind_detail: str | None = Field(default=None, max_length=120,
        description="Optional specific domain label, e.g. cell_type, receptor, or system")


class Match(Record):
    key: str | None
    exact_meaning: bool
    same_direction: bool
    reason: str = Field(min_length=1, max_length=800)


class Equivalence(Record):
    exact_meaning: bool
    same_direction: bool
    compatible_types: bool
    reason: str = Field(min_length=1, max_length=800)


class NewRelation(Record):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    definition: str = Field(min_length=1, max_length=400)
    symmetric: bool
    inverse: str | None


class DefinitionCheck(Record):
    coherent: bool
    meaning_preserved: bool
    direction_preserved: bool
    symmetry_correct: bool
    inverse_correct: bool
    reason: str = Field(min_length=1, max_length=800)


class RelationRegistry:
    def __init__(self, models, trace):
        self.models, self.trace = models, trace
        self.entries = {key: dict(key=key, definition=value[0], inverse=value[1], symmetric=value[2])
                        for key, value in DEFAULT_RELATIONS.items()}
        self.decisions = []

    def snapshot(self):
        return {"relations": list(self.entries.values()), "decisions": self.decisions,
                "alias_policy": "Each occurrence is checked; a surface label is never a global alias."}

    def vocabulary(self):
        return list(self.entries.values())

    def _record(self, entity_id, original, key, reason):
        row = dict(entity_id=entity_id, original=original, canonical_key=key, reason=reason)
        self.decisions.append(row)
        self.trace.emit("registry.relation_resolved", entity_id=entity_id, **{k: v for k, v in row.items() if k != "entity_id"})
        self.trace.save("artifacts/relations.json", self.snapshot())
        return key

    def resolve(self, relation, definition, source, target, context, entity_id):
        original = dict(label=relation, definition=definition, source=source, target=target, context=context)
        # Exact copies of an existing contract are not new meanings. Actual use
        # still goes through the shared entailment/debate checks.
        if relation in self.entries and definition == self.entries[relation]["definition"]:
            return self._record(entity_id, original, relation, "Existing exact relation contract; usage requires review")
        for page in batches(self.vocabulary()):
            match = self.models.ask("relation_resolver",
                "Find a relation with EXACTLY the same meaning AND SOURCE-to-TARGET direction. "
                "Never merge enabling with causing, containment with parthood/ownership, or a relation with its inverse. "
                "An ambiguous label such as has-a is interpreted only using this occurrence's definition and context. "
                "Return key=null unless both statements entail each other. Only select a listed key.",
                {"occurrence": original, "available": page}, Match, entity_id)
            if match.key not in {r["key"] for r in page} or not (match.exact_meaning and match.same_direction):
                continue
            # Existing named contracts cannot be globally collapsed, even if a
            # model mistakenly calls them equivalent.
            if relation in self.entries and relation != match.key:
                continue
            target_spec = self.entries[match.key]
            check = self.models.ask("relation_match_verifier",
                "Independently verify bidirectional semantic equivalence of the two relation definitions "
                "in this occurrence, keeping SOURCE and TARGET fixed. Similarity is insufficient. "
                "Check direction, causal strength, modality, scope, and endpoint types. "
                "Do not reinterpret participation or location as structural parthood.",
                {"occurrence": original, "proposed_contract": target_spec}, Equivalence, entity_id)
            if check.exact_meaning and check.same_direction and check.compatible_types:
                return self._record(entity_id, original, match.key, check.reason)
        # A rejected use of an established key must not create a competing sense.
        if relation in self.entries:
            return self._record(entity_id, original, None, "Existing key used with an unverified meaning")
        new = self.models.ask("relation_definition",
            "Define a new reusable relation for this precise meaning, preserving SOURCE-to-TARGET direction. "
            "Use a descriptive snake_case key; do not include entity names. Avoid vague has-a. "
            "Define the meaning justified by the source assertion, not unsupported restrictions in a draft definition. "
            "Do not broaden or weaken meaning. Set symmetric only when reversing endpoints preserves truth. "
            "An inverse must be an existing key and must mean exactly the reverse; otherwise use null.",
            {"occurrence": original, "existing_keys": list(self.entries)}, NewRelation, entity_id)
        if new.key in self.entries or (new.inverse is not None and new.inverse not in self.entries):
            return self._record(entity_id, original, None, "New relation key collision or unknown inverse")
        inverse = self.entries.get(new.inverse)
        if inverse and (inverse["inverse"] not in (None, new.key) or inverse["symmetric"] or new.symmetric):
            return self._record(entity_id, original, None, "Conflicting inverse or symmetry contract")
        check = self.models.ask("relation_definition_verifier",
            "Independently check that the new relation is coherent, specific, and exactly preserves the "
            "source assertion's meaning and direction. Reject extra restrictions absent from the source. "
            "Check symmetry and any inverse against its full definition. "
            "An inverse is equivalence AFTER swapping endpoints, not relatedness. Null inverse is valid. "
            "Reject vague or invented predicate meanings and incompatible entity/process uses.",
            {"occurrence": original, "new_contract": new.model_dump(), "inverse_contract": inverse},
            DefinitionCheck, entity_id)
        if not all((check.coherent, check.meaning_preserved, check.direction_preserved,
                    check.symmetry_correct, check.inverse_correct)):
            return self._record(entity_id, original, None, check.reason)
        self.entries[new.key] = new.model_dump()
        if inverse:
            inverse["inverse"] = new.key
        self.trace.emit("registry.relation_added", entity_id=entity_id, relation=new.model_dump())
        return self._record(entity_id, original, new.key, check.reason)

    def fact_key(self, source, relation, target):
        spec = self.entries[relation]
        keys = [(source, relation, target)]
        if spec["symmetric"]:
            keys.append((target, relation, source))
        if spec["inverse"]:
            keys.append((target, spec["inverse"], source))
        return min(keys)


class ConceptRegistry:
    """Every occurrence of a normalized name has exactly one canonical concept."""
    def __init__(self, models, trace):
        self.models, self.trace = models, trace
        self.entries = {}
        self.mentions = []
        self.chapter_names = []

    def resolve(self, mention, context, entity_id):
        value = Concept.model_validate(mention).model_dump()
        name = concept_key(value["name"])
        if name not in self.entries:
            # Kind is extraction/review metadata, never part of identity. Graph
            # nodes expose only the canonical name and one short definition.
            self.entries[name] = dict(name=name, definition=short_definition(value["definition"]),
                                      kind=value["kind"], form="concept")
        else:
            self.trace.emit("registry.identity_reused", entity_id=entity_id, name=name)
        row = dict(entity_id=entity_id, mention=value, canonical=name)
        self.mentions.append(row)
        self.trace.emit("registry.concept_resolved", **row)
        self.trace.save("artifacts/concepts.json", dict(concepts=list(self.entries.values()),
                                                       mentions=self.mentions))
        return name

    def reconcile(self, extractions, outline):
        """Normalize imported names without model-driven sense splitting/merging."""
        redirects, canonical = {}, {}
        for old_name, entry in self.entries.items():
            name = concept_key(old_name)
            redirects[old_name] = name
            canonical.setdefault(name, dict(name=name, definition=short_definition(entry["definition"]),
                                            kind=entry["kind"], form="concept"))
            if old_name != name:
                self.trace.emit("registry.concepts_merged", canonical=name, alias=old_name,
                                reason="Same normalized name")
        self.entries = canonical
        for extraction in extractions:
            extraction["concepts"] = list(dict.fromkeys(concept_key(n) for n in extraction["concepts"]))
            for collection in ("relation_proposals", "relations"):
                for row in extraction.get(collection, []):
                    for side in ("source", "target"):
                        row[side] = concept_key(row[side])
        for mention in self.mentions:
            mention["canonical"] = concept_key(mention["canonical"])
        self.chapter_names = sorted(self.entries)
        self.trace.save("artifacts/concept_reconciliation.json", dict(
            policy="normalized_name_only", redirects=redirects))
        self.trace.save("artifacts/concepts.json", dict(concepts=list(self.entries.values()), mentions=self.mentions))
        self.trace.save("artifacts/extraction_proposals.json", extractions)


class FactIndex:
    """Run-wide document + accepted-background facts, including inverse forms."""
    def __init__(self, relations):
        self.relations = relations
        self.rows = []

    def find(self, row):
        key = self.relations.fact_key(row["source"], row["relation"], row["target"])
        # Recompute keys: a verified new inverse may extend the vocabulary.
        return next((r for r in self.rows if self.relations.fact_key(r["source"], r["relation"], r["target"]) == key
                     and all(r.get(k) == row.get(k) for k in ("conditions", "modality"))), None)

    def add(self, row):
        duplicate = self.find(row)
        if duplicate is None:
            self.rows.append(row)
        return duplicate
