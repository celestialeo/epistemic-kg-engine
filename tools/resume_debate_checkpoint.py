"""Continue a complete debate checkpoint across a pinned validator migration.

Earlier inference stages are never invoked. Incompatible state is an error, not
a request to fall back to model-cache replay. Completed decisions stay unchanged.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import traceback
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
import _submission_runtime as runtime
from pipeline.checkpoints import Checkpoints
from pipeline.health import HealthMonitor
from pipeline.models import Models
from pipeline.registry import ConceptRegistry, FactIndex, RelationRegistry
from pipeline.settings import snapshot
from pipeline.trace import Trace


NONSEMANTIC = {'resume', 'output_root', 'input', 'no_open', 'no_explorer', 'explorer_port',
               'neo4j', 'start_neo4j', 'interact', 'new'}
MIGRATION_MODULES = {'pipeline/debate.py', 'pipeline/settings.py'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def fingerprint(text, config, code, models):
    return digest(dict(text=text, config={k: v for k, v in config.items() if k not in NONSEMANTIC},
                       code={k: v for k, v in code.items() if k != 'pipeline/graph_view.html'}, models=models))


def prepare_checkpoint(checkpoint_bytes, manifest, environment, text,
                       current_code, current_models, current_settings, policy):
    """Validate a concrete version transition before changing its fingerprint."""
    checkpoint_sha = hashlib.sha256(checkpoint_bytes).hexdigest()
    saved = json.loads(checkpoint_bytes)
    expected = manifest.get('artifacts', {}).get('artifacts/checkpoints/debate.json', {}).get('sha256')
    if not expected or checkpoint_sha != expected:
        raise ValueError('Debate checkpoint does not match its saved artifact hash')
    config = manifest['config']
    old_code = environment['code_sha256']
    old_models = environment['model_details']['installed_models']
    if fingerprint(text, config, old_code, old_models) != saved['signature']:
        raise ValueError('Original checkpoint signature does not verify')
    if current_settings != config['resolved_settings']:
        raise ValueError('Settings changed; checkpoint recovery cannot replay earlier stages')
    if current_models != old_models:
        raise ValueError('Installed model identities or metadata changed')
    changed = {name for name in old_code.keys() | current_code.keys()
               if old_code.get(name) != current_code.get(name)}
    if changed:
        if set(policy.get('changes', {})) != MIGRATION_MODULES or changed != MIGRATION_MODULES:
            raise ValueError('Code changes exceed the approved counterexample-validator migration')
        for name, transition in policy['changes'].items():
            if old_code.get(name) != transition['before'] or current_code.get(name) != transition['after']:
                raise ValueError('Code version is not the approved migration: ' + name)

    for name in saved['artifacts']:
        path = PurePosixPath(name)
        if '\\' in name or path.is_absolute() or '..' in path.parts or path.parts[0] != 'artifacts':
            raise ValueError('Invalid checkpoint artifact path: ' + name)
    read = lambda name: json.loads(saved['artifacts']['artifacts/' + name + '.json'])
    seeds = read('seeds')['selected']
    completed = saved['data']['completed_seeds']
    if len(set(completed)) != len(completed) or completed != [s['id'] for s in seeds[:len(completed)]]:
        raise ValueError('Checkpoint does not describe a completed seed prefix')
    if [t['seed']['id'] for t in saved['data']['transcripts']] != completed:
        raise ValueError('Checkpoint contains an incomplete seed transcript')
    candidates = saved['data']['candidates']
    if any(c['seed_id'] not in completed or c['review_status'] == 'pending' for c in candidates):
        raise ValueError('Checkpoint contains work from an incomplete seed')
    if read('debate_progress') != {k: saved['data'][k] for k in ('candidates', 'transcripts')}:
        raise ValueError('Checkpoint progress and saved decisions disagree')
    migration = dict(mode='pinned_validator_migration' if changed else 'exact',
                     policy=policy['id'] if changed else None, policy_sha256=digest(policy),
                     changed_modules=sorted(changed), original_signature=saved['signature'],
                     original_checkpoint_sha256=checkpoint_sha, completed_seeds=completed,
                     preserved_state_sha256=digest(saved['state']),
                     preserved_decisions_sha256=digest(saved['data']))
    prepared = copy.deepcopy(saved)
    prepared['signature'] = fingerprint(text, config, current_code, current_models)
    prepared['migration'] = migration
    return prepared, migration


class VerifiedCheckpoints(Checkpoints):
    def restore(self, name):
        data = super().restore(name)
        if name == 'debate':
            if data is None:
                raise ValueError('Required complete debate checkpoint could not be restored; replay is forbidden')
            concepts, relations, facts = self.registries
            actual = dict(concepts=concepts.entries, mentions=concepts.mentions, aliases=concepts.aliases,
                          chapter_names=concepts.chapter_names, relations=relations.entries,
                          decisions=relations.decisions, facts=facts.rows,
                          unresolved=self.trace.unresolved_items,
                          completed=sorted(self.trace.completed_items),
                          health={k: list(v) for k, v in self.trace.health.history.items()})
            saved = json.loads((self.source / 'artifacts/checkpoints/debate.json').read_text(encoding='utf-8'))
            # JSON represents completed-item tuples as lists.
            if digest(actual) != digest(saved['state']) or data != saved['data']:
                raise ValueError('Restored state differs from the committed checkpoint')
            self.trace.emit('checkpoint.state_verified', checkpoint=name,
                            completed_seeds=data['completed_seeds'], state_sha256=digest(actual))
        return data


def check_preserved(prefix, result, source_artifacts, directory):
    for name in ('candidates', 'transcripts'):
        if result[name][:len(prefix[name])] != prefix[name]:
            raise ValueError('A completed checkpoint decision changed: ' + name)
    for name in ('paragraphs', 'chunks', 'extractions', 'extraction_review', 'source_coverage',
                 'chapter_outline', 'seeds', 'seed_progress', 'concept_reconciliation'):
        key = 'artifacts/' + name + '.json'
        if (directory / key).read_text(encoding='utf-8') != source_artifacts[key]:
            raise ValueError('An earlier stage artifact changed: ' + key)


def run(source, output_root, *, verify_only=False):
    source, output_root = Path(source).resolve(), Path(output_root).resolve()
    if output_root.is_relative_to(source):
        raise ValueError('Recovery output must be outside the original run')
    read = lambda name: json.loads((source / name).read_text(encoding='utf-8'))
    manifest, environment = read('manifest.json'), read('artifacts/environment.json')
    raw_checkpoint = (source / 'artifacts/checkpoints/debate.json').read_bytes()
    saved = json.loads(raw_checkpoint)
    text = (source / 'input.txt').read_text(encoding='utf-8')
    config = copy.deepcopy(manifest['config'])
    config['output_root'] = str(output_root)
    policy = json.loads(Path(__file__).with_name('counterexample_checkpoint_migration.json').read_text(encoding='utf-8'))
    identifier = 'recovery_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8]
    trace = Trace(output_root / identifier, identifier)
    trace.health = HealthMonitor(trace, config['health_window'], config['health_min_samples'],
                                 config['health_max_failure_rate'])
    record = dict(schema_version=1, run_id=identifier, status='running', source_run=str(source),
                  config=config, scope='complete_debate_checkpoint_continuation',
                  pipeline_stages=['checkpoint_restore', 'debate', 'graph', 'evaluation'],
                  started_at=datetime.now(timezone.utc).isoformat(), no_earlier_stage_replay=True)
    trace.save('manifest.json', record)
    print('Recovery directory:', trace.directory, flush=True)
    try:
        from dotenv import load_dotenv
        load_dotenv(runtime.root / '.env', override=False)
        models = Models(trace, config['model'], config['embedding_model'],
                        os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434'),
                        timeout=config['model_timeout'], think=config['think'],
                        context_tokens=config['context_tokens'], max_output_tokens=config['max_output_tokens'],
                        registry_model=config.get('registry_model'), batch_size=config.get('batch_size'),
                        identity_candidates=config.get('identity_candidates'),
                        document_context_tokens=config['document_context_tokens'],
                        document_output_tokens=config['document_output_tokens'])
        models.cache_enabled = False  # Do not load or reuse any prior review responses.
        models.preflight()
        prepared, migration = prepare_checkpoint(raw_checkpoint,
            manifest, environment, text, runtime.source_hashes(), models.details['installed_models'], snapshot(), policy)
        record['checkpoint_migration'] = migration
        trace.emit('checkpoint.migration_verified', **migration)
        trace.text('input.txt', text)
        trace.save('artifacts/environment.json', dict(model_details=models.details,
                                                     code_sha256=runtime.source_hashes()))
        trace.save('recovery_source/artifacts/checkpoints/debate.json', prepared)
        trace.save('recovery_source/original_checkpoint.json', saved)
        concepts, relations = ConceptRegistry(models, trace), RelationRegistry(models, trace)
        facts = FactIndex(relations)
        trace.checkpoints = VerifiedCheckpoints(trace, models, text, config, (concepts, relations, facts),
                                               trace.directory / 'recovery_source')
        if verify_only:
            trace.checkpoints.restore('debate')
            check_preserved(saved['data'], prepared['data'], saved['artifacts'], trace.directory)
            record['status'] = 'checkpoint_verified'
            print('Verified completed seeds:', ', '.join(saved['data']['completed_seeds']), flush=True)
            return trace.directory

        # All inputs come from the same complete snapshot, never mutable latest-progress files.
        artifact = lambda name: json.loads(saved['artifacts']['artifacts/' + name + '.json'])
        paragraphs, chunks, extractions = artifact('paragraphs'), artifact('chunks'), artifact('extractions')
        outline, seeds, reviews = artifact('chapter_outline'), artifact('seeds')['selected'], artifact('extraction_review')
        from pipeline.debate import debate
        from pipeline.graph_view import build_graph, render_graph
        from pipeline.evaluation import evaluate
        from pipeline.report import statistics_for, render_report
        with trace.span('debate'):
            result = debate(seeds, chunks, outline, concepts, relations, facts, models, trace, reviews,
                            proposal_limit=config['background_proposal_limit'])
            check_preserved(saved['data'], result, saved['artifacts'], trace.directory)
            trace.emit('checkpoint.prior_work_preserved', completed_seeds=saved['data']['completed_seeds'])
            trace.save('artifacts/debate.json', result)
        with trace.span('graph'):
            graph = build_graph(text, paragraphs, chunks, extractions, result, trace, concepts, relations)
            record.update(graph_quality_required=False, graph_quality_status='not_run',
                          graph_acceptance_policy='document_review_and_background_debate')
            trace.save('artifacts/graph.json', graph)
            trace.text('knowledge_graph.html', render_graph(graph))
        with trace.span('evaluation'):
            evaluation = evaluate(chunks, graph, models, trace)
            trace.save('artifacts/evaluation.json', evaluation)
            trace.text('reconstruction.txt', '\n\n'.join(row['reconstruction'] for row in evaluation['results']) + '\n')
            stats = statistics_for(paragraphs, chunks, extractions, result, graph, evaluation, models, trace)
            trace.save('statistics.json', stats)
            page, markdown = render_report(stats, paragraphs, chunks, result, evaluation)
            trace.text('index.html', page)
            trace.text('report.md', markdown)
        check_preserved(saved['data'], result, saved['artifacts'], trace.directory)
        record['incomplete_extraction_chunks'] = [e['chunk_id'] for e in extractions if e['status'] == 'incomplete']
        incomplete = record['incomplete_extraction_chunks'] or trace.unresolved_items or evaluation['status'] != 'completed'
        record.update(status='completed_with_issues' if incomplete else 'completed',
                      evaluation_status=evaluation['status'], reconstruction_score=evaluation['final_score'])
        print('Completed:', trace.directory / 'index.html', record['status'], flush=True)
        return trace.directory
    except BaseException as exc:
        record.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed',
                      error=str(exc), error_type=type(exc).__name__)
        trace.emit('run.failed', error=str(exc), error_type=type(exc).__name__, traceback=traceback.format_exc())
        raise
    finally:
        record.update(finished_at=datetime.now(timezone.utc).isoformat(),
                      unresolved_items=getattr(trace, 'unresolved_items', []),
                      performance=dict(model_calls=getattr(locals().get('models'), 'calls', 0),
                                       cache_hits=getattr(locals().get('models'), 'cache_hits', 0)),
                      artifacts={k: v for k, v in trace.artifacts.items() if k != 'manifest.json'})
        trace.save('manifest.json', record)
        trace.emit('run.closed', status=record['status'])
        trace.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    run(args.source, args.output_root, verify_only=args.verify_only)
