"""Record and verify the implementation/input freeze for the held-out run."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / 'outputs/explanation_fix_work/implementation_freeze.json'

def hashes():
    paths = {ROOT / '261273237.ipynb', ROOT / 'pipeline_settings.json', ROOT / 'README.md',
             ROOT / 'data/ai_test.txt', ROOT / 'data/AI Chapter.txt', ROOT / 'compose.yaml'}
    paths.update(ROOT.glob('*.py'))
    paths.update(ROOT.glob('requirements*.txt'))
    for directory in ('pipeline', 'tools', 'tests'):
        paths.update((ROOT / directory).rglob('*.py'))
    return {str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}

if sys.argv[1] == 'freeze':
    if SNAPSHOT.exists():
        raise SystemExit('Freeze already exists; refusing to overwrite it.')
    data = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'sha256': hashes(),
            'development_run_root': sys.argv[2], 'context_tokens': 24576,
            'focused_tests': {'count': 146, 'passed': True, 'log': 'targeted_tests_28.log'},
            'full_suite': {'count': 475, 'failures': 15, 'errors': 30,
                           'log': 'full_tests_subject_articles.log'},
            'final_run_requirements': {'fresh_output_root': True, 'resume': False,
                                      'model_cache_enabled': False, 'code_and_input_changes': False}}
    SNAPSHOT.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print(json.dumps({'freeze_file': str(SNAPSHOT), 'files': len(data['sha256']),
                      'frozen_at_utc': data['frozen_at_utc']}))
elif sys.argv[1] == 'verify':
    before = json.loads(SNAPSHOT.read_text(encoding='utf-8'))['sha256']
    after = hashes()
    changed = [p for p in sorted(before.keys() | after.keys()) if before.get(p) != after.get(p)]
    result = {'verified_at_utc': datetime.now(timezone.utc).isoformat(),
              'files_checked': len(before), 'unchanged': not changed, 'changed': changed}
    (SNAPSHOT.parent / 'freeze_verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    sys.exit(bool(changed))
else:
    raise SystemExit('Use freeze <development_run_root> or verify.')
