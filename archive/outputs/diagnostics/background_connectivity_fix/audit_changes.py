"""Inspect implementation changes relative to the saved repository baseline."""
import ast
import argparse
from collections import Counter
import difflib
import json
from pathlib import Path
import re
import subprocess


directory = Path(__file__).resolve().parent
root = directory.parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('terms', nargs='+', help='Run-specific terms to search in added implementation lines')
args = parser.parse_args()
original = json.loads(subprocess.check_output(['git', 'show', 'HEAD:261273237.ipynb'], cwd=root))
old = {cell['metadata']['module']: ''.join(cell['source']).split('\n', 1)[1]
       for cell in original['cells'] if 'module' in cell.get('metadata', {})}
modules = ('background_context', 'models', 'settings', 'registry', 'repair_budget', 'debate')
terms = re.compile(r'\b(?:' + '|'.join(re.escape(term) for term in args.terms) + r')\b', re.I)
audit, diffs = {}, []
for name in modules:
    module = 'pipeline.' + name
    source = (directory / (module + '.py')).read_text(encoding='utf-8')
    before = old.get(module, '')
    diff = list(difflib.unified_diff(before.splitlines(True), source.splitlines(True),
                                   fromfile=module + ':before', tofile=module + ':after'))
    added = [line[1:] for line in diff if line.startswith('+') and not line.startswith('+++')]
    def numbers(text):
        return Counter(repr(node.value) for node in ast.walk(ast.parse(text))
                       if isinstance(node, ast.Constant) and type(node.value) in (int, float))
    audit[module] = dict(added_lines=len(added), topic_word_matches=terms.findall(''.join(added)),
                         new_numeric_literals=dict(numbers(source) - numbers(before)))
    diffs.extend(diff)
protected = ('check_novelty', 'check_novelty_many', 'apply_verdict', 'review_background_many',
             'check_background_counterexamples', 'validate_review_consistency',
             'check_representation', 'connected_explanation')
def functions(source):
    return {node.name: ast.dump(node) for node in ast.parse(source).body if isinstance(node, ast.FunctionDef)}
before = functions(old['pipeline.debate'])
after = functions((directory / 'pipeline.debate.py').read_text(encoding='utf-8'))
checks = {name: before[name] == after[name] for name in protected}
(directory / 'genericity-audit.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
(directory / 'admission-checks-unchanged.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
(directory / 'source.diff').write_text(''.join(diffs), encoding='utf-8')
print(json.dumps(dict(audit=audit, admission_checks_unchanged=checks), indent=2))
