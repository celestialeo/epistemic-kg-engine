"""Cost attribution must distinguish live, cached, failed and interrupted calls."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.profile_run import profile_run


class ProfileRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []

    def emit(self, kind, seconds, data=None, *, id=None, parent=None, stage='debate'):
        self.events.append(dict(event=kind, elapsed_seconds=seconds, data=data or {},
                                event_id=id, parent_id=parent, stage=stage))

    def request(self, id, role, seconds):
        self.emit('model.request', seconds, dict(role=role, prompt='test'), id=id)

    def response(self, parent, seconds, source='ollama'):
        self.emit('model.response', seconds, dict(source=source, duration_seconds=2,
            response=dict(prompt_eval_count=100, eval_count=20, eval_duration=1_000_000_000,
                          done_reason='stop', message=dict(content='{}'))), parent=parent)

    def profile(self, suffix=b''):
        content = ''.join(json.dumps(e) + '\n' for e in self.events).encode() + suffix
        (self.root / 'events.jsonl').write_bytes(content)
        return profile_run(self.root)

    def test_interleaved_requests_and_cache_exclude_historical_cost(self):
        self.request('a', 'first', 0)
        self.request('b', 'second', 1)
        self.response('a', 2)
        self.response('b', 3)
        self.request('c', 'first', 4)
        self.emit('cache.hit', 4, parent='c')
        self.response('c', 4, source='cache')
        report = self.profile()
        self.assertEqual(report['totals']['requests'], 3)
        self.assertEqual(report['totals']['uncached_requests'], 2)
        self.assertEqual(report['totals']['cache_hits'], 1)
        self.assertEqual(report['totals']['prompt_tokens'], 200)
        self.assertEqual(report['totals']['output_tokens'], 40)
        self.assertEqual(report['totals']['measured_wait_seconds'], 4)
        self.assertEqual({r['role']: r['eval_duration_seconds'] for r in report['roles']},
                         {'first': 1, 'second': 1})

    def test_service_failure_adds_wait_but_validation_failure_does_not_double_count(self):
        self.request('a', 'check', 0)
        self.response('a', 2)
        self.emit('validation.failed', 2, parent='a')
        self.emit('model.attempt_failed', 2, dict(error_type='ValueError'), parent='a')
        self.request('b', 'check', 3)
        self.emit('model.attempt_failed', 8, dict(error_type='ResponseError'), parent='b')
        report = self.profile()
        self.assertEqual(report['totals']['measured_wait_seconds'], 7)
        self.assertEqual(report['totals']['failed_attempts'], 2)
        self.assertEqual(report['totals']['validation_failures'], 1)
        self.assertEqual(report['roles'][0]['failures_before_response'], 1)
        self.assertEqual(report['totals']['pending_requests'], 0)

    def test_incomplete_final_line_preserves_pending_request(self):
        self.request('a', 'check', 0)
        report = self.profile(b'{"event":')
        self.assertEqual(report['totals']['pending_requests'], 1)
        self.assertEqual(report['totals']['measured_wait_seconds'], 0)
        self.assertEqual(len(report['warnings']), 1)

    def test_malformed_complete_line_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, 'invalid event JSON'):
            self.profile(b'{broken}\n')
        with self.assertRaisesRegex(ValueError, 'invalid event JSON'):
            self.profile(b'{broken}\n{"event":"run.closed"}\n')

    def test_resolver_pages_and_null_answers_are_raw_diagnostics(self):
        self.emit('model.request', 0, dict(role='relation_resolver',
            prompt='Instructions\nDATA:\n{"available":[{"key":"a"},{"key":"b"}]}\nPrevious feedback'), id='a')
        self.emit('model.response', 2, dict(source='ollama', duration_seconds=2,
            response=dict(eval_count=12, message=dict(content='{"key":null}'))), parent='a')
        report = self.profile()
        self.assertEqual(report['roles'][0]['candidate_page_p50'], 2)
        self.assertEqual(report['roles'][0]['null_candidate_responses'], 1)
        self.assertFalse(report['recorded_quality']['accuracy_verified'])


if __name__ == '__main__':
    unittest.main()
