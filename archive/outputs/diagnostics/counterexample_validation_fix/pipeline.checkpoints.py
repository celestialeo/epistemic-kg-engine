"""Atomic, fingerprinted stage/item checkpoints; model-cache replay is the fallback."""
import hashlib
import json
from pathlib import Path
import _submission_runtime as notebook


class Checkpoints:
    def __init__(self, trace, models, text, config, registries, source=None):
        self.trace, self.registries = trace, registries
        self.source = Path(source) if source else None
        semantic = {key: value for key, value in config.items() if key not in {
            'resume', 'output_root', 'input', 'no_open', 'no_explorer', 'explorer_port',
            'neo4j', 'start_neo4j', 'interact', 'new'}}
        details = getattr(models, 'details', {})
        # The graph view is rendered again after restored inference stages.
        # Changing its labels/styles must not invalidate saved model work.
        code = {name: digest for name, digest in notebook.source_hashes().items()
                if name != 'pipeline/graph_view.html'}
        signature = dict(text=text, config=semantic, code=code,
                         models=details.get('installed_models', {}))
        self.signature = hashlib.sha256(json.dumps(signature, sort_keys=True, default=str).encode()).hexdigest()

    def save(self, name, data):
        concepts, relations, facts = self.registries
        state = dict(concepts=concepts.entries, mentions=concepts.mentions,
                     aliases=concepts.aliases, chapter_names=concepts.chapter_names,
                     relations=relations.entries, decisions=relations.decisions, facts=facts.rows,
                     unresolved=getattr(self.trace, 'unresolved_items', []),
                     completed=sorted(getattr(self.trace, 'completed_items', set())),
                     health={k: list(v) for k, v in self.trace.health.history.items()})
        artifacts = {key: value for key, value in self.trace.artifacts.items()
                     if key.startswith('artifacts/') and not key.startswith(('artifacts/checkpoints/', 'artifacts/model_cache/'))
                     and key not in {'artifacts/environment.json', 'artifacts/cache_sources.json'}}
        # Saved artifact bytes are included: later stages may replace their files.
        # A checkpoint must remain a consistent snapshot of the earlier state.
        contents = {key: (self.trace.directory / key).read_text(encoding='utf-8') for key in artifacts}
        self.trace.save('artifacts/checkpoints/' + name + '.json', dict(
            signature=self.signature, data=data, state=state, artifacts=contents))

    def restore(self, name):
        if self.source is None:
            return None
        path = self.source / 'artifacts/checkpoints' / (name + '.json')
        if not path.exists():
            return None
        saved = json.loads(path.read_text(encoding='utf-8'))
        if saved['signature'] != self.signature:
            self.trace.emit('checkpoint.invalidated', checkpoint=name, reason='Input, code, model or settings changed')
            return None
        state = saved['state']
        concepts, relations, facts = self.registries
        concepts.entries, concepts.mentions = state['concepts'], state['mentions']
        concepts.aliases, concepts.chapter_names = state['aliases'], state['chapter_names']
        relations.entries, relations.decisions, facts.rows = state['relations'], state['decisions'], state['facts']
        self.trace.unresolved_items = state['unresolved']
        self.trace.completed_items = {tuple(pair) for pair in state['completed']}
        self.trace.health.history.clear()
        for step, rows in state['health'].items():
            self.trace.health.history[step].extend(rows)
        for key, value in saved['artifacts'].items():
            self.trace.text(key, value)
        self.trace.save('artifacts/checkpoints/' + name + '.json', saved)
        self.trace.emit('checkpoint.restored', checkpoint=name, source=str(path))
        return saved['data']
