from .settings import predicate_pattern, budgeted_pages
from .settings import setting
"""Name-based concept identity and semantic relationship contracts."""
from typing import Literal
from difflib import SequenceMatcher
import re
from pydantic import Field
from .records import Record, name_variants
from .identity import concept_key, short_definition
from .relations import DEFAULT_RELATIONS
from .models import ModelResponseError
from .health import finish_item
from .retrieval import shortlist

ConceptKind = Literal["entity", "structure", "process", "event", "substance", "property", "abstract", "other"]


class Concept(Record):
    name: str = Field(min_length=1, max_length=setting('text', 'name_chars'),
        description="Canonical name of a standalone concept, never a statement or context-dependent reference")
    definition: str = Field(min_length=1, max_length=setting('text', 'definition_chars'))
    kind: ConceptKind
    form: Literal["concept"] = Field(default="concept",
        description="All graph endpoints are standalone concepts; assertions belong in relations")
    kind_detail: str | None = Field(default=None, max_length=setting('text', 'detail_chars'),
        description="Optional specific category inferred from the supplied domain and concept")


class Match(Record):
    key: str | None
    exact_meaning: bool
    same_direction: bool
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))


class Equivalence(Record):
    exact_meaning: bool
    same_direction: bool
    compatible_types: bool
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))


class ConceptMatch(Record):
    canonical_name: str | None
    reason: str = Field(min_length=1)


class ConceptIdentity(Record):
    same_concept: bool
    same_scope: bool
    reason: str = Field(min_length=1)


class BackgroundIdentity(Record):
    reason: str = Field(min_length=1)
    distinction: str | None = Field(description="A difference in what the concepts refer to, if any. Relatedness, measurement, cause or explanation does not make two things identical. Null only for interchangeable names of the same referent.")
    same_concept: bool
    same_scope: bool


class NewRelation(Record):
    key: str = Field(pattern=predicate_pattern(), max_length=setting('labels', 'predicate_chars'))
    definition: str = Field(min_length=1, max_length=setting('text', 'definition_chars'))
    symmetric: bool
    inverse: str | None


