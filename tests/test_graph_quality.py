"""Publication safety, meaning-preserving repairs and reviewed graph versions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pipeline.graph_quality import CONTRACTS, Fact, SingleFactPlan, ReviewPolicy, refine_graph, require_quality, structural_issues
from pipeline.graph_view import concept_id
from pipeline.models import ModelServiceError
from pipeline.trace import Trace


def sample():
    nodes = [dict(id=concept_id(name), label=name, definition=definition, kind='concept', origin='document')
             for name, definition in [('quantization', 'Reduction of numerical precision.'),
                                      ('memory requirement', 'Memory needed to store a model.')]]
    text = 'Quantization reduces memory requirements.'
    return dict(run_id='fixture', nodes=nodes, edges=[dict(id='edge_1', source=nodes[0]['id'],
        target=nodes[1]['id'], label='reduces_memory_requirement_via_precision_reduction',
        definition='SOURCE decreases TARGET.', origin='document', evidence=text, chunk_id='c1')],
        provenance=dict(text=text, chunks=[dict(id='c1', text=text, start=0, end=len(text))]))


class Reviewer:
    def __init__(self, *, bad_direction=False, omit=False, fail=False, dangling_merge=False, final_bad=False):
        self.bad_direction, self.omit, self.fail = bad_direction, omit, fail
        self.dangling_merge = dangling_merge
        self.final_bad = final_bad
        self.roles = []

    def ask(self, role, instruction, payload, schema, identifier, validator=None):
        self.roles.append(role)
        if self.fail:
            raise ModelServiceError('offline')
        if role == 'graph_reference_resolver':
            value = dict(references=[])
        elif role in {'graph_entity_context', 'graph_entity_context_check'}:
            value = dict(owned_by=None, performed_by=None, ambiguous=False, reason='No source-attributed role in fixture')
        elif role == 'graph_reference_verifier':
            value = dict(valid=True, issues=[])
        elif role == 'graph_fact_context_reviewer':
            value = dict(actors_explicit=True, ownership_explicit=True, purpose_preserved=True,
                         timing_preserved=True, qualifications_preserved=True, role_scopes_correct=True, issues=[])
        elif role == 'graph_background_objection_review':
            value = dict(counterexample_applies=True, qualification_needed=True,
                         assertion_supported=False, reason='Fixture objection remains supported')
        elif role == 'graph_node_editor':
            value = dict(nodes=[dict(id=n['id'], label=n['label'], definition=n['definition'],
                merge_into='invented' if self.dangling_merge else None, reason='Unchanged concept') for n in payload['nodes']])
        elif role == 'graph_node_reviewer':
            value = dict(nodes=[dict(id=n['id'], valid=True, reason='Same referent') for n in payload['nodes']])
        elif role == 'graph_fact_editor':
            old = payload['original']
            value = dict(facts=[] if self.omit else [dict(source={k:old['source'][k] for k in ('label','definition')},
                target={k:old['target'][k] for k in ('label','definition')}, relation='reduces',
                definition=CONTRACTS['reduces'], evidence=old['evidence'], conditions=None, modality=None)],
                reason='Short predicate preserves direction')
        elif role == 'graph_displayed_fact_reader':
            value = dict(meaning=payload['displayed'])
        elif role == 'graph_fact_reviewer':
            value = dict(facts=[dict(index=i, literal_meaning='Quantization reduces memory requirements.',
                faithful=True, supported=True, direction_valid=not self.bad_direction, label_matches_contract=True, endpoints_valid=True,
                qualifications_preserved=True, reason='Wrong direction' if self.bad_direction else 'Supported')
                for i,_ in enumerate(payload['proposed'])], omission_valid=not self.omit, reason='Review')
        elif role == 'graph_final_reviewer':
            assert 'source' not in payload
            value = dict(consistent=not self.final_bad, concepts_distinct=True,
                         issues=['Conflicting final relationships'] if self.final_bad else [])
        elif role == 'graph_source_coverage':
            assert all(e['origin']=='document' for e in payload['edges'])
            assert all('evidence' not in e for e in payload['edges'])
            value = dict(complete=True, issues=[], bad_edge_ids=[], sentences=[dict(index=i,
                claims=[dict(assertion=s, edge_ids=[payload['edges'][0]['id']], represented=True, reason='Covered')],
                no_claim_reason=None) for i,s in enumerate(payload['sentences'])])
        elif role == 'graph_background_challenge':
            value = dict(valid=True, counterexample=None, required_qualification=None, reason='Plausible fixture')
        else:
            raise AssertionError(role)
        result = schema.model_validate(value)
        if validator:
            validator(result)
        return result


class GraphQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name)/'run', 'test-quality')
        self.addCleanup(self.trace.close)

    def test_shortening_keeps_evidence_and_source_immutable(self):
        original = sample()
        before = copy.deepcopy(original)
        model = Reviewer()
        graph = refine_graph(original, model, self.trace)
        self.assertEqual(before, original)
        self.assertEqual(graph['edges'][0]['label'], 'reduces')
        self.assertEqual(graph['edges'][0]['evidence'], original['edges'][0]['evidence'])
        self.assertEqual(graph['edges'][0]['verification_basis'], 'quote_entailment_model_review')
        self.assertEqual(structural_issues(graph), [])
        require_quality(graph, required=True)
        self.assertIn('graph_node_reviewer', model.roles)
        self.assertIn('graph_fact_reviewer', model.roles)
        self.assertIn('graph_final_reviewer', model.roles)
        self.assertIn('graph_source_coverage', model.roles)
        self.assertEqual(json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())['status'], 'passed')

    def test_content_change_invalidates_review_including_evidence(self):
        graph = refine_graph(sample(), Reviewer(), self.trace)
        graph['edges'][0]['target'] = graph['edges'][0]['source']
        with self.assertRaisesRegex(ValueError, 'changed after'):
            require_quality(graph, required=True)

    def test_shortening_cannot_drop_source_conditions_or_modality(self):
        graph = sample()
        graph['edges'][0].update(conditions='after training', modality='may')
        reviewed = refine_graph(graph, Reviewer(), self.trace)
        self.assertEqual(reviewed['edges'][0]['conditions'], 'after training')
        self.assertEqual(reviewed['edges'][0]['modality'], 'may')

    def test_reviewer_sees_authoritative_contract_and_source_quote(self):
        class TranscriptionReviewer(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_fact_editor':
                    result = super().ask(role, instruction, payload, schema, identifier)
                    result.facts[0].definition = 'An accidental competing definition.'
                    result.facts[0].source.definition = 'A different concept.'
                    validator(result)
                    return result
                if role == 'graph_fact_reviewer':
                    assert payload['proposed'][0]['definition'] == CONTRACTS['reduces']
                    assert payload['proposed'][0]['source']['definition'] == sample()['nodes'][0]['definition']
                    assert 'definition' not in payload['original']
                    assert payload['proposed'][0]['evidence'] == payload['original']['evidence']
                return super().ask(role, instruction, payload, schema, identifier, validator)
        graph = refine_graph(sample(), TranscriptionReviewer(), self.trace)
        self.assertEqual(graph['edges'][0]['definition'], CONTRACTS['reduces'])

    def test_editor_cannot_replace_source_evidence_with_invented_quote(self):
        class InventedEvidence(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                result = super().ask(role, instruction, payload, schema, identifier)
                if role == 'graph_fact_editor':
                    result.facts[0].evidence = 'An invented quote.'
                if validator:
                    validator(result)
                return result
        with self.assertRaisesRegex(ValueError, 'exact continuous quote'):
            refine_graph(sample(), InventedEvidence(), self.trace)

    def test_wrong_direction_cannot_publish_after_bounded_repair(self):
        model = Reviewer(bad_direction=True)
        with self.assertRaisesRegex(ValueError, 'semantic review unresolved'):
            refine_graph(sample(), model, self.trace)
        self.assertEqual(model.roles.count('graph_fact_editor'), 2)
        self.assertEqual(json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())['status'], 'blocked')
        self.assertFalse((self.trace.directory/'artifacts/graph.json').exists())

    def test_document_claim_cannot_be_silently_dropped(self):
        with self.assertRaises(ValueError):
            refine_graph(sample(), Reviewer(omit=True), self.trace)

    def test_service_failure_is_not_a_valid_graph(self):
        with self.assertRaises(ModelServiceError):
            refine_graph(sample(), Reviewer(fail=True), self.trace)
        self.assertEqual(json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())['status'], 'blocked')

    def test_final_graph_failure_overrides_passing_item_reviews(self):
        with self.assertRaisesRegex(ValueError, 'Final graph review unresolved'):
            refine_graph(sample(), Reviewer(final_bad=True), self.trace)
        self.assertTrue((self.trace.directory/'artifacts/graph_review_blocked.json').exists())
        self.assertFalse((self.trace.directory/'artifacts/graph.json').exists())
        report = json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())
        self.assertEqual(report['status'], 'blocked')

    def test_rejected_background_is_excluded_without_losing_document_claim(self):
        class RejectBackground(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                self.bad_direction = payload.get('original', {}).get('origin') == 'background'
                return super().ask(role, instruction, payload, schema, identifier, validator)
        original = sample()
        original['edges'].append(dict(original['edges'][0], id='background_1', origin='background'))
        graph = refine_graph(original, RejectBackground(), self.trace)
        require_quality(graph, required=True)
        self.assertEqual([e['id'] for e in graph['edges']], ['edge_1'])
        self.assertEqual(graph['quality']['excluded_background'], 1)
        report = json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())
        self.assertEqual(report['excluded_background'][0]['id'], 'background_1')

    def test_unsupported_isolate_remains_a_mention_not_fabricated_edge(self):
        class MentionReviewer(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if payload.get('attachment'):
                    if role == 'graph_fact_editor':
                        result = schema.model_validate(dict(facts=[], reason='Only a mention'))
                    else:
                        result = schema.model_validate(dict(facts=[], omission_valid=True, reason='Only a mention'))
                    if validator:
                        validator(result)
                    return result
                return super().ask(role, instruction, payload, schema, identifier, validator)
        original = sample()
        original['nodes'].append(dict(id=concept_id('topic'), label='topic', definition='A mentioned topic.', origin='document'))
        graph = refine_graph(original, MentionReviewer(), self.trace)
        self.assertEqual(len(graph['nodes']), 2)
        self.assertEqual(len(graph['edges']), 1)
        self.assertEqual(graph['provenance']['unlinked_mentions'][0]['label'], 'topic')
        self.assertNotIn('definition', graph['provenance']['unlinked_mentions'][0])

    def test_unknown_merge_target_rejected(self):
        with self.assertRaises(ValueError):
            refine_graph(sample(), Reviewer(dangling_merge=True), self.trace)

    def test_isolated_noun_does_not_trigger_a_fabricated_attachment(self):
        class ReversedAttachment(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_endpoint_roles':
                    return schema.model_validate(dict(valid=False, reason='The resource is not the agent.'))
                if role == 'graph_fact_editor' and payload.get('attachment'):
                    result = schema.model_validate(dict(facts=[dict(anchor_role='source',
                        other=dict(label='quantization', definition='Reduction of numerical precision.'),
                        relation='uses', definition=CONTRACTS['uses'], conditions=None, modality=None,
                        evidence='Quantization reduces memory requirements.')], reason='Proposed attachment'))
                    if validator:
                        validator(result)
                    return result
                return super().ask(role, instruction, payload, schema, identifier, validator)
        original = sample()
        original['nodes'].append(dict(id=concept_id('topic'), label='topic',
            definition='A mentioned resource.', origin='document'))
        graph = refine_graph(original, ReversedAttachment(), self.trace)
        self.assertEqual(len(graph['edges']), 1)
        self.assertEqual(graph['provenance']['unlinked_mentions'][0]['label'], 'topic')
        report = json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())
        self.assertEqual(report['role_checks'], [])
        self.assertEqual(report['unresolved_attachments'], [])

    def test_short_relation_schema_rejects_sentence_labels(self):
        edge = dict(source=dict(label='a', definition='A.'), target=dict(label='b', definition='B.'),
                    relation='shifts_information_source_from_internal_to_external', definition='SOURCE uses TARGET.')
        with self.assertRaises(ValueError):
            Fact.model_validate(edge)

    def test_one_original_fact_cannot_expand_into_unrelated_quote_facts(self):
        fact = dict(source=dict(label='a', definition='A.'), target=dict(label='b', definition='B.'),
                    relation='uses', definition=CONTRACTS['uses'], conditions=None, modality=None, evidence='A uses B.')
        with self.assertRaises(ValueError):
            SingleFactPlan.model_validate(dict(facts=[fact, fact], reason='Two claims from the same quote'))

    def test_review_limits_are_configurable_and_validated(self):
        with self.assertRaises(ValueError):
            ReviewPolicy(repair_attempts=0)
        model = Reviewer(bad_direction=True)
        with self.assertRaisesRegex(ValueError, 'semantic review unresolved'):
            refine_graph(sample(), model, self.trace, policy=ReviewPolicy(repair_attempts=1))
        self.assertEqual(model.roles.count('graph_fact_editor'), 1)

    def test_similar_definitions_merge_only_after_both_identity_checks(self):
        class AliasReviewer(Reviewer):
            def __init__(self, agrees):
                super().__init__()
                self.agrees = agrees

            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role.startswith('graph_alias_'):
                    same = role == 'graph_alias_identity' or self.agrees
                    return schema.model_validate(dict(same_concept=same, same_scope=same,
                        distinction=None if same else 'Different scope', reason='Identity check'))
                return super().ask(role, instruction, payload, schema, identifier, validator)
        for agree in (False, True):
            with self.subTest(agreement=agree):
                original = sample()
                alias = dict(original['nodes'][1], id=concept_id('memory need'), label='memory need')
                original['nodes'].append(alias)
                original['edges'].append(dict(original['edges'][0], id='edge_2', target=alias['id']))
                graph = refine_graph(original, AliasReviewer(agree), self.trace)
                self.assertEqual(len(graph['nodes']), 2 if agree else 3)
                self.assertEqual(len(graph['edges']), 1 if agree else 2)

    def test_loader_enforces_required_review_and_detects_tampering(self):
        from pipeline.explorer import load_snapshot
        directory = self.trace.directory
        self.trace.save('manifest.json', dict(status='completed', graph_quality_required=True))
        self.trace.save('artifacts/graph.json', sample())
        with self.assertRaisesRegex(ValueError, 'missing or incomplete'):
            load_snapshot(directory)
        graph = refine_graph(sample(), Reviewer(), self.trace)
        self.trace.save('artifacts/graph.json', graph)
        self.assertEqual(len(load_snapshot(directory).graph['edges']), 1)
        graph['nodes'][0]['definition'] = 'A changed meaning.'
        self.trace.save('artifacts/graph.json', graph)
        with self.assertRaisesRegex(ValueError, 'changed after'):
            load_snapshot(directory)

    def test_old_graphs_can_be_inspected_but_cannot_claim_review(self):
        require_quality(sample())
        with self.assertRaises(ValueError):
            require_quality(sample(), required=True)


if __name__ == '__main__':
    unittest.main()
