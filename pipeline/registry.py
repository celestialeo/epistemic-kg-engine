"""Isolated semantic checks; no label-only alias learning or cross-run state."""
from typing import Literal
import re
from difflib import SequenceMatcher
from pydantic import Field
from .records import Record, normalize, normalize_name, name_variants, batches
from .relations import DEFAULT_RELATIONS

ConceptKind = Literal["entity", "structure", "process", "event", "substance", "property", "abstract", "other"]


class Concept(Record):
    name: str = Field(min_length=1, max_length=120)
    definition: str = Field(min_length=1, max_length=400)
    kind: ConceptKind
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
    def __init__(self, models, trace):
        self.models, self.trace = models, trace
        self.entries = {}
        self.mentions = []
        self.resolved = {}
        self.chapter_names = []

    def likely_matches(self, value):
        """Retrieve candidates only; never merge on string similarity."""
        stop = {"the", "a", "an", "of", "is", "in", "and", "to", "that", "with", "for", "or", "concept"}
        def words(text):
            return set(re.findall(r"\w+", normalize(text))) - stop
        name_words = words(value["name"])
        definition_words = words(value["definition"])
        ranked = []
        for entry in self.entries.values():
            names = [entry["name"], *entry.get("aliases", [])]
            name_score = max(SequenceMatcher(None, value["name"], n).ratio() for n in names)
            overlap = max(len(name_words & words(n)) for n in names)
            shared = len(definition_words & words(entry["definition"]))
            acronym = any(value["name"] == "".join(w[0] for w in n.split()) or
                          n == "".join(w[0] for w in value["name"].split()) for n in names)
            variant = any(name_variants(value["name"]) & name_variants(n) for n in names)
            if variant or name_score >= .65 or overlap or shared >= 2 or acronym:
                ranked.append((100 * variant + 4 * overlap + 3 * acronym + name_score + shared / max(len(definition_words), 1), entry))
        # A retrieval bound, not a limit on extracted concepts. All merges below
        # still require resolver AND verifier agreement. Misses remain distinct.
        return [e for _, e in sorted(ranked, key=lambda x: (-x[0], x[1]["name"]))[:8]]

    def resolve(self, mention, context, entity_id):
        value = mention.model_dump() if isinstance(mention, Concept) else dict(mention)
        value["name"] = normalize_name(value["name"])
        value.setdefault("kind_detail", None)
        name = value["name"]
        signature = (name, value["definition"], value["kind"], value["kind_detail"], context)
        if signature in self.resolved:
            self.trace.emit("registry.identity_reused", entity_id=entity_id, name=name)
            return self._record(value, self.resolved[signature], entity_id)
        existing = self.entries.get(name)
        if existing and all(existing[k] == value[k] for k in ("definition", "kind")):
            return self._record(value, name, entity_id)
        likely = self.likely_matches(value)
        self.trace.emit("registry.identity_candidates", entity_id=entity_id, name=name,
                        registry_size=len(self.entries), candidates=[e["name"] for e in likely])
        for page in batches(likely, 8):
            match = self.models.ask("concept_resolver",
                "Find EXACT concept identity, not relatedness. Singular/plural forms and genuine abbreviations "
                "may name the same concept. Never merge a subtype, component, broader concept, or different sense. "
                "Descriptions of different functions of the same entity can be complementary, not different senses. "
                "Never merge an action/event with its affected object. Choose an existing name as key or null. "
                "Set same_direction=true for identity.",
                {"mention": value, "context": context, "available": page}, Match, entity_id)
            matched_key = normalize_name(match.key) if match.key else None
            if matched_key not in {r["name"] for r in page} or not match.exact_meaning:
                continue
            match.key = matched_key
            if (value["kind"] == "event") != (self.entries[match.key]["kind"] == "event"):
                continue
            check = self.models.ask("concept_match_verifier",
                "Verify that these names denote the SAME concept in context, not merely related concepts. "
                "Preserve specificity and sense; receptor and NMDA receptor are not identical. "
                "Complementary definitions of the same entity are compatible. An event is never its affected object. "
                "Singular/plural variants may be identical. Set same_direction=true only for identity.",
                {"mention": value, "canonical": self.entries[match.key], "context": context}, Equivalence, entity_id)
            if check.exact_meaning and check.same_direction and check.compatible_types:
                self.resolved[signature] = match.key
                return self._record(value, match.key, entity_id)
        # Ambiguous surface forms retain distinct meanings rather than silently
        # corrupting an existing node. No string-stemming heuristic merges nodes.
        if name in self.entries:
            import hashlib
            suffix = hashlib.sha256((value["kind"] + ":" + value["definition"]).encode()).hexdigest()[:8]
            name = f"{name} ({suffix})"
            if name in self.entries:
                return self._record(value, name, entity_id)
        self.entries[name] = dict(value, name=name, aliases=[])
        self.resolved[signature] = name
        return self._record(value, name, entity_id)

    def reconcile(self, extractions, outline):
        """Resolve residual spelling/number aliases globally before seed selection."""
        from .models import ModelResponseError
        from .health import finish_item
        redirects = {}
        names = sorted(self.entries, key=lambda n: (len(n), n))
        for index, name in enumerate(names):
            if name in redirects:
                continue
            canonical = self.entries[name]
            variants = set().union(*(name_variants(n) for n in [name, *canonical.get("aliases", [])]))
            for other in names[index+1:]:
                if other in redirects:
                    continue
                entry = self.entries[other]
                if (canonical["kind"] == "event") != (entry["kind"] == "event"):
                    continue
                if not any(variants & name_variants(n) for n in [other, *entry.get("aliases", [])]):
                    continue
                payload = dict(first=canonical, second=entry,
                               chapter={k: outline[k] for k in ("overview", "topics")})
                instruction = ("Check exact concept identity in this chapter. Singular/plural, spacing and punctuation "
                    "variants denote the same concept when their senses agree. Complementary descriptions of the "
                    "same entity do not create distinct senses. Preserve genuine subtype, state, action, object and "
                    "sense distinctions. Set same_direction=true only for identity. Explain the concrete distinction "
                    "if rejecting a merge; differences in wording alone are insufficient.")
                pair_id = name + " :: " + other
                try:
                    first = self.models.ask("concept_alias_reconciler", instruction, payload, Equivalence, other)
                    if not (first.exact_meaning and first.same_direction and first.compatible_types):
                        finish_item(self.trace, "concept_reconciliation", pair_id)
                        continue
                    check = self.models.ask("concept_alias_verifier", "Independently verify this pair. " + instruction,
                                            payload, Equivalence, other)
                except ModelResponseError as exc:
                    self.trace.emit("registry.alias_unresolved", entity_id=other, error=str(exc), retained_separately=True)
                    finish_item(self.trace, "concept_reconciliation", pair_id, exc)
                    continue
                finish_item(self.trace, "concept_reconciliation", pair_id)
                if not (check.exact_meaning and check.same_direction and check.compatible_types):
                    continue
                redirects[other] = name
                canonical["aliases"] = list(dict.fromkeys([*canonical.get("aliases", []), other, *entry.get("aliases", [])]))
                canonical.setdefault("alternative_definitions", []).append(entry["definition"])
                canonical["kind_details"] = list(dict.fromkeys([*canonical.get("kind_details", []),
                    *entry.get("kind_details", []), *([entry["kind_detail"]] if entry.get("kind_detail") else [])]))
                self.trace.emit("registry.concepts_merged", canonical=name, alias=other, reason=check.reason)
                variants.update(name_variants(other))
        for extraction in extractions:
            extraction["concepts"] = list(dict.fromkeys(redirects.get(n, n) for n in extraction["concepts"]))
            retained = []
            for row in extraction["relation_proposals"]:
                for side in ("source", "target"):
                    row[side] = redirects.get(row[side], row[side])
                if row["source"] == row["target"]:
                    self.trace.emit("extraction.record_rejected", entity_id=row["id"], record=row,
                                    reason="Alias reconciliation made this a self relation; definition and claims retained")
                else:
                    retained.append(row)
            extraction["relation_proposals"] = retained
        for mention in self.mentions:
            mention["canonical"] = redirects.get(mention["canonical"], mention["canonical"])
        for signature, canonical in list(self.resolved.items()):
            self.resolved[signature] = redirects.get(canonical, canonical)
        for alias in redirects:
            del self.entries[alias]
        self.chapter_names = sorted(self.entries)
        self.trace.save("artifacts/concept_reconciliation.json", dict(redirects=redirects))
        self.trace.save("artifacts/concepts.json", dict(concepts=list(self.entries.values()), mentions=self.mentions))
        self.trace.save("artifacts/extraction_proposals.json", extractions)

    def _record(self, mention, name, entity_id):
        if mention["name"] not in self.entries[name]["aliases"]:
            self.entries[name]["aliases"].append(mention["name"])
        detail = mention.get("kind_detail")
        if detail and detail not in self.entries[name].setdefault("kind_details", []):
            self.entries[name]["kind_details"].append(detail)
        row = dict(entity_id=entity_id, mention=mention, canonical=name)
        self.mentions.append(row)
        self.trace.emit("registry.concept_resolved", entity_id=entity_id, mention=mention, canonical=name)
        self.trace.save("artifacts/concepts.json", {"concepts": list(self.entries.values()), "mentions": self.mentions})
        return name


class FactIndex:
    """Run-wide document + accepted-background facts, including inverse forms."""
    def __init__(self, relations):
        self.relations = relations
        self.rows = []

    def find(self, row):
        key = self.relations.fact_key(row["source"], row["relation"], row["target"])
        # Recompute keys: a verified new inverse may extend the vocabulary.
        return next((r for r in self.rows if self.relations.fact_key(r["source"], r["relation"], r["target"]) == key), None)

    def add(self, row):
        duplicate = self.find(row)
        if duplicate is None:
            self.rows.append(row)
        return duplicate
