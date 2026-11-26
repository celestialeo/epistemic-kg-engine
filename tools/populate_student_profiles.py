"""Auditable fictional learners using the normal professor API and local models.

No answer bank, expected-answer access, question replacement, or grading override.
Author answers in a JSON file from `questions` output, keyed by session key, with
question_id and text. Optional assistance is requested separately before authoring.
The public authoring view also includes the targeted graph relationships, as
explicitly requested by the user; it never exposes the expected answer or rubric.
Every mutation has a durable request ID; only technical failures may be retried.
"""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
import sqlite3
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app, make_models
from pipeline.settings import SETTINGS
from pipeline.student_store import StudentStore

WORK = ROOT / 'outputs/student_profiles'
DB = ROOT / 'outputs/professor/students.sqlite3'
LEDGER = WORK / 'metadata.json'
PROFILES = [
    dict(key='maya', name='Maya Chen', profile='Strong generalist',
         strengths='All three topics; accurate natural explanations with occasional omissions.'),
    dict(key='noah', name='Noah Patel', profile='Struggling beginner',
         strengths='Limited starting knowledge; incomplete, incorrect and uncertain answers; uses help.'),
    dict(key='elena', name='Elena Morales', profile='Topic specialist',
         strengths='Neurons and glia; struggles with AI and LLM tuning.'),
]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def now():
    return datetime.now(timezone.utc).isoformat()


