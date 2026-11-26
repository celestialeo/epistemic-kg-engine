"""Focused live diagnostics only; saved decisions are never written back."""
import copy
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import pipeline
import _submission_runtime as runtime
from dotenv import load_dotenv
from pipeline.debate import CounterexampleCheck, check_background_counterexamples, validate_counterexample
from pipeline.models import Models
from pipeline.trace import Trace

source = ROOT / 'outputs/runs/llm-tuning/custom/run_20261125_034536_UTC-0500_9e4db7ab'
read = lambda name: json.loads((source / name).read_text(encoding='utf-8'))
config = read('manifest.json')['config']
load_dotenv(ROOT / '.env', override=False)
trace = Trace(Path(__file__).parent / 'live_cases', 'focused_counterexample_validation')
models = Models(trace, config['model'], config['embedding_model'], os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434'),
                timeout=config['model_timeout'], think=config['think'], context_tokens=config['context_tokens'],
                max_output_tokens=config['max_output_tokens'], registry_model=config.get('registry_model'),
                batch_size=config.get('batch_size'), identity_candidates=config.get('identity_candidates'),
                document_context_tokens=config['document_context_tokens'], document_output_tokens=config['document_output_tokens'])
models.cache_enabled = False
results = []
try:
    models.preflight()
    trace.save('provenance.json', dict(source=str(source), code_sha256=runtime.source_hashes(),
                                     cache_enabled=False, scope='isolated_counterexample_validation'))
    cases = [copy.deepcopy(c) for c in read('artifacts/debate_progress.json')['candidates']
             if c['review_status'] == 'unresolved' and 'background_counterexample_check failed' in c.get('decision_reason', '')]
    for row in cases:
        original_reason = row['decision_reason']
        row.update(accepted=True, review_status='completed')
        check_background_counterexamples([row], models, trace)
        results.append(dict(kind='saved_failure', id=row['id'], original_reason=original_reason,
                            accepted=row['accepted'], status=row['review_status'],
                            reason=row.get('decision_reason'), check=row.get('counterexample_check')))
        trace.save('results.json', results)
        print(row['id'], row['review_status'], 'accepted=' + str(row['accepted']), flush=True)

    # Test-only controls spanning mathematics, zoology, and a conditional physical claim.
    controls = [
        (dict(id='arithmetic', source='even integers', relation='are_divisible_by', target='four'),
         'Six is an even integer but is not divisible by four.', True),
        (dict(id='zoology', source='all birds', relation='can', target='fly'),
         'Penguins are birds and cannot fly.', True),
        (dict(id='conditional_physics', source='pure water at one atmosphere', relation='boils_at', target='100 degrees Celsius'),
         'Pure water at high altitude under lower atmospheric pressure boils below 100 degrees Celsius.', False),
    ]
    for row, case, expected_valid in controls:
        check = CounterexampleCheck(reason='Focused applicability control.', sound_as_stated=False, counterexample=case)
        try:
            validate_counterexample(row, check, models, trace)
            valid, error = True, None
        except ValueError as exc:
            valid, error = False, str(exc)
        results.append(dict(kind='unrelated_control', id=row['id'], valid=valid,
                            expected_valid=expected_valid, passed=valid == expected_valid, error=error))
        trace.save('results.json', results)
        print(row['id'], 'passed=' + str(valid == expected_valid), flush=True)
    summary = dict(saved_cases=len(cases), resolved=sum(r['status'] != 'unresolved' for r in results if r['kind']=='saved_failure'),
                   controls_passed=all(r['passed'] for r in results if r['kind']=='unrelated_control'),
                   calls=models.calls, retries=models.retries, cache_hits=models.cache_hits)
    trace.save('summary.json', summary)
    print(json.dumps(summary), flush=True)
finally:
    trace.close()