class DefinitionCheck(Record):
    coherent: bool
    meaning_preserved: bool
    direction_preserved: bool
    symmetry_correct: bool
    inverse_correct: bool
    reason: str = Field(min_length=1, max_length=setting('text', 'explanation_chars'))


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
        # A named built-in contract is already a plausible candidate. Verify its
        # qualified use before asking a search model to choose a different key.
        # This is occurrence-level verification, never a global label alias.
        named = re.sub(r'[^a-z0-9]+', '_', relation.casefold()).strip('_')
        if named in DEFAULT_RELATIONS:
            check = self._verify_contract(original, self.entries[named], entity_id)
            if check.exact_meaning and check.same_direction and check.compatible_types:
                return self._record(entity_id, original, named, check.reason)
        limit = getattr(self.models, 'identity_candidates', None) or setting('workload', 'retrieval_candidates')
        candidates = shortlist(relation + ' ' + definition, self.vocabulary(), limit,
                               name_field='key', preferred=relation)
        self.trace.emit('registry.relation_candidates', entity_id=entity_id,
                        available=len(self.entries), candidates=[r['key'] for r in candidates],
                        policy='retrieval_only_verified_equivalence_required')
        protected_conflict = False
        for page in budgeted_pages(candidates, self.models, shared=original, schema=Match, role='relation_resolver'):
            match = self.models.ask("relation_resolver",
                "Find a relation whose use with these fixed endpoints and saved qualifiers expresses EXACTLY the same source assertion and direction. "
                "Never merge enabling with causing, containment with parthood/ownership, or a relation with its inverse. "
                "An ambiguous label such as has-a is interpreted only using this occurrence's definition and context. "
                "Compare the complete qualified assertions, not draft-definition wording in isolation. A general contract may express a specific instance when all extra meaning stays explicit in its qualifiers. Return key=null unless the qualified statements entail each other. Only select a listed key.",
                {"occurrence": original, "available": page}, Match, entity_id)
            if match.key not in {r["key"] for r in page} or not (match.exact_meaning and match.same_direction):
                continue
            # Existing named contracts cannot be globally collapsed, even if a
            # model mistakenly calls them equivalent.
            if relation in DEFAULT_RELATIONS and relation != match.key:
                protected_conflict = True
                continue
            target_spec = self.entries[match.key]
            check = self._verify_contract(original, target_spec, entity_id)
            if check.exact_meaning and check.same_direction and check.compatible_types:
                return self._record(entity_id, original, match.key, check.reason)
        # Preserve an already precise proposed label. Renaming every new relation
        # adds a model call and can reverse the displayed meaning (e.g. a passive
        # predicate becoming active). A new contract still receives verification.
        proposed_key = re.sub(r'[^a-z0-9]+', '_', relation.casefold()).strip('_')
        if protected_conflict:
            return self._record(entity_id, original, None, 'Protected named contract cannot collapse into another contract')
        if (proposed_key not in self.entries and re.fullmatch(predicate_pattern(), proposed_key)
                and len(proposed_key) <= setting('labels', 'predicate_chars')):
            new = NewRelation(key=proposed_key, definition=definition, symmetric=False, inverse=None)
        else:
            def validate_new_contract(value):
                if value.key in self.entries:
                    raise ValueError('This key already has a different unverified contract. Choose a distinct precise key; never overwrite it.')
                if value.inverse is not None and value.inverse not in self.entries:
                    raise ValueError('Inverse must name an existing contract or be null')
            new = self.models.ask("relation_definition",
            "Define a new reusable relation for this precise meaning, preserving SOURCE-to-TARGET direction. "
            f"Prefer a precise one-to-three-word snake_case key; allow more when needed for meaning, at most {setting('labels', 'predicate_words')} words and {setting('labels', 'predicate_chars')} characters. "
            "Do not include endpoint names, conditions or a whole explanatory sentence. Avoid vague has-a. "
            "If the proposed label already exists but its contract was not equivalent, choose a DISTINCT "
            "precise label for this sense. Do not redefine or overwrite an existing contract. "
            "Define the meaning justified by the source assertion, not unsupported restrictions in a draft definition. "
            "Do not broaden or weaken meaning. Set symmetric only when reversing endpoints preserves truth. "
            "An inverse must be an existing key and must mean exactly the reverse; otherwise use null.",
            {"occurrence": original, "existing_keys": list(self.entries)}, NewRelation, entity_id,
                validator=validate_new_contract)
        if new.key in self.entries or (new.inverse is not None and new.inverse not in self.entries):
            return self._record(entity_id, original, None, "New relation key collision or unknown inverse")
        inverse = self.entries.get(new.inverse)
        if inverse and (inverse["inverse"] not in (None, new.key) or inverse["symmetric"] or new.symmetric):
            return self._record(entity_id, original, None, "Conflicting inverse or symmetry contract")
        check = self.models.ask("relation_definition_verifier",
            "Independently check that the new relation is coherent, specific, and exactly preserves the "
            "source assertion's meaning and direction. Reject extra restrictions absent from the source. "
            "Read SOURCE -> key -> TARGET as an ordinary phrase: the label itself must agree with the "
            "definition's direction. An active verb cannot stand for its passive inverse. "
            "The predicate is a reusable meaning; occurrence-level negation, uncertainty and conditions "
            "are applied separately. Do not fold them into a second negation or demand a positive assertion "
            "when the supplied source explicitly negates this predicate. "
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

    def _verify_contract(self, original, target_spec, entity_id):
        context = original.get('context')
        qualifiers = {key: context.get(key) for key in ('conditions','modality','argument_qualifiers')} if isinstance(context,dict) else {}
        qualified_original = dict(source=original['source'], relation=original['label'],
            target=original['target'], definition=original['definition'], **qualifiers)
        qualified_proposal = dict(source=original['source'], relation=target_spec['key'],
            target=original['target'], definition=target_spec['definition'], **qualifiers)
        return self.models.ask("relation_match_verifier",
            "Independently verify bidirectional equivalence of the complete qualified source assertion and the proposed canonical assertion, keeping SOURCE and TARGET fixed. Similarity is insufficient. "
            "Draft definition wording may vary; a specific occurrence can use a general contract only when its endpoints and explicit qualifiers preserve every substantive distinction. "
            "Compare qualified_original with qualified_proposal: BOTH retain the identical saved qualifiers. Do not compare a qualified occurrence with an unqualified dictionary definition. "
            "Check direction, causal strength, modality, scope, and endpoint types. "
            "Do not reinterpret participation or location as structural parthood.",
            {"occurrence": original, "proposed_contract": target_spec,
             "qualified_original": qualified_original, "qualified_proposal": qualified_proposal}, Equivalence, entity_id)

    def resolve_background(self, relation, definition, source, target, context, entity_id):
        """Use a named contract as written; the sentence/link check validates use.

        A concrete draft description need not be globally equivalent to a
        reusable predicate definition. Never redefine the existing contract to
        fit it: the canonical assertion must still preserve the intended fact.
        """
        if relation in self.entries:
            original = dict(label=relation, definition=definition, source=source, target=target, context=context)
            return self._record(entity_id, original, relation,
                "Existing named contract retained; background representation review must validate its literal use")
        return self.resolve(relation, definition, source, target, context, entity_id)

    def fact_key(self, source, relation, target):
        spec = self.entries[relation]
        keys = [(source, relation, target)]
        if spec["symmetric"]:
            keys.append((target, relation, source))
        if spec["inverse"]:
            keys.append((target, spec["inverse"], source))
        return min(keys)


class ConceptRegistry:
    """Normalized names and verified aliases share one canonical concept."""
    def __init__(self, models, trace):
        self.models, self.trace = models, trace
        self.entries = {}
        self.mentions = []
        self.chapter_names = []
        self.aliases = {}

    def _save(self):
        self.trace.save("artifacts/concepts.json", dict(concepts=list(self.entries.values()),
            mentions=self.mentions, aliases=dict(self.aliases)))

    def _verify_identity(self, mention, existing, context, entity_id, *, background=False):
        check = self.models.ask('concept_alias_verifier',
            'Decide whether these names refer to the same concept in the supplied text and graph context. '
            'Treat singular/plural and hyphenated/spaced forms of the same term as the same concept by '
            'default. Generic singular and generic plural descriptions have the same scope. Keep them '
            'separate when the text contrasts an individual item with a group, or when the terms have '
            'different meanings. Do not infer that contrast solely from grammatical number. A spelling '
            'resemblance alone cannot establish the same term. Check whether substituting the supplied '
            'canonical name preserves the reference. Definition wording and inferred kind labels are '
            'fallible descriptions, not identity constraints. Related concepts and different levels of '
            'specificity remain distinct. A property and its measure, a process and its input, '
            'or a category and its member are not interchangeable.' +
            (' State any referential difference in distinction; null means no such difference.' if background else ''),
            {'occurrence': mention, 'existing_concept': existing, 'context': context},
            BackgroundIdentity if background else ConceptIdentity, entity_id)
        self.trace.emit('registry.concept_alias_checked', entity_id=entity_id,
                        occurrence=mention, canonical=existing['name'], result=check.model_dump())
        return check.same_concept and check.same_scope and not getattr(check, 'distinction', None)

    def _semantic_match(self, mention, available, context, entity_id, *, background=False):
        """Similarity alone never merges concepts; verify identity and scope."""
        # Bound expensive model comparisons as the chapter grows. Retrieval
        # can leave aliases undiscovered, but can never authorize a false merge.
        # Names that are not selected remain separate concepts, not discarded.
        limit = getattr(self.models, 'identity_candidates', None) or setting('workload', 'retrieval_candidates')
        query = mention['name'] + ' ' + mention['definition']
        variants = name_variants(mention['name'])
        forms = [entry for entry in available.values() if variants & name_variants(entry['name'])]
        prioritized = shortlist(query, forms, limit, preferred=mention['name'])
        others = shortlist(query, [entry for entry in available.values() if entry not in forms],
                           limit, preferred=mention['name'])
        candidates = (prioritized + others)[:limit] if limit else prioritized + others
        # Inflection is a retrieval hint, never an unchecked string-based merge.
        # Check these pairs directly so a search response cannot discard them
        # merely because singular and plural descriptions have different wording.
        forms = [entry for entry in candidates if variants & name_variants(entry['name'])]
        for entry in forms:
            if self._verify_identity(mention, entry, context, entity_id, background=background):
                return entry['name']
        candidates = [entry for entry in candidates if entry not in forms]
        self.trace.emit('registry.identity_candidates', entity_id=entity_id, available=len(available),
            limit=limit, candidates=[c['name'] for c in candidates], policy='retrieval_only_verified_identity_required')
        from .settings import budgeted_pages
        for page in budgeted_pages(candidates, self.models, shared=dict(occurrence=mention, context=context), schema=ConceptMatch, role='concept_alias_resolver'):
            def validate(result):
                if result.canonical_name is not None and result.canonical_name not in {c["name"] for c in page}:
                    raise ValueError("A concept alias must select a supplied canonical name")
            match = self.models.ask("concept_alias_resolver",
                "Decide whether the occurrence denotes the SAME concept as a supplied entry, despite a "
                "different name, phrasing, or definition. Use contextual meaning and scope. "
                "Singular/plural and hyphenated/spaced forms of the same term normally share identity; "
                "separate an individual from a group only when the supplied text makes that distinction. "
                "Related concepts, different levels of specificity, and concepts merely mentioned in another definition are "
                "not aliases. Differences in what a definition explains do not by themselves establish "
                "different identity. Select an existing canonical_name only for identity, otherwise null.",
                {"occurrence": mention, "context": context, "existing_concepts": page},
                ConceptMatch, entity_id, validator=validate)
            if match.canonical_name is None:
                continue
            if self._verify_identity(mention, available[match.canonical_name], context,
                                     entity_id, background=background):
                return match.canonical_name
        return None

    def resolve_background(self, mention, context, entity_id):
        """Reuse a verified existing concept before registering a new endpoint."""
        value = Concept.model_validate(mention).model_dump()
        name = concept_key(value["name"])
        verified = False
        if name not in self.entries and name not in self.aliases:
            canonical = self._semantic_match(value, self.entries, context, entity_id, background=True)
            if canonical is not None:
                self.aliases[name] = canonical
                verified = True
                self.trace.emit("registry.concepts_merged", entity_id=entity_id,
                                alias=name, canonical=canonical, reason="Verified same concept and scope")
        return self.resolve(value, context, entity_id, _verified=verified)

    def resolve(self, mention, context, entity_id, *, _verified=False):
        value = Concept.model_validate(mention).model_dump()
        name = concept_key(value["name"])
        canonical = self.aliases.get(name, name)
        if (canonical != name and not _verified
                and name_variants(name) & name_variants(canonical)
                and not self._verify_identity(value, self.entries[canonical], context, entity_id)):
            # A run-local alias must not erase a later explicit item/group contrast.
            canonical = name
            self.aliases[name] = name
            self.trace.emit('registry.concept_scope_preserved', entity_id=entity_id,
                            occurrence=value, canonical=name, context=context)
        name = canonical
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
        self._save()
        return name

    def reconcile(self, extractions, outline):
        """Reconcile verified document aliases before seed selection and fact indexing."""
        redirects, canonical = {}, {}
        for old_name, entry in self.entries.items():
            name = concept_key(old_name)
            context = dict(chapter={key: outline[key] for key in ("overview", "topics")},
                           source_claims=[claim for extraction in extractions
                                          if old_name in extraction["concepts"]
                                          for claim in extraction.get("claims", [])])
            if name not in canonical:
                try:
                    match = self._semantic_match(entry, canonical, context, f"reconcile_{old_name}")
                except ModelResponseError as exc:
                    finish_item(self.trace, "concept_identity", old_name, exc)
                else:
                    if match is not None:
                        name = match
                    finish_item(self.trace, "concept_identity", old_name)
            redirects[old_name] = name
            self.aliases[concept_key(old_name)] = name
            canonical.setdefault(name, dict(name=name, definition=short_definition(entry["definition"]),
                                            kind=entry["kind"], form="concept"))
            if old_name != name:
                self.trace.emit("registry.concepts_merged", canonical=name, alias=old_name,
                                reason="Same normalized name or verified semantic identity")
        self.entries = canonical
        for extraction in extractions:
            extraction["concepts"] = list(dict.fromkeys(redirects[n] for n in extraction["concepts"]))
            for collection in ("relation_proposals", "relations"):
                for row in extraction.get(collection, []):
                    for side in ("source", "target"):
                        row[side] = redirects.get(row[side], concept_key(row[side]))
        for mention in self.mentions:
            mention["canonical"] = redirects.get(mention["canonical"], concept_key(mention["canonical"]))
        self.chapter_names = sorted(self.entries)
        self.trace.save("artifacts/concept_reconciliation.json", dict(
            policy="normalized_names_and_verified_aliases", redirects=redirects))
        self._save()
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
                     and all(r.get(k) == row.get(k) for k in ("conditions", "modality"))
                     and sorted(r.get("argument_qualifiers") or []) == sorted(row.get("argument_qualifiers") or [])), None)

    def add(self, row):
        duplicate = self.find(row)
        if duplicate is None:
            self.rows.append(row)
        return duplicate
