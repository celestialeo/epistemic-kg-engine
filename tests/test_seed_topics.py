"""Offline regression for the saved run's chapter-topic/subtopic mismatch."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from pipeline.health import HealthFailure, HealthMonitor
from pipeline.models import Models
from pipeline.seeds import collect_seeds, topic_assessment_schema, topic_catalog


class MemoryTrace:
    run_id = 'seed-topic-fixture'

    def __init__(self):
        self.events = []
        self.saved = {}

    def emit(self, event, **data):
        self.events.append((event, copy.deepcopy(data)))
        return str(len(self.events))

    def save(self, path, value):
        self.saved[path] = copy.deepcopy(value)


def outline():
    # Labels from the saved diagnostic: the subtopic was supplied but rejected.
    return dict(overview='The document explains a model and its components.',
                topics=['Transformer architecture: tokenization, embeddings, positional info, causal attention masks'],
                segments=[dict(id='segment_001', chunk_ids=['chunk_001'], summary='Token processing.',
                               topics=['Tokenization and embedding layers'])])


def decision(topic_id, expand=True):
    return dict(expand=expand, topic_id=topic_id, importance=.8, relevance=.9,
                reason='Understanding this connection helps explain the document.')


def input_data(models, count):
    names = ['concept ' + str(i) for i in range(count)]
    concepts = SimpleNamespace(models=models, entries={name: dict(name=name, definition='A documented concept.', kind='concept')
                                                       for name in names})
    chunks = [dict(id='chunk_001', paragraph_id='paragraph_001', text='The document connects several concepts.')]
    extractions = [dict(chunk_id='chunk_001', concepts=names, relations=[])]
    return extractions, chunks, concepts


def raw(value):
    return SimpleNamespace(model_dump=lambda **kwargs: dict(message=dict(content=json.dumps(value)), done_reason='stop'))


class SeedTopicTests(unittest.TestCase):
    def test_catalog_ids_are_stable_and_schema_accepts_both_levels_only(self):
        document = outline()
        document['topics'].append('Another chapter subject')
        document['segments'].append(dict(id='segment_002', chunk_ids=['chunk_002'], summary='More context.',
                                         topics=['Tokenization and embedding layers']))
        document['segments'].append(dict(id='segment_failed', status='unresolved', topics=['Unvalidated topic']))
        catalog = topic_catalog(document)
        reordered = copy.deepcopy(document)
        reordered['topics'].reverse(); reordered['segments'].reverse()
        self.assertEqual(catalog, topic_catalog(reordered))
        subtopic = next(r for r in catalog if r['level'] == 'subtopic')
        self.assertEqual(subtopic['segment_ids'], ['segment_001', 'segment_002'])
        self.assertEqual(len(catalog), 3)
        schema = topic_assessment_schema(catalog)
        enum = next(branch['enum'] for branch in schema.model_json_schema()['properties']['topic_id']['anyOf'] if 'enum' in branch)
        self.assertEqual(set(enum), {r['id'] for r in catalog})
        for row in catalog:
            self.assertEqual(schema.model_validate(decision(row['id'])).topic_id, row['id'])
        self.assertIsNone(schema.model_validate(decision(None, False)).topic_id)
        unrelated = topic_catalog(dict(topics=['Estuary circulation'], segments=[]))[0]['id']
        for invalid in [subtopic['label'], 'segment_001', 'seed_candidate_0001', unrelated, '', None]:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                schema.model_validate(decision(invalid))
        with self.assertRaisesRegex(ValidationError, 'expand=false requires topic_id=null'):
            schema.model_validate(decision(subtopic['id'], False))

    def test_selection_uses_one_allowed_catalog_and_persists_resolved_labels(self):
        case = self
        captured = []

        class FixtureModels:
            options = dict(num_ctx=8192, num_predict=4096)
            batch_size = 1

            def ask(self, role, instruction, payload, schema, entity_id, validator=None):
                captured.append((role, copy.deepcopy(payload)))
                values = {}
                for item in payload['items']:
                    if role == 'seed_selector':
                        allowed = payload['allowed_topics']
                        catalog_ids = {row['id'] for row in allowed}
                        context_ids = set(payload['chapter']['topic_ids'])
                        for segment in payload['chapter']['segments']:
                            case.assertNotIn('topics', segment)
                            context_ids.update(segment['subtopic_ids'])
                        case.assertEqual(context_ids, catalog_ids)
                        if item['name'] == 'concept 2':
                            values[item['id']] = decision(None, False)
                        else:
                            level = 'chapter' if item['name'] == 'concept 0' else 'subtopic'
                            values[item['id']] = decision(next(row['id'] for row in allowed if row['level'] == level))
                    elif role == 'background_gap_planner':
                        case.assertIn(item['topic_id'], {r['id'] for r in payload['allowed_topics']})
                        values[item['id']] = dict(document_coverage='The source states a function.',
                            gaps=[dict(question='What explains this function?', assumed_knowledge='Its mechanism.',
                                       why_useful='Explains the stated function.', source_chunk_ids=['chunk_001'])],
                            case_specific_unknowns=[], reason='The mechanism is not supplied.')
                    elif role == 'background_gap_coverage':
                        values[item['id']] = dict(answered=False, evidence_ids=[], reason='Not explained in the passage.')
                    else:
                        raise AssertionError(role)
                result = schema.model_validate(values)
                if validator:
                    validator(result)
                return result

        model = FixtureModels(); trace = MemoryTrace()
        trace.health = HealthMonitor(trace)
        seeds = collect_seeds(*input_data(model, 3), trace, outline=outline())
        self.assertEqual(len(seeds), 2)
        self.assertEqual({s['topic_level'] for s in seeds}, {'chapter', 'subtopic'})
        catalog = {r['id']: r for r in trace.saved['artifacts/seeds.json']['allowed_topics']}
        for seed in seeds:
            self.assertEqual(seed['chapter_topic'], catalog[seed['topic_id']]['label'])
        self.assertEqual(trace.saved['artifacts/seed_progress.json']['unresolved'], {})
        self.assertEqual(trace.saved['artifacts/seed_progress.json']['allowed_topics'], list(catalog.values()))
        self.assertTrue(all(row['passed'] for row in trace.health.history['seed_selection']))

    def test_actual_retry_boundary_reports_invalid_selection_and_accepts_correction(self):
        trace = MemoryTrace(); allowed = topic_catalog(outline())
        chosen = next(row for row in allowed if row['level'] == 'subtopic')
        schema = topic_assessment_schema(allowed)
        with patch('pipeline.models.Client') as client:
            client.return_value.chat.side_effect = [raw(decision(chosen['label'])), raw(decision('invented_id')),
                                                   raw(decision(chosen['id']))]
            models = Models(trace, 'fixture', 'fixture', 'http://unused.invalid')
            result = models.ask('seed_selector', 'Select an exact topic_id from allowed_topics.',
                                dict(allowed_topics=allowed), schema, 'seed_topics')
            prompts = [call.kwargs['messages'][0]['content'] for call in client.return_value.chat.call_args_list]
        self.assertEqual(result.topic_id, chosen['id'])
        self.assertEqual(models.retries, 2)
        self.assertIn('Invalid topic_id', prompts[1])
        self.assertIn(chosen['label'], prompts[1])
        self.assertIn('Allowed IDs:', prompts[1])
        self.assertIn(chosen['id'], prompts[1])
        self.assertIn('invented_id', prompts[2])

    def test_exhausted_invalid_selections_still_trigger_health_failure(self):
        trace = MemoryTrace(); trace.health = HealthMonitor(trace)

        def invalid_response(**kwargs):
            keys = kwargs['format']['properties']
            return raw({key: decision('not_in_this_document') for key in keys})

        with patch('pipeline.models.Client') as client:
            client.return_value.chat.side_effect = invalid_response
            models = Models(trace, 'fixture', 'fixture', 'http://unused.invalid', batch_size=1)
            with self.assertRaisesRegex(HealthFailure, r'seed_selection failed 5/5 recent items \(limit 50%\)'):
                collect_seeds(*input_data(models, 5), trace, outline=outline())
        diagnostic = trace.saved['artifacts/health.json']
        self.assertEqual(diagnostic['max_failure_rate'], .5)
        self.assertEqual(diagnostic['window'], 10)
        self.assertTrue(diagnostic['fatal'])
        self.assertIn('Invalid topic_id', diagnostic['error'])
        self.assertEqual(trace.saved['artifacts/seeds.json']['selected'], [])


if __name__ == '__main__':
    unittest.main()
