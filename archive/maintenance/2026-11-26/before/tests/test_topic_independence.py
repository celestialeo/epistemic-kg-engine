"""Topic-independent prompts, repairs, source scope, and bounded review context."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest

from pipeline.graph_quality import ReviewPolicy, refine_graph, require_quality
from pipeline.graph_view import concept_id
from pipeline.ingest import split_document
from pipeline.extraction import Extraction, grounded_records
from pipeline.registry import RelationRegistry
from pipeline.registry import ConceptRegistry
from pipeline.identity import concept_key
from pipeline.trace import Trace
from tests.test_graph_quality import Reviewer, sample


class TopicIndependenceTests(unittest.TestCase):
    def test_replacement_scope_uses_the_resulting_assertions(self):
        from pipeline.graph_quality import SourceRevision, revision_view
        original = [dict(id='old', source='heater', label='affects', target='temperature'),
                    dict(id='keep', source='fan', label='moves', target='air')]
        revision = SourceRevision.model_validate(dict(remove_ids=['old'], facts=[dict(
            source=dict(label='heater', definition='A device supplying heat.'),
            target=dict(label='temperature', definition='A measure of thermal state.'),
            relation='raises', definition='SOURCE increases TARGET.', conditions='when operating',
            modality='can', evidence='The operating heater can raise temperature.')], reason='Clarify the supported change.'))
        view = revision_view(original, revision)
        self.assertEqual([e['id'] for e in view['removed_assertions']], ['old'])
        result = view['resulting_assertions']
        self.assertEqual([(e['source'],e['label'],e['target']) for e in result],
            [('fan','moves','air'),('heater','raises','temperature')])
        self.assertEqual(result[1]['conditions'], 'when operating')
        self.assertEqual(result[1]['modality'], 'can')
        self.assertNotIn('evidence', result[1])
        self.assertEqual(original[0]['label'], 'affects')

    def test_verified_repair_can_correct_inherited_scope(self):
        class CorrectScope(Reviewer):
            def ask(self, role, *args, **kwargs):
                result = super().ask(role, *args, **kwargs)
                if role == 'graph_fact_editor':
                    result.facts[0].conditions = 'under the stated conditions'
                    result.facts[0].modality = 'may'
                return result
        graph = sample()
        text = 'Under the stated conditions, quantization may reduce memory requirements.'
        graph['provenance'].update(text=text, chunks=[dict(id='c1', text=text, start=0, end=len(text))])
        graph['edges'][0].update(evidence=text, conditions='at any time', modality='necessarily')
        result = refine_graph(graph, CorrectScope(), self.trace)
        self.assertEqual(result['edges'][0]['conditions'], 'under the stated conditions')
        self.assertEqual(result['edges'][0]['modality'], 'may')

    def test_source_blind_reading_is_separate_from_evidence_verification(self):
        class IndependentReading(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_displayed_fact_reader':
                    assert 'evidence' not in payload and 'original' not in payload
                    assert 'definition' not in payload and isinstance(payload['source'], dict)
                    return schema.model_validate(dict(meaning='The displayed source reduces the displayed target.'))
                return super().ask(role, instruction, payload, schema, identifier, validator)
        refine_graph(sample(), IndependentReading(), self.trace)
        report = json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())
        self.assertEqual(report['relationships'][0]['displayed_readings'][0]['meaning'],
            'The displayed source reduces the displayed target.')

    def test_direct_fallback_keeps_checks_required_and_restores_settings(self):
        from pipeline.models import OutputLimitError
        class ExhaustedReasoning(Reviewer):
            think = False
            options = dict(num_ctx=8192, num_predict=4096)
            reject = False

            def __init__(self):
                super().__init__()
                self.reasoning_attempts = {}

            def ask(self, role, *args, **kwargs):
                if role in {'graph_source_coverage', 'graph_final_reviewer'} and self.think:
                    self.reasoning_attempts[role] = self.reasoning_attempts.get(role, 0) + 1
                    raise OutputLimitError('Reasoning budget exhausted')
                result = super().ask(role, *args, **kwargs)
                if role == 'graph_final_reviewer' and self.reject:
                    result.consistent = False
                    result.issues = ['A contradictory assertion remains.']
                return result
        for reject in (False, True):
            model = ExhaustedReasoning()
            model.reject = reject
            original = sample()
            source = original['provenance']['text']
            source = source + ' ' + source
            original['provenance'].update(text=source, chunks=[dict(id='c1', text=source, start=0, end=len(source))])
            if reject:
                with self.assertRaisesRegex(ValueError, 'Final graph review unresolved'):
                    refine_graph(original, model, self.trace, policy=ReviewPolicy(reasoning=True))
            else:
                require_quality(refine_graph(original, model, self.trace, policy=ReviewPolicy(reasoning=True)), required=True)
            self.assertFalse(model.think)
            self.assertEqual(model.options['num_predict'], 4096)
            self.assertEqual(model.reasoning_attempts['graph_source_coverage'], 1)
            report = json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())
            self.assertEqual({r['role'] for r in report['direct_fallbacks']}, {'graph_source_coverage','graph_final_reviewer'})
        with self.assertRaises(OutputLimitError):
            refine_graph(sample(), ExhaustedReasoning(), self.trace, policy=ReviewPolicy(reasoning=True, reasoning_fallback=False))

    def test_resumed_output_limit_stays_rejected_and_changed_budget_retries(self):
        from unittest.mock import Mock
        from pipeline.models import Models, OutputLimitError
        from pipeline.graph_quality import Endpoint
        details = dict(installed_models=dict(models=[dict(model='local', digest='same-model')]))
        self.trace.save('artifacts/environment.json', dict(model_details=details))
        first = Models(self.trace, 'local', 'embedding', 'http://127.0.0.1:11434')
        first.client = Mock()
        first.client.chat.return_value.model_dump.return_value = dict(done_reason='length', message=dict(content='{}'))
        with self.assertRaises(OutputLimitError):
            first.ask('check', 'Verify the concept', {}, Endpoint, 'one')
        directory = self.trace.directory
        self.trace.close()
        resumed_trace = Trace(Path(self.temp.name)/'resumed', 'resumed')
        self.addCleanup(resumed_trace.close)
        resumed = Models(resumed_trace, 'local', 'embedding', 'http://127.0.0.1:11434')
        resumed.details = details
        resumed.client = Mock()
        resumed.load_cache(directory)
        with self.assertRaises(OutputLimitError):
            resumed.ask('check', 'Verify the concept', {}, Endpoint, 'two')
        resumed.client.chat.assert_not_called()
        resumed.options['num_predict'] += 1
        resumed.client.chat.return_value.model_dump.return_value = dict(done_reason='stop',
            message=dict(content=json.dumps(dict(label='temperature', definition='A measure of thermal state.'))))
        self.assertEqual(resumed.ask('check', 'Verify the concept', {}, Endpoint, 'three').label, 'temperature')
        resumed.client.chat.assert_called_once()

    def test_node_context_includes_other_mentions_even_with_incident_evidence(self):
        from pipeline.graph_quality import node_context
        graph = sample()
        label = graph['nodes'][0]['label']
        passages = [f'{label} appears in context {i}.' for i in range(12)]
        graph['provenance']['chunks'] = [dict(id=str(i), text=p) for i,p in enumerate(passages)]
        graph['edges'][0]['evidence'] = passages[0]
        context = node_context([graph['nodes'][0]], graph, limit=3)
        self.assertIn(passages[0], context)
        self.assertIn(passages[-1], context)
        self.assertEqual(len(context.split('\n\n')), 3)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.trace = Trace(Path(self.temp.name)/'run', 'generic-test')
        self.addCleanup(self.trace.close)

    def test_inference_modules_do_not_embed_benchmark_subjects(self):
        notebook = json.loads((Path(__file__).resolve().parents[1]/'261273237.ipynb').read_text(encoding='utf-8'))
        # CLI aliases and the notebook's default demo select inputs; they never
        # determine concepts, relationships or grading for those inputs.
        selection_only = {'pipeline.cli', 'pipeline.submission'}
        forbidden = ('quantization', 'backpropagation', 'transformer', 'regularization',
                     'neuron', 'synapse', 'synaptic', 'receptor', 'water_cycle', 'ai_test',
                     'external documents', 'internal parameters', 'dynamic updating')
        checked = 0
        for cell in notebook['cells']:
            module = cell.get('metadata', {}).get('module')
            if not module or module in selection_only:
                continue
            tree = ast.parse(''.join(cell['source']).split('\n', 1)[1])
            constants = '\n'.join(node.value.casefold() for node in ast.walk(tree)
                                  if isinstance(node, ast.Constant) and isinstance(node.value, str))
            for term in forbidden:
                self.assertNotIn(term, constants, (module, term))
            checked += 1
        self.assertGreater(checked, 20)

    def test_both_live_fixtures_have_three_lossless_paragraphs(self):
        root = Path(__file__).resolve().parents[1]
        original_words = len((root/'data/ai_test.txt').read_text().split())
        for name in ('ai_three_paragraphs', 'neuron_three_paragraphs'):
            text = (root/'data/validation'/f'{name}.txt').read_text(encoding='utf-8')
            paragraphs, chunks = split_document(text, 85, self.trace)
            self.assertEqual(len(paragraphs), 3)
            self.assertTrue(2.5*original_words <= len(text.split()) <= 4*original_words)
            self.assertEqual(' '.join(text.split()), ' '.join(' '.join(c['text'] for c in chunks).split()))

    def test_normalization_does_not_guess_singular_forms_or_corrupt_terms(self):
        for word in ('nucleus', 'analysis', 'gas', 'status', 'species', 'physics', 'news', 'parameters'):
            self.assertEqual(concept_key(word), word)
        self.assertEqual(concept_key('MEMBRANE-POTENTIAL'), 'membrane potential')
        self.assertNotEqual(concept_key('cell'), concept_key('cells'))

    def test_identity_retrieval_bounds_model_work_without_merging_candidates(self):
        class NoAlias:
            batch_size = 2
            identity_candidates = 3
            calls = 0

            def ask(inner, role, instruction, payload, schema, identifier, validator=None):
                inner.calls += 1
                self.assertEqual(role, 'concept_alias_resolver')
                result = schema.model_validate(dict(canonical_name=None, reason='Distinct referents',
                                                    search_uncertain=False))
                if validator:
                    validator(result)
                return result
        model = NoAlias()
        registry = ConceptRegistry(model, self.trace)
        available = {f'object {i}':dict(name=f'object {i}', definition=f'A distinct item {i}.') for i in range(30)}
        result = registry._semantic_match(dict(name='new object', definition='A different item.'), available, '', 'new')
        self.assertIsNone(result)
        self.assertEqual(model.calls, 2)
        self.assertEqual(len(available), 30)

    def test_one_wrong_predicate_does_not_discard_healthy_sentence_records(self):
        text = 'A depot contains a package and receives a request.'
        def endpoint(name):
            return dict(name=name, definition='The named '+name+'.', kind='entity')
        registry = RelationRegistry(None, self.trace)
        healthy = dict(source=endpoint('depot'), target=endpoint('package'), relation='contains',
            relation_definition=registry.entries['contains']['definition'], evidence=text)
        invalid = dict(source=endpoint('depot'), target=endpoint('request'), relation='acts_on',
            relation_definition=registry.entries['acts_on']['definition'], evidence=text)
        extracted = Extraction.model_validate(dict(unit_kind='core_statement', concepts=[],
            claims=[dict(text=text, evidence=text)], relations=[healthy,invalid], confidence=.9, reason='Fixture'))
        class Repair:
            def ask(inner, role, instruction, payload, schema, identifier, validator=None):
                self.assertEqual(role, 'extractor_quote_repair')
                self.assertEqual(len(payload['failed_records']), 1)
                bad = payload['failed_records'][0]
                self.assertEqual(bad['index'], 1)
                repaired = dict(invalid, relation='receives', relation_definition='SOURCE receives TARGET.')
                result = schema.model_validate(dict(records=[dict(collection='relations', index=1,
                    record=repaired, reason='The original predicate assigned incompatible roles.')]))
                if validator:
                    validator(result)
                return result
        unit = dict(id='sentence', text=text, start=0, end=len(text))
        accepted, unresolved = grounded_records(extracted, unit, unit, Repair(), registry, self.trace)
        self.assertFalse(unresolved)
        self.assertEqual([row[1].relation for row in accepted['relations']], ['contains','receives'])
        self.assertIs(accepted['relations'][0][1], extracted.relations[0])
        self.assertEqual(len(accepted['claims']), 1)

    def test_unseen_topic_can_repair_endpoint_without_sentence_template(self):
        class RepairReviewer(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_fact_editor':
                    result = super().ask(role, instruction, payload, schema, identifier)
                    result.facts[0].source.label = 'road resurfacing'
                    result.facts[0].source.definition = 'Replacement of a road surface.'
                    if validator:
                        validator(result)
                    return result
                if role == 'graph_fact_reviewer':
                    result = super().ask(role, instruction, payload, schema, identifier, validator)
                    result.facts[0].endpoints_valid = payload['proposed'][0]['source']['label'] == 'road resurfacing'
                    return result
                return super().ask(role, instruction, payload, schema, identifier, validator)
        graph = sample()
        graph['nodes'][0].update(label='road surface', definition='The upper layer of a road.')
        graph['nodes'][1].update(label='surface roughness', definition='Unevenness of a road surface.')
        quote = 'Surface roughness is reduced when the road is resurfaced.'
        graph['edges'][0].update(evidence=quote, label='reduces')
        graph['provenance'].update(text=quote, chunks=[dict(id='c1', text=quote, start=0, end=len(quote))])
        # The old, incorrect source is a background node so it is excluded once
        # no retained assertion uses it, rather than invoking mention recovery.
        graph['nodes'][0]['origin'] = 'background'
        reviewed = refine_graph(graph, RepairReviewer(), self.trace)
        require_quality(reviewed, required=True)
        names = {n['id']:n['label'] for n in reviewed['nodes']}
        self.assertEqual(names[reviewed['edges'][0]['source']], 'road resurfacing')
        self.assertEqual(names[reviewed['edges'][0]['target']], 'surface roughness')
        self.assertEqual(reviewed['edges'][0]['evidence'], quote)

    def test_repeated_quote_keeps_its_source_occurrence(self):
        graph = sample()
        quote = graph['provenance']['text']
        graph['provenance']['text'] = quote + '\n\n' + quote
        start = len(quote)+2
        graph['provenance']['chunks'] = [dict(id='first',text=quote,start=0,end=len(quote)),
            dict(id='second',text=quote,start=start,end=start+len(quote))]
        graph['edges'][0].update(chunk_id='second',evidence_start=start,evidence_end=start+len(quote))
        reviewed = refine_graph(graph, Reviewer(), self.trace)
        self.assertEqual(reviewed['edges'][0]['evidence_start'], start)
        self.assertEqual(reviewed['edges'][0]['chunk_id'], 'second')

    def test_missing_source_claim_is_recovered_only_after_independent_review(self):
        class CoverageReviewer(Reviewer):
            def __init__(self, supported, progress=True):
                super().__init__()
                self.supported = supported
                self.progress = progress

            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_source_coverage':
                    assert len(payload['sentences']) == 1
                    complete = len(payload['edges']) == 2
                    value = dict(complete=complete, issues=[] if complete else ['The cooling assertion is missing.'], bad_edge_ids=[],
                        sentences=[dict(index=i, claims=[dict(assertion=s,
                            edge_ids=[payload['edges'][min(int('Cooling' in s),len(payload['edges'])-1)]['id']] if complete or 'Cooling' not in s else [],
                            represented=complete or 'Cooling' not in s, reason='Covered' if complete or 'Cooling' not in s else 'Missing cooling')],
                            no_claim_reason=None) for i,s in enumerate(payload['sentences'])])
                elif role == 'graph_source_repair':
                    value = dict(remove_ids=[], facts=[dict(source=dict(label='cooling',definition='Removal of heat.'),
                        target=dict(label='temperature',definition='A measure of thermal state.'), relation='reduces',
                        definition='SOURCE decreases the amount or degree of TARGET.', conditions=None, modality=None,
                        evidence='Cooling reduces temperature.')], reason='Recover the omitted source assertion.')
                elif role == 'graph_source_fact_verifier':
                    assert payload['proposed']['source']['definition'] == 'Removal of heat.'
                    value = dict(index=0,
                        literal_meaning='Cooling reduces temperature.', faithful=True, supported=self.supported,
                        direction_valid=True, label_matches_contract=True, endpoints_valid=True, qualifications_preserved=True,
                        reason='Supported' if self.supported else 'Unsupported repair')
                elif role == 'graph_source_repair_verifier':
                    assert self.supported
                    assert 'edges' not in payload and 'nodes' not in payload
                    assert len(payload['resulting_assertions']) == 2
                    assert payload['removed_assertions'] == []
                    value = dict(omission_valid=True, makes_progress=self.progress, reason='Independent scope check')
                else:
                    return super().ask(role, instruction, payload, schema, identifier, validator)
                result = schema.model_validate(value)
                if validator:
                    validator(result)
                return result
        for supported, progress in ((False,True),(True,True),(True,False)):
            with self.subTest(supported=supported, progress=progress):
                graph = sample()
                graph['nodes'].append(dict(id=concept_id('cooling'), label='cooling',
                    definition='A wrong unused definition.', kind='concept', origin='document'))
                text = graph['provenance']['text'] + ' Cooling reduces temperature.'
                graph['provenance'].update(text=text, chunks=[dict(id='c1',text=text,start=0,end=len(text))])
                if supported and progress:
                    reviewed = refine_graph(graph, CoverageReviewer(True), self.trace)
                    self.assertEqual(len(reviewed['edges']), 2)
                    self.assertEqual(reviewed['edges'][0]['id'], 'edge_1')
                    self.assertEqual(reviewed['edges'][1]['evidence'], 'Cooling reduces temperature.')
                    self.assertEqual(next(n['definition'] for n in reviewed['nodes'] if n['label']=='cooling'), 'Removal of heat.')
                    require_quality(reviewed, required=True)
                else:
                    with self.assertRaisesRegex(ValueError, 'Final graph review unresolved'):
                        refine_graph(graph, CoverageReviewer(supported, progress), self.trace)
                    report = json.loads((self.trace.directory/'artifacts/graph_quality.json').read_text())
                    self.assertEqual(len(report['source_repairs']), 2)
                    self.assertTrue(all(not r['applied'] for r in report['source_repairs']))

    def test_correct_definition_cannot_rescue_a_misleading_predicate_label(self):
        class MisleadingLabel(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                result = super().ask(role, instruction, payload, schema, identifier, validator)
                if role == 'graph_fact_reviewer':
                    result.facts[0].label_matches_contract = False
                    result.facts[0].reason = 'The short label implies the opposite participant direction.'
                return result
        with self.assertRaisesRegex(ValueError, 'semantic review unresolved'):
            refine_graph(sample(), MisleadingLabel(), self.trace)

    def test_node_repair_preserves_individually_verified_decisions(self):
        class PartialReviewer(Reviewer):
            def __init__(self):
                super().__init__()
                self.reviews = 0

            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                result = super().ask(role, instruction, payload, schema, identifier, validator)
                if role == 'graph_node_editor' and self.reviews:
                    result.nodes[0].definition = 'An unrelated replacement definition.'
                if role == 'graph_node_reviewer':
                    if self.reviews:
                        assert payload['proposed']['nodes'][0]['definition'] == sample()['nodes'][0]['definition']
                    result.nodes[self.reviews].valid = True
                    result.nodes[1-self.reviews].valid = False
                    self.reviews += 1
                return result
        model = PartialReviewer()
        graph = refine_graph(sample(), model, self.trace, policy=ReviewPolicy(node_batch_size=2))
        self.assertEqual(model.reviews, 2)
        self.assertEqual(graph['nodes'][0]['definition'], sample()['nodes'][0]['definition'])

    def test_concise_document_assertion_still_requires_context_review(self):
        from pipeline.graph_quality import CONTRACTS
        original = sample()
        original['edges'][0].update(label='reduces', definition=CONTRACTS['reduces'])
        model = Reviewer()
        graph = refine_graph(original, model, self.trace)
        self.assertIn('graph_fact_editor', model.roles)
        self.assertIn('graph_fact_reviewer', model.roles)
        self.assertEqual(graph['edges'][0]['target'], original['edges'][0]['target'])
        rejecting = Reviewer(bad_direction=True)
        with self.assertRaisesRegex(ValueError, 'semantic review unresolved'):
            refine_graph(original, rejecting, self.trace)
        self.assertEqual(rejecting.roles.count('graph_fact_editor'), 2)
        self.assertEqual(rejecting.roles.count('graph_fact_reviewer'), 1)

    def test_coverage_cannot_skip_a_sentence_or_claim_coverage_without_an_edge(self):
        class EmptyCoverage(Reviewer):
            def __init__(self, skip):
                super().__init__()
                self.skip = skip

            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_source_coverage':
                    result = schema.model_validate(dict(complete=True, issues=[], bad_edge_ids=[], sentences=[] if self.skip else [
                        dict(index=0, claims=[dict(assertion=payload['source'], edge_ids=[],
                            represented=True, reason='A word appears in the source')], no_claim_reason=None)]))
                    validator(result)
                    return result
                return super().ask(role, instruction, payload, schema, identifier, validator)
        for skip in (True, False):
            with self.subTest(skip=skip), self.assertRaises(ValueError):
                refine_graph(sample(), EmptyCoverage(skip), self.trace)

    def test_background_counterexample_overrides_a_positive_valid_flag(self):
        class Counterexample(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_background_challenge':
                    return schema.model_validate(dict(valid=True, counterexample='An allowed case violates the claim.',
                        required_qualification=None, reason='The assertion is too broad.'))
                return super().ask(role, instruction, payload, schema, identifier, validator)
        original = sample()
        original['edges'].append(dict(original['edges'][0], id='background_1', origin='background'))
        graph = refine_graph(original, Counterexample(), self.trace)
        self.assertEqual([e['id'] for e in graph['edges']], ['edge_1'])
        self.assertEqual(graph['quality']['excluded_background'], 1)

    def test_failed_batch_isolates_only_unverified_nodes_and_still_requires_review(self):
        class IsolatedReviewer(Reviewer):
            def __init__(self, valid):
                super().__init__()
                self.valid = valid
                self.isolated = []

            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_node_repair':
                    node = payload['node']
                    self.isolated.append(node['id'])
                    return schema.model_validate(dict(nodes=[dict(id=node['id'], label=node['label'],
                        definition=node['definition'], merge_into=None, reason='Keep distinct')]))
                if role == 'graph_node_repair_verifier':
                    assert 'reason' not in payload['proposed']['nodes'][0]
                    return schema.model_validate(dict(nodes=[dict(id=payload['node']['id'],
                        valid=self.valid, reason='Source review')]))
                result = super().ask(role, instruction, payload, schema, identifier, validator)
                if role == 'graph_node_reviewer':
                    result.nodes[1].valid = False
                return result
        for valid in (False, True):
            with self.subTest(valid=valid):
                model = IsolatedReviewer(valid)
                if valid:
                    require_quality(refine_graph(sample(), model, self.trace, policy=ReviewPolicy(node_batch_size=2)), required=True)
                else:
                    with self.assertRaisesRegex(ValueError, 'isolated repair'):
                        refine_graph(sample(), model, self.trace, policy=ReviewPolicy(node_batch_size=2))
                self.assertEqual(set(model.isolated), {sample()['nodes'][1]['id']})
                self.assertEqual(len(model.isolated), 1 if valid else 2)

    def test_review_reasoning_is_configurable_and_restores_caller_settings(self):
        class ThinkingReviewer(Reviewer):
            think = False

            def ask(self, *args, **kwargs):
                expected = self.expected and args[0] in {'graph_source_coverage','graph_final_reviewer'}
                assert self.think == expected
                return super().ask(*args, **kwargs)
        for enabled, fail in ((False,False),(True,False),(True,True)):
            with self.subTest(enabled=enabled, fail=fail):
                model = ThinkingReviewer(fail=fail)
                model.expected = enabled
                if fail:
                    from pipeline.models import ModelServiceError
                    with self.assertRaises(ModelServiceError):
                        refine_graph(sample(), model, self.trace, policy=ReviewPolicy(reasoning=enabled))
                else:
                    refine_graph(sample(), model, self.trace, policy=ReviewPolicy(reasoning=enabled))
                self.assertFalse(model.think)

    def test_node_merge_cannot_collapse_an_existing_relationship(self):
        class MergeNeighbors(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_node_editor' and payload['existing']:
                    node, other = payload['nodes'][0], payload['existing'][0]
                    result = schema.model_validate(dict(nodes=[dict(id=node['id'], label=other['label'],
                        definition=other['definition'], merge_into=other['id'], reason='Proposed identity')]))
                    validator(result)
                    return result
                return super().ask(role, instruction, payload, schema, identifier, validator)
        with self.assertRaisesRegex(ValueError, 'self-link'):
            refine_graph(sample(), MergeNeighbors(), self.trace, policy=ReviewPolicy(node_batch_size=1))

    def test_alias_pass_cannot_collapse_connected_participants(self):
        class IdenticalAliases(Reviewer):
            alias_calls = 0

            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role.startswith('graph_alias_'):
                    self.alias_calls += 1
                    return schema.model_validate(dict(same_concept=True, same_scope=True,
                        distinction=None, reason='Same definition'))
                return super().ask(role, instruction, payload, schema, identifier, validator)
        original = sample()
        original['nodes'][1]['definition'] = original['nodes'][0]['definition']
        model = IdenticalAliases()
        graph = refine_graph(original, model, self.trace)
        self.assertEqual(model.alias_calls, 0)
        self.assertEqual(len(graph['nodes']), 2)
        self.assertNotEqual(graph['edges'][0]['source'], graph['edges'][0]['target'])

    def test_optional_background_output_limit_is_withheld_but_source_limit_blocks(self):
        from pipeline.models import OutputLimitError
        class LimitedReviewer(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == self.limited_role:
                    raise OutputLimitError('Budget exhausted')
                return super().ask(role, instruction, payload, schema, identifier, validator)
        original = sample()
        original['edges'].append(dict(original['edges'][0], id='background_1', origin='background'))
        model = LimitedReviewer()
        model.limited_role = 'graph_background_challenge'
        graph = refine_graph(original, model, self.trace)
        self.assertEqual(len(graph['edges']), 1)
        self.assertEqual(graph['quality']['excluded_background'], 1)
        model.limited_role = 'graph_source_coverage'
        with self.assertRaises(OutputLimitError):
            refine_graph(original, model, self.trace)

    def test_reasoning_budget_restores_model_options_on_error(self):
        from pipeline.models import ModelServiceError
        class BudgetReviewer(Reviewer):
            think = False
            options = dict(num_ctx=8192, num_predict=4096, temperature=0)

            def ask(self, role, *args, **kwargs):
                if role == 'graph_source_coverage':
                    assert self.think
                    assert 4096 < self.options['num_predict'] <= 6144
                    raise ModelServiceError('Unavailable')
                return super().ask(role, *args, **kwargs)
        model = BudgetReviewer()
        before = dict(model.options)
        with self.assertRaises(ModelServiceError):
            refine_graph(sample(), model, self.trace, policy=ReviewPolicy(reasoning=True, reasoning_output_tokens=6144))
        self.assertEqual(model.options, before)
        self.assertFalse(model.think)

    def test_invalid_editor_response_enters_isolated_repair(self):
        from pipeline.models import ModelResponseError
        class SchemaFailure(Reviewer):
            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_node_editor':
                    raise ModelResponseError('Repeated invalid merge')
                if role == 'graph_node_repair':
                    n = payload['node']
                    return schema.model_validate(dict(nodes=[dict(id=n['id'], label=n['label'],
                        definition=n['definition'], merge_into=None, reason='Retain the source concept')]))
                if role == 'graph_node_repair_verifier':
                    return schema.model_validate(dict(nodes=[dict(id=payload['node']['id'], valid=True, reason='Verified')]))
                return super().ask(role, instruction, payload, schema, identifier, validator)
        require_quality(refine_graph(sample(), SchemaFailure(), self.trace), required=True)

    def test_source_and_consistency_reviews_are_bounded_and_cover_every_edge(self):
        graph = sample()
        graph['nodes'], graph['edges'] = [], []
        chunks = []
        for i in range(5):
            text = f'Process{i} reduces property{i}.'
            source, target = f'process{i}', f'property{i}'
            graph['nodes'].extend([dict(id=concept_id(name), label=name,
                definition=f'The distinct referent {name}.', kind='concept', origin='document')
                for name in (source,target)])
            graph['edges'].append(dict(id=f'e{i}', source=concept_id(source), target=concept_id(target),
                label='reduces', origin='document', evidence=text, chunk_id=f'c{i}'))
            chunks.append(dict(id=f'c{i}', text=text))
        graph['provenance']['text'] = '\n\n'.join(c['text'] for c in chunks)
        for c in chunks:
            c['start'] = graph['provenance']['text'].index(c['text'])
            c['end'] = c['start']+len(c['text'])
        graph['provenance']['chunks'] = chunks
        class BoundedReviewer(Reviewer):
            def __init__(self):
                super().__init__()
                self.covered = set()
                self.sources = []

            def ask(self, role, instruction, payload, schema, identifier, validator=None):
                if role == 'graph_node_editor':
                    assert len(payload['existing']) <= 2
                    assert len(payload['source']) < len(graph['provenance']['text'])
                if role == 'graph_alias_identity' or role == 'graph_alias_verification':
                    return schema.model_validate(dict(same_concept=False, same_scope=False,
                        distinction='Different referents', reason='Keep separate'))
                if role == 'graph_source_coverage':
                    self.sources.append(payload['source'])
                    assert len(payload['edges']) == 1
                if role == 'graph_final_reviewer':
                    assert len(payload['edges']) <= 4
                    self.covered.update(e['id'] for e in payload['edges'])
                return super().ask(role, instruction, payload, schema, identifier, validator)
        reviewer = BoundedReviewer()
        reviewed = refine_graph(graph, reviewer, self.trace,
            policy=ReviewPolicy(node_batch_size=2, candidate_limit=2, edge_batch_size=2))
        self.assertEqual(reviewer.covered, {e['id'] for e in reviewed['edges']})
        self.assertEqual(reviewer.sources, [c['text'] for c in chunks])


if __name__ == '__main__':
    unittest.main()
