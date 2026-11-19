"""Development helper: replace existing notebook modules from an explicit directory.

The notebook remains the implementation source. This tool never imports modules or
executes experiments. Temporary editable copies are not runtime dependencies.
"""
import argparse
import json
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('modules', nargs='*')
    parser.add_argument('--assets', nargs='*', default=[])
    args = parser.parse_args()
    notebook = Path(__file__).resolve().parents[1] / '261273237.ipynb'
    document = json.loads(notebook.read_text(encoding='utf-8'))
    for name in args.modules:
        source = (args.directory / (name + '.py')).read_text(encoding='utf-8')
        compile(source, name, 'exec')
        cell = next((c for c in document['cells'] if c.get('metadata', {}).get('module') == name), None)
        if cell is None:
            cell = dict(id=uuid.uuid4().hex, cell_type='code', metadata={'module': name}, execution_count=None, outputs=[], source=[])
            index = max(i for i, c in enumerate(document['cells']) if 'module' in c.get('metadata', {}))
            document['cells'].insert(index, cell)
        cell['source'] = ('%%pipeline_module ' + name + '\n' + source).splitlines(keepends=True)
    for name in args.assets:
        source = (args.directory / Path(name).name).read_text(encoding='utf-8')
        cell = next((c for c in document['cells'] if c.get('metadata', {}).get('asset') == name), None)
        if cell is None:
            cell = dict(id=uuid.uuid4().hex, cell_type='code', metadata={'asset': name}, execution_count=None, outputs=[], source=[])
            index = max(i for i, c in enumerate(document['cells']) if 'module' in c.get('metadata', {}))
            document['cells'].insert(index, cell)
        header = ''.join(cell['source']).split('\n', 1)[0] or ('%%project_asset ' + name)
        cell['source'] = (header + '\n' + source).splitlines(keepends=True)
    notebook.write_text(json.dumps(document, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