def backup(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as original, closing(sqlite3.connect(target)) as copy:
        original.backup(copy)
        assert copy.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def prepare():
    if LEDGER.exists():
        raise SystemExit('Existing provenance ledger found; resume it instead of resetting students again.')
    archive = ROOT / 'archive/databases' / ('student_profiles_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    backup(DB, archive/'students.sqlite3')
    store = StudentStore(DB)
    # Refuse to erase attribution while published student overlays still exist.
    # Reconcile those through reversible contribution/manual-edit APIs first.
    from pipeline.contributions import Contributions
    if Contributions(store).rows():
        raise SystemExit('Existing contributions need an explicit overlay reconciliation before reset; backup saved.')
    baseline = {}
    for run in store.runs():
        graph = run['snapshot']['graph']
        if any(x.get('origin') == 'student' for x in graph['edges'] + graph['nodes']):
            raise SystemExit('An existing student overlay needs reconciliation before reset; backup saved.')
        directory = Path(run['directory'])
        for path in [directory/'artifacts/graph.json', directory/'manual_graph.sqlite3']:
            if path.exists():
                if path.suffix == '.sqlite3':
                    backup(path, archive/directory.parent.name/directory.name/path.name)
                baseline[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    with store.connect() as db:
        for table in ('contribution_jobs', 'contributions', 'overrides', 'pending_answers',
                      'answers', 'sessions', 'requests', 'assessment_errors', 'students'):
            db.execute('DELETE FROM ' + table)
    ledger = dict(origin='fictional, authored student simulations; not real learners',
                  created_at=now(), backup=str(archive.relative_to(ROOT)),
                  policy='Real API/model workflow; answers authored only from displayed questions and requested help. No outcome targeting or grade replacement.',
                  round_questions=2, baseline_hashes=baseline, profiles=PROFILES,
                  students={}, sessions={}, commands={}, contributions={})
    write(LEDGER, ledger)
    return ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'start', 'questions', 'submit', 'next', 'help', 'contributions', 'metrics'])
    parser.add_argument('--round', type=int, default=1, choices=[1, 2])
    parser.add_argument('--answers', type=Path)
    parser.add_argument('--session', help='Optional exact ledger session key')
    parser.add_argument('--help-kind', choices=['hint', 'reveal'], default='hint')
    args = parser.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    ledger = prepare() if args.action == 'prepare' and not LEDGER.exists() else json.loads(LEDGER.read_text(encoding='utf-8'))
    # Bound this population exercise only. Production selection and grading stay unchanged.
    SETTINGS['ui']['quiz_round_questions'] = ledger['round_questions']
    store = StudentStore(DB)
    def save(): write(LEDGER, ledger)
    def model_factory(snapshot, trace):
        models = make_models(snapshot, trace)
        original = models.ask
        def ask(role, *arguments, **keywords):
            started = time.monotonic()
            print('MODEL', role, flush=True)
            result = original(role, *arguments, **keywords)
            print('DONE', role, round(time.monotonic()-started, 1), 's', flush=True)
            return result
        models.ask = ask
        return models
    with TestClient(create_app([], professor_store=store, runs_root=ROOT/'outputs/runs', model_factory=model_factory), base_url='http://127.0.0.1') as client:
        def get(path):
            response = client.get('/api/professor/'+path)
            response.raise_for_status()
            return response.json()
        def post(path, body):
            return client.post('/api/professor/'+path, json=body)
        catalog = get('catalog')
        topics = sorted(catalog['topics'], key=lambda t:t['title'])
        ledger['topics'] = [{k:t[k] for k in ('id','title','topic_key')} for t in topics]
        if args.action == 'prepare':
            for profile in PROFILES:
                existing = [s for s in store.students() if s['name'] == profile['name']]
                if len(existing) > 1: raise ValueError('Duplicate student name; inspect before continuing')
                if existing:
                    ledger['students'][profile['key']] = existing[0]
                else:
                    response = post('students', {'name':profile['name']}); response.raise_for_status()
                    ledger['students'][profile['key']] = response.json()
                save()
            assert len(get('catalog')['students']) == 3
            print('Backup verified; exactly three fictional students created. Source graphs and approvals preserved.')
            return
        def metrics(student_id, run_id):
            topic = next(t for t in topics if t['id'] == run_id)
            data = get('scope?'+urlencode(dict(student_id=student_id, run_id=run_id, topic=topic['topic_key'])))
            selected = data['selected']
            return dict(at=now(), metrics=selected['metrics'], categories=selected['categories'],
                        graph_metrics=selected.get('graph_metrics'), unique_relationships=data['unique_relationships'])
        def command(key, action, entry, **extra):
            state = entry.get('state')
            number = state['state']['question']['number'] if state else 0
            command_key = key+':'+action+':'+str(number)
            record = ledger['commands'].get(command_key)
            if record is None:
                body = dict(action=action, request_id=str(uuid.uuid4()), **extra)
                if action != 'start':
                    body.update(session_id=state['id'], question_id=state['state']['question']['id'])
                record = dict(body=body, attempts=[], status='pending')
                ledger['commands'][command_key] = record; save()
            else:
                for field, value in extra.items():
                    if record['body'].get(field) != value:
                        raise ValueError('Cannot rewrite an existing request: '+command_key)
            if record['status'] == 'completed':
                return record['response']
            # Two attempts normally; one final technical retry after the recorded
            # criterion-index validation diagnostic fix. Successful grades never rerun.
            limit = 3 if record.get('diagnostic_fix_retry') else 2
            while len(record['attempts']) < limit:
                print('REQUEST', key, action, number, flush=True)
                response = post('quiz', record['body'])
                record['attempts'].append(dict(at=now(), status=response.status_code,
                                              error=response.json() if response.status_code != 200 else None))
                if response.status_code == 200:
                    record.update(status='completed', response=response.json())
                    entry['state'] = response.json(); save()
                    return response.json()
                save()
                print('TECHNICAL FAILURE', response.status_code, response.text[:1500], flush=True)
                if response.status_code not in (503, 409):
                    break
                if response.status_code == 409 and 'Another graph request' not in response.text:
                    break
            record['status'] = 'unresolved'; save()
            return None
        if args.action == 'start':
            if args.round == 2:
                ledger.setdefault('authoring_update', dict(at=now(), round=2,
                    policy='User requested targeted graph relationships as the reference for natural profile-consistent answers. No internet research, hidden expected answers, or grading criteria. Earlier submissions retained.'))
                save()
            for profile in PROFILES:
                student = ledger['students'][profile['key']]
                for topic in topics:
                    key = f"{profile['key']}:{topic['title']}:r{args.round}"
                    if args.session and key != args.session: continue
                    entry = ledger['sessions'].setdefault(key, dict(student_id=student['id'], run_id=topic['id'],
                        profile=profile['key'], topic=topic['title'], round=args.round))
                    if entry.get('state'): continue
                    entry.setdefault('before', metrics(student['id'], topic['id'])); save()
                    command(key, 'start', entry, student_id=student['id'], run_id=topic['id'])
        selected = {k:v for k,v in ledger['sessions'].items() if v['round']==args.round and (not args.session or k==args.session)}
        if args.action == 'questions':
            def reference(entry):
                checkpoint=store.session(entry['state']['id'])['checkpoint']
                graph=checkpoint['graph_snapshot']
                nodes={n['id']:n['label'] for n in graph['nodes']}
                requested={f['id'] for f in checkpoint['question']['examiner_material']['facts']}
                return [dict(subject=nodes[e['source']], relationship=e['label'], object=nodes[e['target']],
                             **{k:e.get(k) for k in ('definition','conditions','modality','purpose','timing','argument_qualifiers')},
                             participants=[dict(role=p['role'],concept=nodes[p['node']]) for p in e.get('participants',[])])
                        for e in graph['edges'] if e['id'] in requested]
            public = {k:dict(question_id=v['state']['state']['question']['id'],
                            question=v['state']['state']['question']['text'],
                            number=v['state']['state']['question']['number'],
                            assistance=v['state']['state']['question']['help_text'],
                            reference_relationships=reference(v),
                            completed=v['state']['state']['completed'])
                      for k,v in selected.items() if v.get('state')}
            print(json.dumps(public, ensure_ascii=False, indent=2)); return
        if args.action == 'help':
            if not args.session: raise ValueError('--session is required for help')
            for key,entry in selected.items():
                result=command(key,args.help_kind,entry)
                if result: print(json.dumps(result['state']['question'],ensure_ascii=False))
        if args.action == 'submit':
            answers=json.loads(args.answers.read_text(encoding='utf-8'))
            for key,authored in answers.items():
                entry=selected[key];question=entry['state']['state']['question']
                if authored['question_id'] != question['id']: raise ValueError('Question mismatch: '+key)
                previous=entry.get('submissions',{}).get(str(question['number']))
                if previous:
                    if previous['answer'] != authored['text']: raise ValueError('Cannot rewrite a submitted answer')
                    continue
                result=command(key,'answer',entry,text=authored['text'])
                if result:
                    print('OUTCOME',key,result['answer_score'],result['state']['question']['feedback'],flush=True)
                    entry.setdefault('submissions',{})[str(question['number'])]=dict(
                        question=dict(question), answer=authored['text'], answer_id=result['contribution_answer_id'],
                        score=result['answer_score'], feedback=result['state']['question']['feedback'],
                        result=result['state']['last_result'], at=now())
                    save()
        if args.action == 'next':
            for key,entry in selected.items():
                state=entry.get('state')
                if state and not state['state']['completed'] and state['state']['question']['attempts']:
                    command(key,'next',entry)
        if args.action == 'contributions':
            for key,entry in selected.items():
                for submission in entry.get('submissions',{}).values():
                    answer_id=submission['answer_id']
                    previous=ledger['contributions'].get(answer_id,{})
                    if previous.get('completed') or previous.get('attempts',0)>=2: continue
                    print('CONTRIBUTIONS',key,answer_id,flush=True)
                    response=post('answers/'+answer_id+'/contributions/check',{})
                    response.raise_for_status(); data=response.json()
                    job=next(j for j in data['jobs'] if j['answer_id']==answer_id)
                    ledger['contributions'][answer_id]=dict(completed=job['status']=='completed',job=job, attempts=previous.get('attempts',0)+1,
                        records=[r for r in data['contributions'] if r['answer_id']==answer_id])
                    save()
        if args.action in ('metrics','next','submit'):
            for key,entry in selected.items():
                entry['after']=metrics(entry['student_id'],entry['run_id'])
            save()
        save()


if __name__ == '__main__':
    main()
