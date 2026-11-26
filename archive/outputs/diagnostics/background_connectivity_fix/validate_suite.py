"""Capture comparable unittest results for this investigation."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--draft', action='store_true')
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    directory = Path(__file__).resolve().parent
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'tests'))
    if args.draft:
        import pipeline
        import _submission_runtime as runtime
        for name in ('background_context', 'models', 'settings', 'registry', 'repair_budget', 'debate'):
            module = 'pipeline.' + name
            runtime.register_module(module, (directory / (module + '.py')).read_text(encoding='utf-8'))
    with (directory / (args.label + '-tests.log')).open('w', encoding='utf-8') as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_*.py')
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    data = dict(tests=result.testsRun,
                failures=[dict(id=test.id(), traceback=traceback) for test, traceback in result.failures],
                errors=[dict(id=test.id(), traceback=traceback) for test, traceback in result.errors],
                skipped=[dict(id=test.id(), reason=reason) for test, reason in result.skipped])
    baseline = json.loads((directory / 'baseline-tests.json').read_text(encoding='utf-8'))
    old = {row['id'] for kind in ('failures', 'errors') for row in baseline[kind]}
    new = {row['id'] for kind in ('failures', 'errors') for row in data[kind]}
    data.update(new_failed_ids=sorted(new - old), resolved_failed_ids=sorted(old - new))
    (directory / (args.label + '-tests.json')).write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(json.dumps({key: len(value) if key in ('failures', 'errors', 'skipped') else value
                      for key, value in data.items()}, indent=2))
    return bool(new - old)


if __name__ == '__main__':
    raise SystemExit(main())
