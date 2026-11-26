"""Complete only the saved LLM-tuning document evaluation, preserving chunk results."""
import argparse
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from pipeline.evaluation import compare_texts, METRIC_VERSION, METRIC_WEIGHTS
from pipeline.models import Models
from pipeline.report import render_report
from pipeline.trace import Trace
import _submission_runtime as runtime

RUN = ROOT/'outputs/runs/llm-tuning/run_20261125_034536_UTC-0500_9e4db7ab'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).astimezone(ZoneInfo('America/Toronto')).isoformat()


def is_missing_document(item):
    return item.get('step')=='evaluation' and item.get('id')=='evaluation:document'


class DocumentModels(Models):
    def ask(self, role, instruction, payload, schema, entity_id, validator=None, **kwargs):
        if not entity_id.startswith('evaluation:document'):
            raise ValueError('This recovery permits only full-document evaluation calls.')
        print(f'  {role}: {entity_id}', flush=True)
        return super().ask(role, instruction, payload, schema, entity_id, validator, **kwargs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context-tokens', type=int, default=32768)
    parser.add_argument('--output-tokens', type=int, default=12288)
    parser.add_argument('--resume', type=Path)
    args=parser.parse_args()
    if not 0 < args.output_tokens < args.context_tokens:
        parser.error('Output tokens must be positive and smaller than the context.')
    manifest=read(RUN/'manifest.json')
    previous=read(RUN/'artifacts/evaluation.json')
    chunks=sorted(read(RUN/'artifacts/chunks.json'),key=lambda row:row['order'])
    rows=previous['results']
    assert manifest['status'] in {'completed','completed_with_issues'}
    assert previous['metric_version']==METRIC_VERSION
    assert previous['weights']==dict(METRIC_WEIGHTS)
    assert len(rows)==len(chunks) and rows
    assert all(row['chunk_id']==chunk['id'] and row['original']==chunk['text'] and
               row['status']=='completed' for row,chunk in zip(rows,chunks))
    assert (RUN/'reconstruction.txt').read_text(encoding='utf-8')=='\n\n'.join(row['reconstruction'] for row in rows)+'\n'
    immutable_names=['input.txt','artifacts/graph.json','artifacts/chunks.json','reconstruction.txt',
                     'events.jsonl','artifacts/debate.json','artifacts/extractions.json','artifacts/paragraphs.json']
    immutable={name:sha(RUN/name) for name in immutable_names}
    config=manifest['config']
    identifier='document_evaluation_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:8]
    directory=Path(__file__).resolve().parent/identifier
    trace=Trace(directory,identifier)
    metadata=dict(scope='full_document_only',source_run=manifest['run_id'],status='running',
                  started_at=now(),source_sha256=immutable,chunk_results_preserved=True,
                  context_tokens=args.context_tokens,max_output_tokens=args.output_tokens,
                  think=False,metric_version=METRIC_VERSION,
                  trace_directory=os.path.relpath(directory,RUN).replace('\\','/'))
    trace.save('manifest.json',metadata)
    backups=['manifest.json','statistics.json','artifacts/evaluation.json','artifacts/evaluation_progress.json',
             'artifacts/unresolved_items.json','index.html','report.md','run.log']
    before={name:(RUN/name).read_bytes() for name in backups if (RUN/name).exists()}
    for name,raw in before.items():
        target=directory/'before'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
    models=None
    try:
        models=DocumentModels(trace,config['model'],config.get('embedding_model','nomic-embed-text'),
                              os.environ.get('OLLAMA_HOST','http://127.0.0.1:11434'),
                              timeout=max(config.get('model_timeout',600),1200),think=False,
                              context_tokens=args.context_tokens,max_output_tokens=args.output_tokens,
                              document_context_tokens=args.context_tokens,document_output_tokens=args.output_tokens)
        print('Evaluation trace:',directory,flush=True)
        print('Preserving all six chunk results; evaluating only the complete texts.',flush=True)
        models.preflight()
        trace.save('artifacts/environment.json',dict(model_details=models.details,
                   code_sha256=runtime.source_hashes(),effective_options=models.options,
                   original_config=config))
        if args.resume:
            prior=read(args.resume/'manifest.json')
            assert prior['source_sha256']==immutable
            models.load_cache(args.resume)
        with trace.span('evaluation'):
            scores=compare_texts('\n\n'.join(row['original'] for row in rows),
                                 '\n\n'.join(row['reconstruction'] for row in rows),
                                 models,'evaluation:document')
            trace.emit('evaluation.metrics_computed',entity_id='evaluation:document',**scores)
        trace.save('document_metrics.json',scores)
        assert isinstance(scores['final_score'],(int,float)) and 0 <= scores['final_score'] <= 100
        result=deepcopy(previous)
        result.update(document_metrics=scores,final_score=scores['final_score'],status='completed',reason=None)
        assert result['results']==previous['results'] and result['summary']==previous['summary']
        metadata.update(status='completed',finished_at=now(),duration_seconds=time.monotonic()-trace.started,
                        final_score=scores['final_score'],unresolved_items=[],
                        models=dict(generation=models.model,calls=models.calls,retries=models.retries,
                                    cache_hits=models.cache_hits,prompt_tokens=models.prompt_tokens,
                                    output_tokens=models.output_tokens))
        stats=read(RUN/'statistics.json')
        stats.update(reconstruction_score=scores['final_score'],evaluation_status='completed',evaluation=metadata)
        stats['unresolved_items']=[item for item in stats.get('unresolved_items',[]) if not is_missing_document(item)]
        unresolved=read(RUN/'artifacts/unresolved_items.json')
        unresolved=[item for item in unresolved if not is_missing_document(item)]
        updated=deepcopy(manifest)
        updated.update(evaluation_status='completed',reconstruction_score=scores['final_score'],evaluation=metadata)
        updated['unresolved_items']=[item for item in updated.get('unresolved_items',[]) if not is_missing_document(item)]
        updated.setdefault('evaluation_history',[]).append(metadata)
        page,report=render_report(stats,read(RUN/'artifacts/paragraphs.json'),chunks,read(RUN/'artifacts/debate.json'),result)
        notice=('Graph generation includes the original execution and checkpoint recovery. '
                'The missing full-document evaluation was completed separately at '+metadata['finished_at']+
                '; the saved graph, reconstruction, and six chunk scores were preserved.')
        page=page.replace('<body>','<body><p>'+notice+'</p>',1)
        report=report.replace('\n\n','\n\n'+notice+'\n\n',1)
        log=before['run.log'].decode('utf-8')
        log=log.replace('Evaluation: incomplete','Evaluation: completed (full-document reevaluation recorded below)',1)
        log=log.replace('Final unresolved items: '+str(len(manifest.get('unresolved_items',[]))),
                        'Final unresolved items: '+str(len(updated['unresolved_items'])),1)
        log+=('\n'+metadata['finished_at']+' | INFO | evaluation | Full-document reevaluation completed: '
              +format(scores['final_score'],'.2f')+'/100. Saved graph and chunk scores preserved.\n')
        outputs={'artifacts/evaluation.json':encoded(result),'artifacts/unresolved_items.json':encoded(unresolved),
                 'statistics.json':encoded(stats),'index.html':page.encode('utf-8'),
                 'report.md':report.encode('utf-8'),'run.log':log.encode('utf-8')}
        for name,raw in outputs.items():
            target=directory/'published'/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(raw)
            if name!='run.log':
                updated.setdefault('artifacts',{})[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
        outputs['manifest.json']=encoded(updated)
        for name,digest in immutable.items():
            assert sha(RUN/name)==digest, 'Source changed during evaluation: '+name
        for name,raw in before.items():
            assert (RUN/name).read_bytes()==raw, 'Published result changed concurrently: '+name
        for name,raw in outputs.items():
            pending=(RUN/name).with_name(Path(name).name+'.'+identifier+'.tmp')
            pending.write_bytes(raw)
            pending.replace(RUN/name)
        for name,digest in immutable.items():
            assert sha(RUN/name)==digest
        assert read(RUN/'artifacts/evaluation.json')['results']==rows
        # Refresh only the stored manifest for this existing graph identity.
        db=ROOT/'outputs/professor/students.sqlite3'
        with closing(sqlite3.connect(db,timeout=30)) as connection:
            records=connection.execute('SELECT id,directory,snapshot FROM runs').fetchall()
            matching=[r for r in records if Path(r[1]).resolve()==RUN.resolve()]
            assert len(matching)==1
            key,_,raw_snapshot=matching[0]
            trace.text('before/database_run_snapshot.json',raw_snapshot)
            snapshot=json.loads(raw_snapshot)
            snapshot['manifest']=updated
            with connection:
                connection.execute('UPDATE runs SET snapshot=? WHERE id=?',(json.dumps(snapshot),key))
            assert connection.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        trace.emit('evaluation.published',source_run=manifest['run_id'],final_score=scores['final_score'])
        print(json.dumps(dict(status='completed',final_score=scores['final_score'],
                              original_claims=scores.get('original_claim_count'),
                              reconstructed_claims=scores.get('reconstructed_claim_count'),
                              matched_claims=scores.get('matched_claim_count'),model_calls=models.calls,
                              trace_directory=str(directory)),indent=2),flush=True)
    except BaseException as exc:
        metadata.update(status='failed',error=str(exc),error_type=type(exc).__name__,finished_at=now())
        trace.emit('evaluation.failed',error=str(exc),error_type=type(exc).__name__)
        raise
    finally:
        trace.save('manifest.json',metadata)
        trace.close()


if __name__=='__main__':
    main()
