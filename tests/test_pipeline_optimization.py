"""Synthetic invariants for cost reductions, recovery and checkpoint validity."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch, Mock
from itertools import combinations

from ollama import ChatResponse, ResponseError
from pipeline.batching import ask_keyed
from pipeline.checkpoints import Checkpoints
from pipeline.evaluation import (Reconstruction, extract_evaluation_claims, ClaimMatch, validate_matches,
                                 select_one_to_one, compare_texts, OrderedClaims, ClaimAlignment)
from pipeline.models import Models, ModelServiceError, compact_payload
from pipeline.records import Record
from pipeline.registry import ConceptRegistry, RelationRegistry, FactIndex
from pipeline.retrieval import shortlist
from pipeline.trace import Trace


class Answer(Record):
    value: int


class OptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.trace = Trace(self.root / 'run', 'run')
        self.addCleanup(self.trace.close)

    def events(self):
        return [json.loads(line) for line in (self.trace.directory / 'events.jsonl').read_text().splitlines()]

    def test_atomic_artifact_retries_windows_lock_without_losing_previous_file(self):
        path=self.trace.text('artifacts/state.json','old')
        error=PermissionError('Sharing denied');error.winerror=32
        replace=os.replace
        attempts=[]
        def locked_then_ready(source,target):
            attempts.append(1)
            if len(attempts)<3:
                self.assertEqual(path.read_text(),'old')
                raise error
            replace(source,target)
        with patch('pipeline.trace.os.replace',side_effect=locked_then_ready),patch('pipeline.trace.time.sleep') as sleep:
            self.trace.text('artifacts/state.json','new')
        self.assertEqual(path.read_text(),'new')
        self.assertEqual(len(attempts),3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list],[0.1,0.2])
        self.assertEqual(self.trace.counts['artifact.replace_retry'],2)

    def test_permanent_windows_artifact_lock_is_bounded_and_keeps_old_state(self):
        path=self.trace.text('artifacts/state.json','old')
        error=PermissionError('Access denied');error.winerror=5
        with patch('pipeline.trace.os.replace',side_effect=error) as replace, \
             patch('pipeline.trace.time.sleep') as sleep,self.assertRaises(PermissionError):
            self.trace.text('artifacts/state.json','new')
        self.assertEqual(replace.call_count,6)
        self.assertAlmostEqual(sum(c.args[0] for c in sleep.call_args_list),3.1)
        self.assertEqual(path.read_text(),'old')
        self.assertEqual(next(path.parent.glob('state.json.*.tmp')).read_text(),'new')

    def test_evaluation_quote_retry_identifies_both_assignments_without_dropping_claims(self):
        class Model:
            def ask(self, role, instruction, payload, schema, entity_id, validator):
                result = schema.model_validate({'claims': [
                    {'text': 'Heat expands the rod.', 'evidence': 'Cooling contracts it.'},
                    {'text': 'Cooling contracts the rod.', 'evidence': 'Heat expands it.'}]})
                validator(result)
        with self.assertRaises(ValueError) as caught:
            extract_evaluation_claims('Heat expands it. Cooling contracts it.', Model(), 'fixture')
        message = str(caught.exception)
        self.assertIn('Heat expands the rod.', message)
        self.assertIn('Cooling contracts the rod.', message)
        self.assertIn('Check BOTH', message)
        self.assertIn('do not drop claims', message)

    def test_alignment_retry_identifies_reused_indices(self):
        matches = [ClaimMatch(original_index=0, reconstructed_index=1, reason='First'),
                   ClaimMatch(original_index=2, reconstructed_index=1, reason='Conflicting')]
        with self.assertRaisesRegex(ValueError, 'reconstructed 1 is already paired with original 0'):
            validate_matches(matches, 3, 3)

    def test_verified_matching_is_maximal_for_every_three_by_three_graph(self):
        possible = [(left, right) for left in range(3) for right in range(3)]
        for mask in range(1 << len(possible)):
            pairs = [pair for i, pair in enumerate(possible) if mask & (1 << i)]
            matches = [ClaimMatch(original_index=a, reconstructed_index=b, reason='Verified') for a,b in pairs]
            selected = select_one_to_one(matches)
            expected = max((size for size in range(4) if any(
                len({a for a,b in subset}) == len({b for a,b in subset}) == size
                for subset in combinations(pairs, size))), default=0)
            self.assertEqual(len(selected), expected, pairs)
            validate_matches(selected, 3, 3)
            self.assertTrue(all((m.original_index,m.reconstructed_index) in pairs for m in selected))

    def test_alignment_reviews_alternatives_before_selecting_and_retains_evidence(self):
        claims = OrderedClaims.model_validate({'claims': [
            {'text':'First claim', 'evidence':'first quote'}, {'text':'Second claim', 'evidence':'second quote'}]})
        pairs = [ClaimMatch(original_index=a,reconstructed_index=b,reason='Proposed')
                 for a,b in [(0,0),(0,1),(1,0)]]
        model = Mock()
        model.ask.return_value = ClaimAlignment(matches=pairs)
        reviews = [{**m.model_dump(),'accepted':i>0} for i,m in enumerate(pairs)]
        with patch('pipeline.evaluation.extract_evaluation_claims',return_value=claims), \
             patch('pipeline.evaluation.context_matches',return_value=(pairs[1:],reviews)) as check:
            result = compare_texts('Original passage','Reconstructed passage',model,'fixture')
        self.assertEqual(len(check.call_args.args[0]),3)
        self.assertEqual(result['matched_claim_count'],2)
        self.assertFalse(result['context_reviews'][0]['selected_for_alignment'])
        self.assertTrue(all(r['selected_for_alignment'] for r in result['context_reviews'][1:]))
        self.assertEqual(result['original_claims'][0]['evidence'],'first quote')
        self.assertEqual(model.ask.call_args.args[2]['original_claims'][0],dict(index=0,text='First claim'))

    def test_retrieval_bounds_work_and_prioritizes_matching_definitions(self):
        entries = [dict(name='unrelated ' + str(i), definition='different topic') for i in range(100)]
        target = dict(name='delta', definition='rate of change in temperature')
        selected = shortlist('temperature change rate', [*entries, target], 8)
        self.assertEqual(selected[0], target)
        self.assertEqual(len(selected), 8)

    def test_generation_requires_explicit_qualifier_decisions(self):
        from pipeline.extraction import Extraction
        from pipeline.debate import GraphLink
        source = Extraction.model_json_schema()['$defs']['Relation']
        background = GraphLink.model_json_schema()
        for schema in (source, background):
            self.assertIn('argument_qualifiers', schema['required'])
            self.assertIn('conditions', schema['required'])
            self.assertIn('modality', schema['required'])
        from pipeline.debate import DocumentVerdict
        review = DocumentVerdict.model_json_schema()
        self.assertEqual(list(review['properties'])[:2], ['qualified_reading', 'reason'])
        self.assertIn('qualified_reading', review['required'])

    def test_passage_planning_visits_all_source_and_checks_gaps_across_passages(self):
        from pipeline.gaps import collect_seeds
        visited = []
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            if role == 'passage_gap_planner':
                cid = payload['source']['id']; visited.append(cid)
                proposal = dict(concept=payload['anchors'][0], topic_id=payload['allowed_topics'][0]['id'],
                    gaps=[dict(question='Why ' + cid + '?', assumed_knowledge='A missing mechanism',
                               why_useful='Explains the stated process', source_chunk_ids=[cid])],
                    priority='high', reason='Needed explanation')
                value = dict(document_coverage='The source states an effect.', seeds=[proposal],
                    case_specific_unknowns=[dict(question='Which implementation in this case?',
                        reason='Unspecified', source_chunk_ids=[cid])], reason='Scope assessed')
                with self.assertRaises(ValueError):
                    schema.model_validate(dict(value, seeds=[dict(proposal, concept='invented anchor')]))
                invalid = schema.model_validate(dict(value, seeds=[dict(proposal,
                    gaps=[dict(proposal['gaps'][0], source_chunk_ids=['invented chunk'])])]))
                with self.assertRaises(ValueError): validator(invalid)
            elif role == 'background_gap_coverage':
                self.assertEqual({r['id'] for r in payload['references']}, {'chunk_1', 'chunk_2'})
                value = {q['id']: dict(answered=q['question']=='Why chunk_1?',
                    evidence_ids=['chunk_2'] if q['question']=='Why chunk_1?' else [],
                    reason='Fixture source coverage') for q in payload['items']}
            else:
                raise AssertionError(role)
            result = schema.model_validate(value)
            if validator: validator(result)
            return result
        model = SimpleNamespace(ask=ask, options=dict(num_ctx=16000, num_predict=4096))
        concepts = ConceptRegistry(model, self.trace)
        concepts.entries = {n:dict(name=n, definition='A documented process', kind='process')
                            for n in ['process a', 'process b', 'property c']}
        chunks = [dict(id='chunk_' + str(i), paragraph_id='p' + str(i), text='Source passage ' + str(i)) for i in (1,2)]
        extractions = [dict(chunk_id=c['id'], concepts=list(concepts.entries), relations=[]) for c in chunks]
        seeds = collect_seeds(extractions, chunks, concepts, self.trace,
                              outline=dict(overview='Processes and properties', topics=['Mechanisms'], segments=[]))
        self.assertEqual(visited, ['chunk_1', 'chunk_2'])
        self.assertEqual(len(seeds), 1)
        self.assertEqual([g['question'] for g in seeds[0]['gaps']], ['Why chunk_2?'])
        self.assertEqual(seeds[0]['chunk_ids'], ['chunk_1', 'chunk_2'])
        self.assertEqual(len(seeds[0]['case_specific_unknowns']), 2)
        state = json.loads((self.trace.directory/'artifacts/seeds.json').read_text())
        self.assertEqual(state['omitted_by_limit'], 0)
        self.assertEqual(len(state['assessments'][0]['covered_gaps']), 1)

    def test_precision_review_is_targeted_and_restores_model_configuration(self):
        from pipeline.source_precision import needs_precision, precise_source_check
        row = dict(id='edge',source='barrier',relation='prevents',target='operator',
                   relation_definition='Stops an activity',conditions=None,modality=None,
                   evidence='A barrier prevents an operator from opening a chamber.',accepted=True)
        self.assertTrue(needs_precision(row))
        self.assertFalse(needs_precision(dict(row,relation='measures',evidence='A device measures temperature.')))
        self.assertTrue(needs_precision(dict(row,relation='stored_in',surface_relation='stores',evidence='A box stores material.')))
        conditional=dict(row,relation='enters',source='water',target='chamber',
            evidence='If water enters the chamber, the pressure rises.')
        self.assertTrue(needs_precision(conditional))
        self.assertFalse(needs_precision(dict(conditional,conditions='if water enters the chamber')))
        original = dict(row)
        model = SimpleNamespace(think=False,options=dict(num_ctx=8192,num_predict=4096),model='configured-local-model')
        old_options = model.options
        objection_is_applicable = True
        def ask(role,instruction,payload,schema,entity_id,validator=None):
            if role=='source_objection_applicability':
                self.assertFalse(model.think)
                return schema.model_validate({'edge':dict(reason='Applicability checked against other edges',unsupported=objection_is_applicable)})
            self.assertFalse(model.think)
            self.assertEqual(model.options['num_predict'],1536)
            self.assertEqual(payload['source_quote'],row['evidence'])
            if role=='source_scope_reader':
                self.assertNotIn('graph',payload)
                return schema.model_validate(dict(reason='Source only',statements=[row['evidence']]))
            result=schema.model_validate(dict(reason='Activity missing',faithful=False,
                missing_or_changed_meaning='The quoted activity must be represented'))
            validator(result);return result
        model.ask=ask
        chunk=dict(id='chunk',text=row['evidence'],start=0)
        result=precise_source_check(chunk,[row],model,self.trace)
        self.assertEqual(result['unsupported'][0]['id'],'edge');self.assertEqual(row,original)
        self.assertFalse(model.think);self.assertIs(model.options,old_options)
        objection_is_applicable = False
        partial=precise_source_check(chunk,[row],model,self.trace)
        self.assertEqual(partial['missing'],[])
        self.assertEqual(partial['unsupported'],[])
        from pipeline.models import OutputLimitError
        failed_calls=[]
        def fail(*args,**kwargs):
            failed_calls.append(args[0]);raise OutputLimitError('bounded response')
        model.ask=fail
        result=precise_source_check(chunk,[row],model,self.trace)
        self.assertIn('edge_precision',result['errors'])
        self.assertEqual(result['unsupported'],[])
        self.assertFalse(model.think);self.assertIs(model.options,old_options)
        self.assertEqual(precise_source_check(chunk,[row],model,self.trace)['errors'],result['errors'])
        self.assertEqual(failed_calls,['source_scope_reader'])

    def test_short_evidence_cannot_remove_conditional_scope_or_borrow_another_edges_scope(self):
        from pipeline.source_precision import enclosing_evidence,precise_source_check,conditional_premise_without_scope
        text='A valve opens. If water enters a chamber, pressure can rise.'
        quote='water enters a chamber'
        row=dict(id='premise',source='water',relation='enters',target='chamber',
            relation_definition='SOURCE enters TARGET',conditions=None,modality=None,
            evidence=quote,evidence_start=100+text.index(quote),accepted=True)
        chunk=dict(id='chunk',start=100,text=text)
        expanded,offset=enclosing_evidence(chunk,row)
        self.assertEqual(expanded,'If water enters a chamber, pressure can rise.')
        self.assertEqual(offset,100+text.index('If'))
        self.assertTrue(conditional_premise_without_scope(chunk,row))
        self.assertFalse(conditional_premise_without_scope(chunk,dict(row,conditions='if water enters')))
        self.assertTrue(conditional_premise_without_scope(chunk,dict(row,evidence=text,evidence_start=100)))
        self.assertFalse(conditional_premise_without_scope(chunk,dict(row,relation='warms',evidence=text,evidence_start=100)))
        calls=[]
        def ask(role,instruction,payload,schema,entity_id,validator=None):
            calls.append(role)
            if role=='source_scope_reader':
                self.assertEqual(payload['source_quote'],expanded)
                return schema.model_validate(dict(reason='A conditional statement',statements=[expanded]))
            self.assertEqual(role,'source_fidelity_check')
            value=schema.model_validate(dict(reason='A conditional premise was asserted without scope',
                faithful=False,missing_or_changed_meaning='Preserve the conditional meaning'))
            validator(value);return value
        companion=dict(row,id='consequence',source='pressure',relation='rises',target='level',
                       conditions='if water enters a chamber',modality='can',accepted=True)
        model=SimpleNamespace(ask=ask,think=False,options=dict(num_ctx=8192,num_predict=4096),model='local')
        result=precise_source_check(chunk,[row,companion],model,self.trace)
        self.assertEqual([r['id'] for r in result['unsupported']],['premise'])
        self.assertEqual(calls,['source_scope_reader'])
        repeated=dict(chunk,text='If water enters a chamber, pressure can rise. '+expanded)
        second=dict(row,evidence_start=100+repeated['text'].rindex(quote))
        self.assertEqual(enclosing_evidence(repeated,second)[1],100+repeated['text'].rindex('If'))

    def test_argument_qualifiers_survive_deduplication_and_reconstruction(self):
        from pipeline.graph_view import canonicalize_graph,concept_id
        from pipeline.evaluation import reconstruction_context
        registry=RelationRegistry(SimpleNamespace(),self.trace)
        registry.entries['moves']=dict(key='moves',definition='Moves the target',symmetric=False,inverse=None)
        facts=FactIndex(registry)
        first=dict(id='a',source='device',relation='moves',target='material',conditions=None,
                   modality=None,argument_qualifiers=['into a vessel'])
        second=dict(first,id='b',argument_qualifiers=['into a chamber'])
        self.assertIsNone(facts.add(first));self.assertIsNone(facts.add(second))
        self.assertIs(facts.find(dict(first)),first)
        nodes=[dict(id=concept_id(n),label=n,kind='concept',origin='document',definition=n) for n in ['device','material']]
        edges=[dict(id=r['id'],source=nodes[0]['id'],target=nodes[1]['id'],label='moves',origin='document',
                    chunk_id='chunk',conditions=None,modality=None,argument_qualifiers=r['argument_qualifiers']) for r in [first,second]]
        graph=canonicalize_graph(dict(nodes=nodes,edges=edges))
        self.assertEqual(len(graph['edges']),2)
        projected=reconstruction_context(graph,'chunk')['relations']
        self.assertEqual({tuple(r['argument_qualifiers']) for r in projected},{('into a vessel',),('into a chamber',)})
        self.assertTrue(all(r['conditions'] is None for r in projected))

    def test_source_arguments_require_exact_quotes_and_remain_unaccepted_proposals(self):
        from pipeline.qualifiers import complete_arguments
        row = dict(id='one', source='device', relation='prevents', target='operator',
                   conditions='during maintenance', modality='can',
                   evidence='A device can prevent an operator from opening a chamber during maintenance.')
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            self.assertEqual(role,'source_arguments')
            value = dict(prevented_or_enabled_action='opening a chamber', result_or_destination='operator',
                         other_required_arguments=['during maintenance'], reason='Quoted activity')
            wrong = schema.model_validate({'one':dict(value, prevented_or_enabled_action='invented activity')})
            with self.assertRaises(ValueError): validator(wrong)
            result = schema.model_validate({'one':value}); validator(result); return result
        complete_arguments([dict(relation_proposals=[row])], SimpleNamespace(ask=ask), self.trace)
        self.assertEqual(row['conditions'], 'during maintenance')
        self.assertEqual(row['argument_qualifiers'], ['activity: opening a chamber'])
        self.assertEqual(row['source'],'device'); self.assertEqual(row['target'],'operator')
        self.assertEqual(row['modality'],'can'); self.assertNotIn('accepted',row)
        with patch.object(SimpleNamespace(), 'ask', create=True) as unused:
            complete_arguments([dict(relation_proposals=[row])], SimpleNamespace(ask=unused), self.trace)
            unused.assert_not_called()

    def test_double_encoded_negation_requires_model_correction(self):
        from pipeline.qualifiers import Polarity, correct_polarity
        row = dict(relation='does_not_use', relation_definition='SOURCE does not use TARGET',
                   modality='does not')
        with self.assertRaisesRegex(ValueError, 'negation occurs in both'):
            Polarity.model_validate(row)
        self.assertEqual(Polarity.model_validate(dict(row, relation='uses')).modality, 'does not')
        self.assertEqual(Polarity.model_validate(dict(row, modality=None)).relation, 'does_not_use')
        calls = []
        def ask(role, instruction, payload, schema, entity_id):
            calls.append(role)
            self.assertEqual(payload['source'], 'Process A does not employ process B.')
            return schema.model_validate(dict(row, relation='uses', relation_definition='SOURCE employs TARGET'))
        draft = dict(row, source='process a', target='process b', conditions='phase c')
        result = correct_polarity(draft, 'Process A does not employ process B.',
                                  SimpleNamespace(ask=ask), self.trace, 'one')
        self.assertEqual(calls, ['polarity_repair'])
        self.assertEqual(result['source'], draft['source'])
        self.assertEqual(result['conditions'], 'phase c')
        self.assertEqual(result['relation'], 'uses')
        self.assertEqual(draft['relation'], 'does_not_use')

    def test_gap_reuse_requires_admitted_evidence_and_a_complete_answer(self):
        from pipeline.debate import debate
        for answered in (True, False):
            seen = []
            def ask(role, instruction, payload, schema, entity_id, validator=None):
                seen.append(role)
                if role == 'proposer':
                    raise RuntimeError('An unanswered gap still reaches the proposer')
                self.assertEqual(role, 'background_existing_gap_coverage')
                self.assertEqual([f['id'] for f in payload['items'][0]['admitted_facts']], ['admitted'])
                result = schema.model_validate({'gap': dict(answered=answered,
                    evidence_ids=['admitted'] if answered else [], reason='Fixture coverage judgment')})
                validator(result)
                return result
            model = SimpleNamespace(ask=ask)
            concepts = ConceptRegistry(model, self.trace)
            relations = RelationRegistry(model, self.trace)
            facts = FactIndex(relations)
            row = dict(id='admitted', source='process a', relation='changes', target='property b',
                intended_fact='Process A changes property B under condition C.',
                relation_definition='SOURCE changes TARGET', conditions='condition C', modality=None,
                origin='background', accepted=True)
            facts.rows = [row, dict(row, id='rejected', accepted=False)]
            seed = dict(id='seed', concept='process a', definition='A process', kind='process',
                chunk_id='chunk', gaps=[dict(id='gap', question='How does process A change property B?')])
            args = ([seed], [dict(id='chunk', text='Process A is discussed.')],
                    dict(overview='Fixture', topics=[]), concepts, relations, facts, model, self.trace)
            if answered:
                result = debate(*args)
                self.assertEqual(result['transcripts'][0]['status'], 'skipped')
                self.assertNotIn('proposer', seen)
            else:
                with self.assertRaisesRegex(RuntimeError, 'unanswered gap'):
                    debate(*args)

    def test_retrieval_never_authorizes_a_false_identity_merge(self):
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            data = dict(canonical_name='existing', reason='Related') if role == 'concept_alias_resolver' else dict(
                same_concept=False, same_scope=True, reason='Different referents')
            return schema.model_validate(data)
        model = SimpleNamespace(ask=ask, identity_candidates=2)
        registry = ConceptRegistry(model, self.trace)
        mention = dict(name='new concept', definition='A related but different entity', kind='entity', form='concept')
        available = {'existing': dict(name='existing', definition='A different entity', kind='entity', form='concept')}
        self.assertIsNone(registry._semantic_match(mention, available, 'context', 'one'))

    def test_named_contract_is_verified_before_searching_for_alternatives(self):
        calls = []
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            calls.append(role)
            self.assertEqual(payload['proposed_contract']['key'], 'enables')
            self.assertEqual(payload['qualified_original']['modality'],'can')
            self.assertEqual(payload['qualified_proposal']['modality'],'can')
            return schema.model_validate(dict(exact_meaning=True, same_direction=True,
                compatible_types=True, reason='Qualified occurrence expresses this contract'))
        registry = RelationRegistry(SimpleNamespace(ask=ask), self.trace)
        before = dict(registry.entries['enables'])
        self.assertEqual(registry.resolve('enables', 'Makes the target possible',
            'ventilation', 'cooling', dict(evidence='Ventilation can enable cooling',modality='can'), 'one'), 'enables')
        self.assertEqual(calls, ['relation_match_verifier'])
        self.assertEqual(registry.entries['enables'], before)

    def test_new_predicate_keeps_its_passive_direction_and_requires_verification(self):
        for passes in (True, False):
            calls = []
            def ask(role, instruction, payload, schema, entity_id, validator=None):
                calls.append(role)
                if role == 'relation_resolver':
                    return schema.model_validate(dict(key=None, exact_meaning=False, same_direction=False, reason='No equivalent'))
                self.assertEqual(role, 'relation_definition_verifier')
                self.assertEqual(payload['new_contract']['key'], 'provided_by')
                return schema.model_validate(dict(coherent=passes, meaning_preserved=passes,
                    direction_preserved=passes, symmetry_correct=True, inverse_correct=True, reason='Fixture review'))
            registry = RelationRegistry(SimpleNamespace(ask=ask), self.trace)
            result = registry.resolve('provided by', 'SOURCE is provided by TARGET.',
                                      'resource', 'provider', 'A provider supplies a resource.', 'one')
            self.assertEqual(result, 'provided_by' if passes else None)
            self.assertNotIn('relation_definition', calls)

    def test_existing_surface_label_can_receive_a_verified_distinct_sense(self):
        calls = []
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            calls.append(role)
            if role == 'relation_resolver':
                value = dict(key=None, exact_meaning=False, same_direction=False, reason='Different sense')
            elif role == 'relation_definition':
                with self.assertRaisesRegex(ValueError, 'already has a different'):
                    validator(schema.model_validate(dict(key='uses', definition='A different sense', symmetric=False, inverse=None)))
                value = dict(key='employs_resource', definition='SOURCE employs TARGET as a resource', symmetric=False, inverse=None)
            else:
                value = dict(coherent=True, meaning_preserved=True, direction_preserved=True,
                             symmetry_correct=True, inverse_correct=True, reason='Verified resource use')
            return schema.model_validate(value)
        registry = RelationRegistry(SimpleNamespace(ask=ask), self.trace)
        original = dict(key='uses',definition='SOURCE operates TARGET as an instrument',symmetric=False,inverse=None)
        registry.entries['uses'] = dict(original)
        result = registry.resolve('uses','SOURCE employs TARGET as a resource',
                                  'device','material','A device uses material.','one')
        self.assertEqual(result,'employs_resource')
        self.assertEqual(registry.entries['uses'],original)
        self.assertIn('relation_definition_verifier',calls)

    def test_dynamic_predicate_sense_reuse_still_requires_equivalence_verification(self):
        calls = []
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            calls.append(role)
            value = (dict(key='employs_resource',exact_meaning=True,same_direction=True,reason='Same sense')
                     if role=='relation_resolver' else dict(exact_meaning=True,same_direction=True,
                                                           compatible_types=True,reason='Independently verified'))
            return schema.model_validate(value)
        registry = RelationRegistry(SimpleNamespace(ask=ask),self.trace)
        registry.entries.update(uses=dict(key='uses',definition='Uses an instrument',symmetric=False,inverse=None),
            employs_resource=dict(key='employs_resource',definition='Uses a resource',symmetric=False,inverse=None))
        self.assertEqual(registry.resolve('uses','Uses a resource','device','material','Quote','one'),'employs_resource')
        self.assertEqual(calls,['relation_resolver','relation_match_verifier'])
        self.assertEqual(registry.entries['uses']['definition'],'Uses an instrument')

    def test_batch_retries_only_item_whose_semantic_validation_failed(self):
        calls = []
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            ids = [item['id'] for item in payload['items']]
            calls.append(ids)
            response = schema.model_validate({id: dict(value=0 if id == 'b' and len(ids) > 1 else 1) for id in ids})
            if validator: validator(response)
            return response
        def validate(item, response):
            if response.value != 1: raise ValueError('Invalid semantic choice')
        output = ask_keyed(SimpleNamespace(ask=ask), 'check', 'Check',
                           [dict(id='a'), dict(id='b')], Answer, 'batch', validate=validate)
        self.assertEqual(calls, [['a', 'b'], ['b']])
        self.assertEqual(output, {'a': {'value': 1}, 'b': {'value': 1}})

    def test_compacted_repeated_evidence_is_lossless(self):
        original = dict(first='Exact source sentence. ' * 12, second=['Exact source sentence. ' * 12])
        packed = compact_payload(original)
        def expand(value):
            if isinstance(value, dict) and set(value) == {'$text'}: return packed['text_references'][value['$text']]
            if isinstance(value, dict): return {k: expand(v) for k, v in value.items()}
            if isinstance(value, list): return [expand(v) for v in value]
            return value
        self.assertEqual(expand(packed['data']), original)

    def test_transient_service_failure_recovers_and_records_each_call(self):
        with patch('pipeline.models.Client') as client, patch('pipeline.models.time.sleep'):
            client.return_value.chat.side_effect = [ResponseError('CUDA unavailable', 500),
                ChatResponse(message=dict(role='assistant', content='{"text":"model answer","reason":"fixture"}'), done_reason='stop')]
            models = Models(self.trace, 'test', 'embed', 'http://localhost')
            answer = models.ask('test', 'Generate', {}, Reconstruction, 'one')
        self.assertEqual(answer.text, 'model answer')
        self.assertEqual(models.calls, 2)
        self.assertEqual(models.service_retries, 1)
        self.assertEqual(self.trace.counts['service.retry'], 1)
        self.assertEqual(self.trace.counts['model.request'], 2)

    def test_service_recovery_is_bounded_and_bad_requests_are_not_retried(self):
        for status, count in ((500, 3), (400, 1)):
            with self.subTest(status=status), patch('pipeline.models.Client') as client, patch('pipeline.models.time.sleep'):
                client.return_value.chat.side_effect = ResponseError('Failure', status)
                models = Models(self.trace, 'test', 'embed', 'http://localhost')
                with self.assertRaises(ModelServiceError): models.ask('test', 'Generate', {}, Reconstruction, 'one')
                self.assertEqual(client.return_value.chat.call_count, count)

    def test_durable_cache_survives_incomplete_event_tail_and_revalidates(self):
        details = {'installed_models': {'models': [{'model': 'test', 'digest': 'unchanged'}]}}
        self.trace.save('artifacts/environment.json', dict(model_details=details))
        with patch('pipeline.models.Client') as client:
            client.return_value.chat.return_value = ChatResponse(
                message=dict(role='assistant', content='{"text":"saved","reason":"fixture"}'), done_reason='stop')
            models = Models(self.trace, 'test', 'embed', 'http://localhost')
            models.ask('test', 'Generate', {}, Reconstruction, 'one')
        self.trace.stream.write('{"partial":'); self.trace.stream.flush()
        with patch('pipeline.models.Client') as client:
            resumed = Models(self.trace, 'test', 'embed', 'http://localhost')
            resumed.details = details
            # Use a different destination so load_cache does not append events to its source.
            other = Trace(self.root / 'resumed', 'resumed'); self.addCleanup(other.close)
            resumed.trace = other
            resumed.load_cache(self.trace.directory)
            result = resumed.ask('test', 'Generate', {}, Reconstruction, 'one')
            client.return_value.chat.assert_not_called()
        self.assertEqual(result.text, 'saved')
        self.assertEqual(other.counts['cache.incomplete_tail'], 1)
        self.assertEqual(other.counts['validation.completed'], 1)

    def test_checkpoint_restores_consistent_artifacts_and_invalidates_changed_input(self):
        models = SimpleNamespace(details={})
        concepts, relations = ConceptRegistry(models, self.trace), RelationRegistry(models, self.trace)
        facts = FactIndex(relations)
        store = Checkpoints(self.trace, models, 'original text', {}, (concepts, relations, facts))
        self.trace.save('artifacts/example.json', {'version': 1})
        store.save('stage', dict(completed=['one']))
        self.trace.save('artifacts/example.json', {'version': 2})
        target = Trace(self.root / 'new', 'new'); self.addCleanup(target.close)
        restored = Checkpoints(target, models, 'original text', {}, (concepts, relations, facts), self.trace.directory)
        self.assertEqual(restored.restore('stage'), {'completed': ['one']})
        self.assertEqual(json.loads((target.directory / 'artifacts/example.json').read_text()), {'version': 1})
        changed = Checkpoints(target, models, 'different text', {}, (concepts, relations, facts), self.trace.directory)
        self.assertIsNone(changed.restore('stage'))

    def test_presentation_change_reuses_checkpoint_but_logic_and_prompt_changes_do_not(self):
        models = SimpleNamespace(details={})
        concepts, relations = ConceptRegistry(models,self.trace), RelationRegistry(models,self.trace)
        registries = (concepts,relations,FactIndex(relations))
        hashes = {'pipeline/core.py':'logic-v1','pipeline/prompt.txt':'prompt-v1',
                  'pipeline/graph_view.html':'view-v1'}
        with patch('pipeline.checkpoints.notebook.source_hashes',return_value=hashes):
            store=Checkpoints(self.trace,models,'text',{},registries)
            store.save('stage',{'complete':True})
        target=Trace(self.root/'resume','resume');self.addCleanup(target.close)
        def restore(changes):
            with patch('pipeline.checkpoints.notebook.source_hashes',return_value=hashes|changes):
                return Checkpoints(target,models,'text',{},registries,self.trace.directory).restore('stage')
        self.assertEqual(restore({'pipeline/graph_view.html':'view-v2'}),{'complete':True})
        self.assertIsNone(restore({'pipeline/core.py':'logic-v2'}))
        self.assertIsNone(restore({'pipeline/prompt.txt':'prompt-v2'}))

    def test_source_audit_receives_qualifiers_and_resolves_exact_evidence_from_ids(self):
        from pipeline.source_recovery import audit_source
        captured = {}
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            captured.update(payload)
            identifier = payload['items'][0]['id']
            value = dict(claims=[dict(source_assertion='A qualified connection', graph_edge_ids=['edge'],
                graph_reading='Process A may not influence property B during phase C', preserves_meaning=True)],
                missing=[dict(source_sentence_ids=[identifier], missing_claim='A qualified connection',
                                      reason='Fixture')], unsupported=[], reason='Fixture coverage')
            with self.assertRaises(ValueError):
                schema.model_validate({identifier:dict(value, missing=[dict(value['missing'][0],source_sentence_ids=['invented'])])})
            invalid_edge = schema.model_validate({identifier:dict(value,
                unsupported=[dict(value['missing'][0], id='invented edge')])})
            with self.assertRaises(ValueError): validator(invalid_edge)
            result = schema.model_validate({identifier:value})
            validator(result)
            return result
        row = dict(id='edge', source='process a', relation='influences', target='property b',
            relation_definition='SOURCE influences TARGET', modality='may not',
            conditions='during phase c', evidence='Do not treat this quote as graph content', accepted=True)
        result = audit_source(dict(id='chunk', start=45, text='Process A may not influence property B during phase C.'),
                     dict(relations=[row]), SimpleNamespace(entries={}), SimpleNamespace(ask=ask), self.trace, 0)
        self.assertEqual(captured['graph_assertions'][0]['modality'], 'may not')
        self.assertEqual(captured['graph_assertions'][0]['conditions'], 'during phase c')
        self.assertNotIn('evidence', captured['graph_assertions'][0])
        self.assertEqual(result.missing[0].evidence, 'Process A may not influence property B during phase C.')
        self.assertEqual(result.missing[0].evidence_start, 45)

    def test_source_audit_cannot_reject_an_edge_using_an_unrelated_sentence(self):
        from pipeline.source_recovery import audit_source
        text = 'A device warms material. A valve releases pressure.'
        quote = 'A valve releases pressure.'
        row = dict(id='valve_edge',source='valve',relation='releases',target='pressure',
            relation_definition='SOURCE releases TARGET',evidence=quote,
            evidence_start=100+text.index(quote),evidence_end=100+len(text),accepted=True)
        tested = []
        def ask(role,instruction,payload,schema,entity_id,validator=None):
            identifier = payload['items'][0]['id']
            value = dict(claims=[dict(source_assertion='The source assertion',graph_edge_ids=[],
                graph_reading='Missing',preserves_meaning=False)],missing=[],unsupported=[],reason='Fixture')
            if identifier.endswith('001'):
                invalid = dict(value,unsupported=[dict(id='valve_edge',source_sentence_ids=[identifier],
                    reason='The warming edge is missing',missing_claim='Warming material')])
                with self.assertRaisesRegex(ValueError,"own source sentence"):
                    validator(schema.model_validate({identifier:invalid}))
                tested.append(True)
            result = schema.model_validate({identifier:value})
            validator(result)
            return result
        result = audit_source(dict(id='chunk',start=100,text=text),dict(relations=[row]),
            SimpleNamespace(),SimpleNamespace(ask=ask,batch_size=1),self.trace,0)
        self.assertEqual(tested,[True])
        self.assertEqual(result.unsupported,[])

    def test_source_sentence_ids_disambiguate_repeated_text(self):
        from pipeline.source_recovery import audit_source
        text = 'Device acts. Device acts.'
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            values = {}
            for item in payload['items']:
                missing = [dict(reason='Missing second occurrence', missing_claim='The second source assertion',
                                source_sentence_ids=[item['id']])] if item['id'].endswith('002') else []
                values[item['id']] = dict(claims=[dict(source_assertion='Device acts.', graph_edge_ids=[],
                    graph_reading='No graph assertion', preserves_meaning=False)],
                    reason='Fixture coverage', missing=missing, unsupported=[])
            result = schema.model_validate(values)
            if validator: validator(result)
            return result
        result = audit_source(dict(id='chunk',start=100,text=text), dict(relations=[]),
                              SimpleNamespace(), SimpleNamespace(ask=ask), self.trace, 0)
        repeated = [r for r in result.missing if r.evidence_start == 100 + text.rindex('Device acts.')]
        self.assertTrue(repeated)
        self.assertEqual(repeated[0].evidence, 'Device acts.')
        self.assertEqual(result.missing[0].evidence_start, 100)

    def test_source_reviewer_cannot_rewrite_the_assertion_to_match_the_quote(self):
        from pipeline.debate import review_extractions
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            self.assertEqual(role, 'extraction_reviewer')
            item = payload['items'][0]
            literal = item['literal_candidate_reading']
            self.assertEqual(literal, 'ASSERTED (process a --[affects]--> process b)')
            verdict = dict(candidate_id='edge', qualified_reading=literal, reason='Source negates this assertion',
                semantics_valid=True, direction_valid=True, types_valid=True, no_contradiction=False,
                certain=True, evidence_status='unsupported', domain_relevance=1., accept=False,
                objections_resolved=False, rejection_categories=['contradiction'])
            with self.assertRaises(ValueError):
                schema.model_validate(dict(edge=dict(verdict, qualified_reading='process a does not affect process b')))
            result = schema.model_validate(dict(edge=verdict)); validator(result); return result
        model = SimpleNamespace(ask=ask)
        concepts = ConceptRegistry(model, self.trace)
        concepts.entries = {n:dict(name=n, definition='A process', kind='process') for n in ('process a','process b')}
        row = dict(id='edge', chunk_id='chunk', source='process a', target='process b', relation='affects',
            relation_definition='SOURCE affects TARGET', modality=None, conditions=None,
            evidence='Process A does not affect process B.', origin='document', reason='Draft')
        extraction = dict(chunk_id='chunk', relation_proposals=[row], relations=[])
        result = review_extractions([extraction], [dict(id='chunk',text=row['evidence'])],
            dict(overview='Processes', topics=['Interactions']), concepts,
            FactIndex(RelationRegistry(model,self.trace)), model, self.trace)
        self.assertFalse(result[0]['accepted'])
        self.assertEqual(extraction['relations'], [])

    def test_negative_direction_reader_is_blind_and_only_flags_exact_reversals(self):
        from pipeline.qualifiers import negative_direction
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            self.assertEqual(role, 'source_role_reader')
            self.assertNotIn('candidate', payload)
            self.assertNotIn('source', payload)
            result = schema.model_validate(dict(predicate_subject='process b', predicate_object='process a',
                reason='Source grammatical roles'))
            validator(result); return result
        row = dict(id='edge', source='process a', relation='affects', target='process b', modality='does not',
                   evidence='The process b does not affect process a.')
        result = negative_direction(row, SimpleNamespace(ask=ask), self.trace)
        self.assertTrue(result['exact_reversed_bindings'])
        result = negative_direction(dict(row, target='property c'), SimpleNamespace(ask=ask), self.trace)
        self.assertFalse(result['exact_reversed_bindings'])
        def unknown(role, instruction, payload, schema, entity_id, validator=None):
            result = schema.model_validate(dict(predicate_subject=None, predicate_object=None, reason='Unclear'))
            validator(result); return result
        self.assertFalse(negative_direction(row, SimpleNamespace(ask=unknown), self.trace)['exact_reversed_bindings'])

    def test_explicit_relative_clause_veto_is_generic_and_does_not_invent_repairs(self):
        from pipeline.qualifiers import explicit_reversed_clause, negative_direction
        row = dict(id='edge', source='material', target='coil', relation='heats', modality='does not',
                   evidence='The material that the coil does not heat remains unchanged.')
        self.assertTrue(explicit_reversed_clause(row))
        self.assertFalse(explicit_reversed_clause(dict(row, source='coil', target='material')))
        self.assertFalse(explicit_reversed_clause(dict(row, evidence='The material is not heated by the coil.')))
        self.assertFalse(explicit_reversed_clause(dict(row, evidence='The material that the coil does not touch remains unchanged.')))
        result = negative_direction(row, SimpleNamespace(), self.trace)
        self.assertTrue(result['exact_reversed_bindings'])
        self.assertEqual(row['source'], 'material')

    def test_batches_accept_discriminated_union_schemas(self):
        from typing import Annotated, Literal
        from pydantic import Field
        class One(Record):
            kind: Literal['one']
            value: int
        class Two(Record):
            kind: Literal['two']
            text: str
        schema = Annotated[One | Two, Field(discriminator='kind')]
        def ask(role, instruction, payload, schema, entity_id, validator=None):
            return schema.model_validate({item['id']: dict(kind='one', value=1) for item in payload['items']})
        result = ask_keyed(SimpleNamespace(ask=ask), 'check', 'Check', [dict(id='a')], schema, 'one')
        self.assertEqual(result['a'], {'kind': 'one', 'value': 1})

    def test_source_repair_requires_admission_and_retains_unresolved_coverage(self):
        from pipeline.source_recovery import Coverage, recover_source
        text = 'Device A can warm material B under condition C.'
        source = dict(id='chunk', paragraph_id='paragraph', text=text, start=0, end=len(text))
        audit = Coverage.model_validate(dict(missing=[dict(evidence=text,
            missing_claim='The qualified warming connection', reason='Absent')], reason='Missing'))
        for admitted in (False, True):
            with self.subTest(admitted=admitted):
                extraction = dict(chunk_id='chunk', concepts=[], relations=[], relation_proposals=[])
                row = dict(id='repair', chunk_id='temporary', accepted=admitted,
                           review_status='completed', source='device a', target='material b',
                           relation='warms', conditions='under condition C', modality='can')
                recovered = [dict(concepts=['device a', 'material b'], relation_proposals=[row],
                                  relations=[row] if admitted else [])]
                audits = [audit, Coverage(missing=[], reason='Represented')] if admitted else [audit]
                with patch('pipeline.qualifiers.complete_arguments'), \
                     patch('pipeline.source_recovery.audit_source', side_effect=audits), \
                     patch('pipeline.extraction.extract', return_value=recovered) as generate, \
                     patch('pipeline.debate.review_extractions', return_value=[row]) as review:
                    recover_source([extraction], [source], [], {}, SimpleNamespace(), None, None,
                                   SimpleNamespace(), self.trace, [])
                generate.assert_called_once()
                review.assert_called_once()
                self.assertEqual(len(extraction['relations']), int(admitted))
                report = json.loads((self.trace.directory / 'artifacts/source_coverage.json').read_text())
                self.assertEqual(report['chunks'][0]['status'],
                                 'covered_by_model_review' if admitted else 'remaining_gaps')
                if admitted:
                    self.assertEqual(extraction['relations'][0]['chunk_id'], 'chunk')
                    self.assertEqual(extraction['relations'][0]['modality'], 'can')

    def test_source_audit_can_quarantine_a_wrong_edge_without_fabricating_a_replacement(self):
        from pipeline.source_recovery import Coverage, recover_source
        text = 'Device A forbids operator B from starting process C.'
        source = dict(id='chunk', paragraph_id='paragraph', text=text, start=0, end=len(text))
        bad = dict(id='bad', chunk_id='chunk', source='device a', relation='forbids', target='operator b',
                   accepted=True, review_status='completed', conditions=None, modality=None)
        extraction = dict(chunk_id='chunk', concepts=[], relations=[bad], relation_proposals=[bad])
        facts = SimpleNamespace(rows=[bad])
        audit = Coverage.model_validate(dict(missing=[], unsupported=[dict(id='bad', evidence=text,
            missing_claim='The prohibition concerns starting the process', reason='Essential activity is absent')], reason='Scope changed'))
        recovered = [dict(concepts=[], relation_proposals=[], relations=[])]
        with patch('pipeline.source_precision.precise_source_check', return_value=dict(missing=[],unsupported=[],errors={})), \
             patch('pipeline.source_recovery.audit_source', return_value=audit), \
             patch('pipeline.extraction.extract', return_value=recovered) as generate, \
             patch('pipeline.debate.review_extractions', return_value=[]) as review:
            recover_source([extraction], [source], [], {}, SimpleNamespace(), None, facts,
                           SimpleNamespace(), self.trace, [bad])
        generate.assert_called_once(); review.assert_called_once()
        self.assertFalse(bad['accepted'])
        self.assertEqual(extraction['relations'], [])
        self.assertEqual(facts.rows, [])
        self.assertEqual(extraction['relation_proposals'][0]['id'], 'bad')
        report = json.loads((self.trace.directory/'artifacts/source_coverage.json').read_text())
        self.assertEqual(report['chunks'][0]['status'], 'remaining_gaps')


if __name__ == '__main__':
    unittest.main()
