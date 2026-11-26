"""Append an auditable fictional-learner exercise through the unchanged quiz API.

Never resets existing records. Answers are manually authored from public questions
and targeted graph relationships, without expected answers or assessment criteria.
The three-question limit applies only inside this process, never to production.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app, make_models
from pipeline.settings import SETTINGS
from pipeline.student_store import StudentStore
from populate_student_profiles import backup, now, write as _write_json

WORK = ROOT / 'outputs/student_profiles/additional_quizzes'
LEDGER = WORK / 'metadata.json'
DB = ROOT / 'outputs/professor/students.sqlite3'


def write(path,value):
    # Windows readers/antivirus may briefly hold the destination open. This only
    # retries the same local JSON save, never an answer or model decision.
    for attempt in range(5):
        try:
            return _write_json(path,value)
        except PermissionError:
            if attempt==4: raise
            time.sleep(0.1*(attempt+1))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initialize():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding='utf-8'))
    original = json.loads((WORK.parent/'metadata.json').read_text(encoding='utf-8'))
    destination = ROOT/'archive/databases'/('additional_student_quizzes_'+now().replace(':','').replace('.',''))
    backup(DB, destination/'students.sqlite3')
    protected = [ROOT/'261273237.ipynb', ROOT/'pipeline_settings.json', WORK.parent/'metadata.json']
    for path in (ROOT/'outputs/runs').glob('*/*/artifacts/graph.json'):
        protected.append(path)
    for path in (ROOT/'outputs/runs').glob('*/*/manual_graph.sqlite3'):
        backup(path, destination/path.relative_to(ROOT/'outputs/runs'))
    graph = json.loads(next((ROOT/'outputs/runs/neurons-and-glia').glob('*/artifacts/graph.json')).read_text())
    microglia = next(n['id'] for n in graph['nodes'] if n['label'] == 'microglia')
    specialty = [e['id'] for e in graph['edges'] if microglia in (e['source'],e['target'])]
    profiles = original['profiles'] + [dict(key='liam', name='Liam Morgan', profile='Concept specialist',
        strengths='Microglia: phagocytic defense, regulation of connections, synaptic pruning, pattern recognition receptors, and phagocytosis. Struggles elsewhere, including other neurons-and-glia concepts.')]
    ledger = dict(origin='Fictional students and authored simulated answers; not real learners.',
        created_at=now(), backup=str(destination.relative_to(ROOT)),
        policy='Append only. Actual quiz API, question generation, submission and grading. Author from targeted graph meaning/direction/conditions and profile, never hidden expected answers or criteria. No internet. No outcome-driven resubmissions. At most two HTTP attempts for technical failures, using the same durable request ID and body.',
        round_questions=3, planned_quizzes_per_student=6, planned_questions_per_student=18,
        profiles=profiles, students=original['students'], topics=original['topics'],
        specialty=dict(topic='neurons and glia', concept_id=microglia, label='microglia', relationship_ids=specialty),
        protected_hashes={str(p.relative_to(ROOT)):digest(p) for p in protected},
        sessions={}, commands={}, contributions={})
    write(LEDGER, ledger)
    return ledger


def reference(store, entry):
    checkpoint = store.session(entry['state']['id'])['checkpoint']
    graph = checkpoint['graph_snapshot']
    nodes = {n['id']:n['label'] for n in graph['nodes']}
    # Read only target IDs from examiner material, never expected answers/criteria.
    requested = {f['id'] for f in checkpoint['question']['examiner_material']['facts']}
    return [dict(id=e['id'], subject=nodes[e['source']], relationship=e['label'], object=nodes[e['target']],
                 **{k:e.get(k) for k in ('definition','conditions','modality','purpose','timing','negated','argument_qualifiers')},
                 participants=[dict(role=p['role'],concept=nodes[p['node']]) for p in e.get('participants',[])])
            for e in graph['edges'] if e['id'] in requested]


def focus_labels(profile, topic, round_number):
    # Ordinary UI focus choices, fixed before outcomes; eligibility remains normal.
    if topic == 'ai test':
        return ['regularization','regularization','quantization'] if round_number == 1 else ['retrieval augmented generation','retrieval augmented generation','self attention']
    if topic == 'llm tuning':
        return ['standard fine tuning','fine tuning','parameter efficient tuning'] if round_number == 1 else ['distillation','teacher model','offline inference']
    if round_number == 1:
        return ['microglia']*3 if profile == 'liam' else ['brain astrocyte networks']*3
    return ['axon','soma','axon terminals']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['init','start','questions','submit','next','help','contributions','metrics','verify'])
    parser.add_argument('--round',type=int,choices=[1,2],default=1)
    parser.add_argument('--session')
    parser.add_argument('--answers',type=Path)
    parser.add_argument('--advance',action='store_true',help='After submissions, request the next question or normal completion')
    parser.add_argument('--help-kind',choices=['hint','reveal'],default='hint')
    args=parser.parse_args()
    ledger=initialize() if args.action=='init' else json.loads(LEDGER.read_text(encoding='utf-8'))
    SETTINGS['ui']['quiz_round_questions']=3
    store=StudentStore(DB)
    def save(): write(LEDGER,ledger)
    def models(snapshot,trace):
        instance=make_models(snapshot,trace)
        ask=instance.ask
        def timed(role,*a,**kw):
            start=time.monotonic();print('MODEL',role,flush=True)
            result=ask(role,*a,**kw)
            print('DONE',role,round(time.monotonic()-start,1),'s',flush=True)
            return result
        instance.ask=timed
        return instance
    with TestClient(create_app([],professor_store=store,runs_root=ROOT/'outputs/runs',model_factory=models),base_url='http://127.0.0.1') as client:
        def get(path):
            response=client.get('/api/professor/'+path);response.raise_for_status();return response.json()
        def post(path,body): return client.post('/api/professor/'+path,json=body)
        catalog=get('catalog')
        topics=sorted(catalog['topics'],key=lambda t:t['title'])
        assert len(topics)==3
        if args.action=='init':
            profile=ledger['profiles'][-1]
            existing=[s for s in store.students() if s['name']==profile['name']]
            assert len(existing)<=1
            if existing: student=existing[0]
            else:
                response=post('students',dict(name=profile['name']));response.raise_for_status();student=response.json()
            ledger['students'][profile['key']]=student
            assert len(store.students())==4
            assert {s['id']:s['name'] for s in store.students()}=={s['id']:s['name'] for s in ledger['students'].values()}
            assert Counter(e['profile'] for e in ledger['sessions'].values())==Counter({p['key']:6 for p in ledger['profiles']})
            assert all(len(r['attempts'])<=2 for r in ledger['commands'].values())
            for path in WORK.glob('answers_r*.json'):
                for key,authored in json.loads(path.read_text(encoding='utf-8')).items():
                    matches=[r for k,r in ledger['commands'].items() if k.startswith(key+':answer:') and r['body']['question_id']==authored['question_id']]
                    assert len(matches)==1 and matches[0]['body']['text']==authored['text']
            save();print('Backup saved; existing students retained; fourth student:',student);return
        def metrics(student,run):
            topic=next(t for t in topics if t['id']==run)
            data=get('scope?'+urlencode(dict(student_id=student,topic=topic['topic_key'],run_id=run)))
            selected=data['selected']
            return dict(at=now(),metrics=selected['metrics'],categories=selected['categories'],graph_metrics=selected.get('graph_metrics'),unique_relationships=data['unique_relationships'])
        def focus(entry,number):
            label=entry['focus_labels'][min(number-1,2)]
            graph=next(r for r in store.runs() if r['id']==entry['run_id'])['snapshot']['graph']
            return next(n['id'] for n in graph['nodes'] if n['label']==label)
        def command(key,action,entry,**extra):
            state=entry.get('state')
            number=state['state']['question']['number'] if state else 0
            command_key=f'{key}:{action}:{number}'
            record=ledger['commands'].get(command_key)
            if record is None:
                body=dict(action=action,request_id=str(uuid.uuid4()),**extra)
                if action!='start': body.update(session_id=state['id'],question_id=state['state']['question']['id'])
                record=dict(body=body,attempts=[],status='pending');ledger['commands'][command_key]=record;save()
            else:
                for field,value in extra.items():
                    if record['body'].get(field)!=value: raise ValueError('Refusing changed request '+command_key)
            if record['status']=='completed': return record['response']
            if record['status']=='exhausted': return None
            while len(record['attempts'])<2:
                print('REQUEST',key,action,number,flush=True)
                attempt=dict(started_at=now(),status='in_flight');record['attempts'].append(attempt);save()
                try:
                    response=post('quiz',record['body'])
                except Exception as exc:
                    attempt.update(at=now(),status='transport_failure',error=repr(exc));save();continue
                attempt.update(at=now(),status=response.status_code,error=response.json() if response.status_code!=200 else None)
                if response.status_code==200:
                    record.update(status='completed',response=response.json());entry['state']=response.json();save();return response.json()
                if response.status_code==422 and ('No eligible unmastered facts remain' in response.text or 'All eligible facts are covered' in response.text):
                    record['status']='exhausted'
                    entry['stop_reason']=dict(kind='eligible_questions_exhausted',command=command_key,message=response.json())
                    print('ELIGIBLE QUESTIONS EXHAUSTED',key,flush=True);save();return None
                print('TECHNICAL FAILURE',response.status_code,response.text[:1000],flush=True);save()
                if response.status_code not in (503,409) or (response.status_code==409 and 'Another graph request' not in response.text): break
            record['status']='unresolved';entry['stop_reason']=dict(command=command_key,error=record['attempts'][-1]);save();return None
        if args.action=='start':
            for profile in ledger['profiles']:
                student=ledger['students'][profile['key']]
                for topic in topics:
                    key=f"{profile['key']}:{topic['title']}:r{args.round}"
                    if args.session and key!=args.session: continue
                    entry=ledger['sessions'].setdefault(key,dict(student_id=student['id'],run_id=topic['id'],profile=profile['key'],topic=topic['title'],round=args.round,focus_labels=focus_labels(profile['key'],topic['title'],args.round)))
                    if entry.get('state'): continue
                    entry.setdefault('before',metrics(student['id'],topic['id']));save()
                    command(key,'start',entry,student_id=student['id'],run_id=topic['id'],focus_id=focus(entry,1))
        selected={k:v for k,v in ledger['sessions'].items() if v['round']==args.round and (not args.session or args.session==k)}
        if args.action=='questions':
            result={}
            for key,entry in selected.items():
                if not entry.get('state'): continue
                q=entry['state']['state']['question']
                if entry['state']['state']['completed'] or q['attempts'] or entry.get('stop_reason'): continue
                result[key]=dict(question_id=q['id'],number=q['number'],question=q['text'],assistance=q['help_text'],reference_relationships=[{k:v for k,v in r.items() if v not in (None,[])} for r in reference(store,entry)])
            print(json.dumps(result,indent=2,ensure_ascii=False));return
        if args.action=='help':
            assert args.session
            for key,entry in selected.items():
                response=command(key,args.help_kind,entry)
                if response: print(json.dumps(response['state']['question'],ensure_ascii=False))
        if args.action=='submit':
            authored=json.loads(args.answers.read_text(encoding='utf-8'))
            for key,answer in authored.items():
                entry=selected[key];q=entry['state']['state']['question']
                assert answer['question_id']==q['id'],key
                previous=entry.get('submissions',{}).get(str(q['number']))
                if previous:
                    assert previous['answer']==answer['text'],'Refusing answer rewrite'
                    continue
                targets=reference(store,entry)
                result=command(key,'answer',entry,text=answer['text'])
                if result:
                    entry.setdefault('submissions',{})[str(q['number'])]=dict(question=dict(q),reference_relationships=targets,answer=answer['text'],answer_id=result['contribution_answer_id'],score=result['answer_score'],feedback=result['state']['question']['feedback'],result=result['state']['last_result'],at=now())
                    print('OUTCOME',key,result['answer_score'],result['state']['question']['feedback'],flush=True);save()
        if args.action=='next' or (args.action=='submit' and args.advance):
            for key,entry in selected.items():
                state=entry.get('state')
                if state and not state['state']['completed'] and state['state']['question']['attempts'] and not entry.get('stop_reason'):
                    number=state['state']['question']['number']+1
                    command(key,'next',entry,focus_id=focus(entry,number))
        if args.action=='contributions':
            for key,entry in selected.items():
                for submission in entry.get('submissions',{}).values():
                    answer_id=submission['answer_id'];previous=ledger['contributions'].get(answer_id,{})
                    if previous.get('completed') or previous.get('attempts',0)>=2: continue
                    print('CONTRIBUTIONS',key,answer_id,flush=True)
                    ledger['contributions'][answer_id]=dict(previous,attempts=previous.get('attempts',0)+1);save()
                    response=post('answers/'+answer_id+'/contributions/check',{})
                    if response.status_code!=200:
                        ledger['contributions'][answer_id].update(error=response.text);save();continue
                    data=response.json();job=next(j for j in data['jobs'] if j['answer_id']==answer_id)
                    ledger['contributions'][answer_id].update(completed=job['status']=='completed',job=job,records=[r for r in data['contributions'] if r['answer_id']==answer_id]);save()
        if args.action in ('metrics','next','submit'):
            for key,entry in selected.items(): entry['after']=metrics(entry['student_id'],entry['run_id'])
        if args.action=='verify':
            results={}
            for path,expected in ledger['protected_hashes'].items(): assert digest(ROOT/path)==expected,path
            results['production_code_settings_original_graphs_and_previous_ledger_unchanged']=True
            with closing(sqlite3.connect(ROOT/ledger['backup']/'students.sqlite3')) as before,closing(sqlite3.connect(DB)) as after:
                for table, in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='runs'").fetchall():
                    old=Counter(before.execute('SELECT * FROM '+table).fetchall());new=Counter(after.execute('SELECT * FROM '+table).fetchall())
                    assert not old-new,'Old records changed: '+table
                    if table in ('overrides','fact_approvals'):
                        assert old==new,'Unexpected change to '+table
                    results[table]=dict(before=sum(old.values()),after=sum(new.values()),all_old_rows_preserved=True)
                assert after.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                assert not after.execute('PRAGMA foreign_key_check').fetchall()
                assert not after.execute("SELECT session_id,json_extract(question,'$.id') FROM answers GROUP BY session_id,json_extract(question,'$.id') HAVING count(*)>1").fetchall()
            archived=ROOT/ledger['backup']
            for original in archived.glob('*/*/manual_graph.sqlite3'):
                current=ROOT/'outputs/runs'/original.relative_to(archived)
                with closing(sqlite3.connect(original)) as before,closing(sqlite3.connect(current)) as after:
                    assert not Counter(before.execute('SELECT * FROM changes').fetchall())-Counter(after.execute('SELECT * FROM changes').fetchall()),str(current)
            results['prior_professor_and_student_graph_changes_preserved']=True
            assert len(store.students())==4
            from pipeline.contributions import Contributions
            from pipeline.assessment import eligible_fact
            contribution_ids={r['id'] for r in Contributions(store).rows()}
            student_ids={s['id'] for s in store.students()}
            for run in store.runs():
                for edge in run['snapshot']['graph']['edges']:
                    if edge.get('origin')=='student':
                        assert edge['student_id'] in student_ids and edge['contribution_id'] in contribution_ids
                        assert not eligible_fact(edge,store.approvals(run['id'],run['snapshot']['graph']))
            results['student_overlays_attributed_and_unapproved_additions_not_quizzed']=True
            answers={a['id']:a for a in store.answers()}
            for key,entry in ledger['sessions'].items():
                if not entry.get('state'): continue
                checkpoint=store.session(entry['state']['id'])['checkpoint']
                assert checkpoint['LIMIT']==3,(key,checkpoint.keys())
                assert len(entry.get('submissions',{}))<=3
                restored=get('sessions/'+entry['state']['id'])
                assert restored['student_id']==entry['student_id'] and restored['run_id']==entry['run_id']
                from pipeline.quiz import QuizSession
                quiz=QuizSession.restore(checkpoint['graph_snapshot'],None,checkpoint)
                assert not quiz.review_mode
                assert not ({e['id'] for e in quiz._eligible()} & quiz.independent)
                assert quiz.completed or entry.get('stop_reason')
                if len(entry.get('submissions',{}))<3:
                    assert entry.get('stop_reason') or not quiz._eligible()
                for submission in entry.get('submissions',{}).values():
                    assert not ({r['id'] for r in submission['reference_relationships']} & set(checkpoint['round_start_matches']))
                    answer=answers[submission['answer_id']]
                    assert answer['text']==submission['answer'] and answer['score']==submission['score']
                    assert answer['session_id']==entry['state']['id']
                    assert not answer['overrides']
            for student in ledger['students'].values():
                for topic in topics:
                    live=get('runs/'+topic['id']+'/knowledge?'+urlencode(dict(student_id=student['id'])))
                    assert live['knowledge']==StudentStore(DB).knowledge(student['id'],topic['id'])
            results['progress_persists_separately_and_normal_quizzes_skip_green']=True
            receipt=next(r for r in ledger['commands'].values() if r['body']['action']=='answer' and r['status']=='completed')
            replay=post('quiz',receipt['body']);replay.raise_for_status()
            assert replay.json()==receipt['response']
            assert {a['id']:a for a in store.answers()}==answers
            results['idempotent_receipt_replay_no_duplicate_answer']=True
            results['planned_sessions']=len(ledger['sessions'])
            results['new_sessions']=sum(bool(e.get('state')) for e in ledger['sessions'].values())
            results['new_graded_answers']=sum(len(e.get('submissions',{})) for e in ledger['sessions'].values())
            results['stopped']={k:e['stop_reason'] for k,e in ledger['sessions'].items() if e.get('stop_reason')}
            write(WORK/'verification.json',results);print(json.dumps(results,indent=2))
        save()


if __name__=='__main__': main()
