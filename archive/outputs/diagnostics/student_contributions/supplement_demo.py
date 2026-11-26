"""One additional real quiz per demo student, with explicit new mechanisms."""
import json, sys, uuid
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app
from pipeline.settings import SETTINGS
from pipeline.student_store import StudentStore
from pipeline.contributions import Contributions
out=ROOT/'outputs/diagnostics/student_contributions/demo'
path=out/'supplement.json'
ledger=json.loads((out/'ledger.json').read_text(encoding='utf-8'))
saved=json.loads(path.read_text()) if path.exists() else dict(requests={},results=[])
def save():path.write_text(json.dumps(saved,indent=2),encoding='utf-8')
store=StudentStore(ROOT/'outputs/professor/students.sqlite3')
SETTINGS['ui']['quiz_round_questions']=1
with TestClient(create_app([],professor_store=store,runs_root=ROOT/'outputs/runs'),base_url='http://127.0.0.1') as client:
    def post(route,body):
        response=client.post('/api/professor/'+route,json=body)
        if response.status_code!=200:raise RuntimeError(response.text)
        return response.json()
    topic=next(t for t in client.get('/api/professor/catalog').json()['topics'] if t['id']==ledger['run_id'])
    focus=next(n['id'] for n in topic['concepts'] if n['label']=='dropout')
    for index,student in enumerate(ledger['students']):
        def command(action,**kwargs):
            key=f'{index}:{action}'
            if key not in saved['requests']:
                saved['requests'][key]=dict(action=action,request_id=str(uuid.uuid4()),**kwargs);save()
            return post('quiz',saved['requests'][key])
        state=command('start',student_id=student['id'],run_id=topic['id'],focus_id=focus)
        question=store.session(state['id'])['checkpoint']['question']
        if index==0:
            answer=('Dropout disables some activations. '
                'Gradient clipping rescales gradients whose norm exceeds a chosen threshold. '
                'Early stopping can use a patience parameter to tolerate several validation checks without improvement before ending training.')
        else:
            answer=(question['expected_answer']+' An Adam optimizer maintains exponential moving averages of gradients and of squared gradients. '
                'An embedding layer can be initialized with pretrained word embeddings.')
        state=command('answer',session_id=state['id'],question_id=state['state']['question']['id'],text=answer)
        print(student['name'],'actual grade',state['answer_score'],flush=True)
        data=post('answers/'+state['contribution_answer_id']+'/contributions/check',{})
        rows=[r for r in data['contributions'] if r['answer_id']==state['contribution_answer_id']]
        result=dict(student=student['name'],session_id=state['id'],answer_id=state['contribution_answer_id'],
            actual_score=state['answer_score'],contributions=rows)
        saved['results']=[r for r in saved['results'] if r['answer_id']!=result['answer_id']]+[result];save()
        print([(r['status'],r['claim']['statement']) for r in rows],flush=True)
    # Retry unresolved checks, using current generic validation and preserving grades.
    for row in Contributions(store).rows():
        if row['status']=='validating':
            data=post('answers/'+row['answer_id']+'/contributions/check',{})
            print('Retried interrupted/unresolved contribution',row['id'],flush=True)
