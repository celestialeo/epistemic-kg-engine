"""Two five-question AI Chapter demos using the real HTTP/model workflow.

First invocation backs up and clears student records. Subsequent invocations resume
the ledger. Demo answer text is authored here; grades and validation are never mocked.
"""
import json
from pathlib import Path
import sqlite3
import sys
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app
from pipeline.settings import SETTINGS
from pipeline.student_store import StudentStore

OUT = ROOT/'outputs/diagnostics/student_contributions/demo'
DB = ROOT/'outputs/professor/students.sqlite3'
LEDGER = OUT/'ledger.json'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if LEDGER.exists():
        ledger = json.loads(LEDGER.read_text(encoding='utf-8'))
    else:
        archive = ROOT/'outputs/archive'/('student_database_'+datetime.now(ZoneInfo('America/Toronto')).strftime('%Y%m%d_%H%M%S'))
        archive.mkdir(parents=True)
        store = StudentStore(DB)
        with sqlite3.connect(DB) as original, sqlite3.connect(archive/'students.sqlite3') as backup:
            original.backup(backup)
            assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        # Backup verified before resetting all student, assessment, and run-catalog data.
        with store.connect() as db:
            for table in ('contributions','contribution_jobs','overrides','pending_answers','answers',
                          'sessions','students','requests','assessment_errors','fact_approvals','runs'):
                db.execute('DELETE FROM '+table)
        ledger = dict(backup=str(archive/'students.sqlite3'), students=[], results=[], requests={})
        LEDGER.write_text(json.dumps(ledger, indent=2), encoding='utf-8')
        print('Verified backup and reset:', ledger['backup'], flush=True)

    def save(): LEDGER.write_text(json.dumps(ledger, indent=2), encoding='utf-8')
    # Use the existing configurable round length; scoring and validation are untouched.
    SETTINGS['ui']['quiz_round_questions'] = 5
    store = StudentStore(DB)
    with TestClient(create_app([], professor_store=store, runs_root=ROOT/'outputs/runs'), base_url='http://127.0.0.1') as client:
        def get(path):
            response=client.get('/api/professor/'+path); response.raise_for_status(); return response.json()
        def post(path, body):
            response=client.post('/api/professor/'+path, json=body)
            if response.status_code != 200: raise RuntimeError(response.text)
            return response.json()
        topic=next(t for t in get('catalog')['topics'] if 'AI Chapter' in t['title'])
        ledger['run_id']=topic['id']; save()
        names={n['label']:n['id'] for n in topic['concepts']}
        focuses=['backpropagation','learning rate','dropout','separate validation dataset','tokenizer']
        scenarios=['correct_with_new_concept','partial','incorrect','contradictory','correct_with_new_concept']
        for index, name in enumerate(['Maya Chen (Demo)','Noah Patel (Demo)']):
            if len(ledger['students'])<=index:
                ledger['students'].append(post('students',dict(name=name))); save()
            student=ledger['students'][index]
            def command(action, number, state=None, **kwargs):
                key=f'{index}:{number}:{action}'
                if key not in ledger['requests']:
                    body=dict(action=action,request_id=str(uuid.uuid4()),**kwargs)
                    if state: body.update(session_id=state['id'],question_id=state['state']['question']['id'])
                    ledger['requests'][key]=body; save()
                return post('quiz',ledger['requests'][key])
            state=command('start',0,student_id=student['id'],run_id=topic['id'],focus_id=names[focuses[0]])
            for number in range(5):
                if number:
                    state=command('next',number,state,focus_id=names[focuses[number]])
                question=next((a['question'] for a in store.answers(state['id'])
                    if a['question']['id']==state['state']['question']['id']),
                    store.session(state['id'])['checkpoint']['question'])
                if number==0:
                    text=question['expected_answer']+' Backpropagation applies the chain rule to compute derivatives through composed functions.'
                elif number==1:
                    text='It affects training.' if index==0 else 'The learning rate changes updates.'
                elif number==2:
                    text=('Dropout increases every activation at inference and never disables activations during training.' if index==0 else
                          'Dropout permanently removes every neuron from a network before training starts.')
                elif number==3:
                    text=('A separate validation dataset supports model selection. A separate validation dataset cannot support model selection.' if index==0 else
                          'A separate validation dataset supports model selection, but it does not support model selection. '
                          'In our unpublished classroom experiment, the separate validation dataset improved test accuracy by exactly 17 percentage points.')
                else:
                    text=question['expected_answer']+(' A tokenizer using byte-pair encoding can represent text using a learned subword vocabulary.' if index==0 else
                        'A tokenizer maps tokens to integer token IDs for model input.')
                print(name, 'question',number+1, scenarios[number],question['text'],flush=True)
                state=command('answer',number,state,text=text)
                answer_id=state['contribution_answer_id']
                print('Actual grade:',state['answer_score'],'checking extra claims',flush=True)
                contribution=post('answers/'+answer_id+'/contributions/check',{})
                result=dict(student=name,session_id=state['id'],answer_id=answer_id,number=number+1,
                    intended_scenario=scenarios[number],question=question['text'],answer=text,actual_score=state['answer_score'],
                    contributions=[r for r in contribution['contributions'] if r['answer_id']==answer_id],
                    job=next(j for j in contribution['jobs'] if j['answer_id']==answer_id))
                ledger['results']=[r for r in ledger['results'] if r['answer_id']!=answer_id]+[result];save()
                print('Contribution result:',[(r['status'],r['claim']['statement']) for r in result['contributions']],result['job']['status'],flush=True)
            if not state['state']['completed']: state=command('next',5,state)
            assert state['state']['completed']
        ledger['completed']=True;save()
        print('Demo complete:',LEDGER,flush=True)


if __name__=='__main__': main()
