"""Build a labelled demo class with real local-model grading, then explicitly publish.

Questions are generated and reviewed once as a reusable bank. Student answers are
authored synthetic scenarios; scenario labels are NEVER supplied to the grader.
All sessions/answers go through the normal professor API, including assistance.
The staged database permits resuming before a transactional roster replacement.
"""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app,load_snapshot
from pipeline.models import Models
from pipeline.professor import run_identity,topic_identity
from pipeline.quiz_examiner import QuizExaminer, review_expected
from pipeline.student_store import StudentStore
from pipeline.trace import Trace


NAMES=['Maya Chen','Noah Patel','Sofia Alvarez','Ethan Brooks','Amara Okafor',
       'Leo Martin','Ava Thompson','Lucas Nguyen','Isabella Rossi','Oliver Wilson']
# Graph-specific practice responses: the saved AI-test graph is the exercise reference.
ANSWERS={
 'edge_00001':('The little transformer uses attention over its own input to work with text.',
               'It relies on self-attention, but I cannot explain what that is used for.',
               'The small transformer never uses self-attention to process text.'),
 'edge_00002':('During learning, the small transformer uses backpropagation so its predictions improve.',
               'The transformer uses backpropagation; I am unsure of its purpose.',
               'The small transformer does not use backpropagation while training.'),
 'edge_00003':('Regularization helps the little transformer handle examples beyond those it learned from.',
               'It helps the model learn, but I do not know what happens with new examples.',
               'Regularization prevents the transformer from generalizing beyond its training examples.'),
 'edge_00004':('Once trained, a quantized model needs less memory to store it.',
               'Quantization changes memory requirements, but I do not know in which direction.',
               'After training, quantization increases how much memory the model needs.'),
 'edge_00005':('Retrieval-augmented generation lets the system consult outside documents to answer questions.',
               'It retrieves information, but I cannot say how that is used to answer.',
               'Retrieval-augmented generation prevents outside documents from being used for answers.'),
 'edge_00006':('Backpropagation uses the chain rule to calculate loss gradients with respect to the model parameters.',
               'Backpropagation uses the chain rule, but I do not know what it computes.',
               'Backpropagation never uses the chain rule to compute gradients of the loss.'),
 'edge_00007':('For machine-learning models, regularization puts limits on model complexity.',
               'Regularization affects the model, but I am not sure what aspect is constrained.',
               'Regularization leaves model complexity completely unconstrained.'),
 'edge_00008':('Under regularization, model complexity reduces how well a model can memorize noise.',
               'It changes noise memorization, but I cannot say whether it increases or decreases it.',
               'Under regularization, model complexity increases how well a model can memorize noise.'),
 'edge_00009':('Reducing the ability to memorize noise helps the model generalize better.',
               'Memorizing noise is connected to generalization, but I am unsure how.',
               'Reducing noise memorization prevents generalization performance.'),
 'edge_00010':('Quantization represents numbers with lower numerical precision.',
               'It changes how numbers are represented, but I cannot explain the precision change.',
               'Quantization raises numerical precision rather than reducing it.'),
 'edge_00011':('Consulting external documents requires accessing a changing knowledge base outside the model’s fixed weights.',
               'External documents give access to knowledge, but I cannot describe the knowledge base.',
               'Using external documents cannot access a changing knowledge base.'),
 'edge_00012':('In retrieval-augmented generation, outside documents shift the information source away from internal parameters to external material.',
               'External documents change where information comes from, but I cannot describe the shift.',
               'Using external documents shifts all information back into internal parameters and away from external sources.')}


def write(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')


def scenario(student,round_no,fact,number):
    edge=int(fact.rsplit('_',1)[1]);p=(student*7+round_no*3+edge+number)%10
    if student==0:return 'correct'
    if student==1:return 'correct' if p<round_no+2 else 'partial' if p<8 else 'wrong'
    if student==2:return 'correct' if edge in [1,2,3,6,7] else 'partial' if p<5 else 'wrong'
    if student==3:return 'correct' if edge in [4,10,5,11,12] else 'wrong'
    if student==4:return 'assisted' if round_no<3 or p<7 else 'correct'
    if student==5:return 'wrong' if p<8 else 'correct'
    if student==6:return 'partial' if p<7 else 'assisted'
    if student==7:return 'correct' if round_no>=3 else 'wrong' if p<6 else 'partial'
    if student==8:return ['correct','partial','wrong','assisted','unrelated'][p%5]
    return 'unrelated' if p<6 else 'wrong' if p<9 else 'correct'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=Path('outputs/professor/students.sqlite3'))
    parser.add_argument('--publish',action='store_true',help='Replace live student records only after all 40 sessions are complete')
    args=parser.parse_args();args.work.mkdir(parents=True,exist_ok=True)
    snapshot=load_snapshot(args.run);run_id=run_identity(snapshot);key,title=topic_identity(snapshot)
    staged=args.work/'students.sqlite3';fresh=not staged.exists()
    if fresh and args.database.exists():
        with sqlite3.connect(args.database) as source,sqlite3.connect(staged) as target:source.backup(target)
    store=StudentStore(staged)
    tables=['assessment_errors','pending_answers','overrides','answers','requests','sessions','students']
    if fresh:
        with store.connect() as db:
            for table in tables:db.execute('DELETE FROM '+table)
        store.register_run(run_id,key,title,snapshot)
        for edge in snapshot.graph['edges']:
            if edge.get('origin')=='background':store.approve_fact(run_id,edge,True,
                'User-authorized synthetic AI-test exercise: use the saved generated graph as the reference regardless of external correctness. This is not independent factual verification.')
        for name in NAMES:store.add_student(name)
    if set(ANSWERS)!=set(e['id'] for e in snapshot.graph['edges']):raise ValueError('This scenario bank requires the specified 12-fact AI-test graph')
    ledger_path=args.work/'progress.json';ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else dict(run_id=run_id,sessions={},answers=[])
    bank_path=args.work/'questions.json';bank=json.loads(bank_path.read_text(encoding='utf-8')) if bank_path.exists() else {}
    trace=Trace(args.work/('trace_'+uuid.uuid4().hex[:10]),'demo_class')
    models=Models(trace,'qwen3.5:9b','nomic-embed-text','http://127.0.0.1:11434',context_tokens=8192,max_output_tokens=1536,timeout=180)
    models.preflight()
    identity={m.get('model',m.get('name')):m['digest'] for m in models.details['installed_models']['models']}
    identity_path=args.work/'model_identity.json'
    if identity_path.exists() and json.loads(identity_path.read_text())!=identity:
        raise RuntimeError('Installed model identities changed; use a new work directory for a new demo')
    write(identity_path,identity)
    cache_path=args.work/'model_cache.json'
    if cache_path.exists():models.cache=json.loads(cache_path.read_text(encoding='utf-8'))
    examiner=QuizExaminer(models,snapshot.graph);examiner.approvals=store.approvals(run_id,snapshot.graph)
    for fact_id,questions in bank.items():
        retained=[]
        for question in questions:
            if not question.get('answer_grounding'):
                review=review_expected(models,question['examiner_material'],question['expected_answer'],'demo_bank_audit:'+fact_id)
                if not (review.supported and review.direction_preserved and review.conditions_preserved):
                    print('REPLACE EXPECTED ANSWER',fact_id,review.reason,flush=True)
                    continue
                question['answer_grounding']=review.model_dump()
            retained.append(question)
        bank[fact_id]=retained
        write(bank_path,bank);write(cache_path,models.cache)
    for edge in snapshot.graph['edges']:
        bank.setdefault(edge['id'],[])
        while len(bank[edge['id']])<2:
            variant=len(bank[edge['id']]);print('QUESTION',edge['id'],variant+1,flush=True)
            q=examiner.question(edge['source'],[edge['id']],variant+1,[q['text'] for q in bank[edge['id']]],'demo_bank:'+edge['id']+':'+str(variant))
            bank[edge['id']].append(q);write(bank_path,bank);write(cache_path,models.cache)
            print(q['text'],flush=True)
    current_round=[0]
    def bank_question(self,focus,identifiers,number,previous,request_id,fallback=None):
        # These are genuine generated/reviewed questions, reused across demo learners.
        candidates=bank[identifiers[0]];return copy.deepcopy(candidates[current_round[0]%len(candidates)])
    app=create_app([],professor_store=store,runs_root=args.run.parent,model_factory=lambda s,t:models)
    students={s['name']:s['id'] for s in store.students()}
    with patch.object(QuizExaminer,'question',bank_question),TestClient(app,base_url='http://127.0.0.1') as client:
        client.get('/api/professor/catalog').raise_for_status()
        def command(action,state=None,**kwargs):
            body=dict(action=action,request_id=str(uuid.uuid4()),**kwargs)
            if state:body.update(session_id=state['id'],question_id=state['state']['question']['id'])
            if state and action=='answer':
                pending=store.pending_answers(state['id'])
                if pending:
                    if pending[0]['text']!=kwargs['text']:raise RuntimeError('Pending answer differs from the scenario; review it before resuming')
                    body=pending[0]['request']
            for attempt in range(3):
                response=client.post('/api/professor/quiz',json=body)
                if response.status_code==200:return response.json()
                print('RETRY',action,response.status_code,response.text[:500],flush=True)
                if response.status_code not in [503,409]:break
            raise RuntimeError(response.text)
        for i,name in enumerate(NAMES):
            for round_no in range(1,5):
                current_round[0]=round_no-1;session_key=str(i)+':'+str(round_no)
                if session_key in ledger['sessions']:
                    state=client.get('/api/professor/sessions/'+ledger['sessions'][session_key]).json()
                else:
                    prior=store.knowledge(students[name],run_id)
                    review=all(e['id'] in prior and prior[e['id']]['mark']=='match' and not prior[e['id']]['helped'] for e in snapshot.graph['edges'])
                    state=command('start',student_id=students[name],run_id=run_id,review_mode=review)
                    ledger['sessions'][session_key]=state['id'];write(ledger_path,ledger)
                while not state['state']['completed']:
                    q=state['state']['question'];saved=store.session(state['id'])['checkpoint']['question']
                    if q['attempts']:
                        state=command('next',state);continue
                    fact=saved['examiner_material']['facts'][0]['id'];kind=scenario(i,round_no,fact,q['number'])
                    text=ANSWERS[fact][0 if kind in ['correct','assisted'] else 1 if kind=='partial' else 2]
                    if kind=='unrelated':text=['I prefer sunny days and pizza.','Can you help me? I do not know this answer.'][q['number']%2]
                    if kind=='assisted' and not saved['revealed']:state=command('reveal',state)
                    print('ANSWER',name,'round',round_no,'question',q['number'],fact,kind,flush=True)
                    started=time.time();state=command('answer',state,text=text)
                    answer=store.answers(state['id'])[-1]
                    ledger['answers'].append(dict(student=name,round=round_no,question=q['number'],fact=fact,scenario=kind,
                        answer_id=answer['id'],score=answer['score'],marks=answer['effective_marks'],seconds=round(time.time()-started,2)))
                    write(ledger_path,ledger);write(cache_path,models.cache)
                    print('GRADED',answer['score'],answer['effective_marks'],'seconds',round(time.time()-started,2),flush=True)
                    if not state['state']['completed']:state=command('next',state)
                print('SESSION COMPLETE',name,round_no,flush=True)
    history=store.history();answers=store.answers()
    if len(store.students())!=10 or len(history)!=40 or not all(s['completed'] for s in history):raise RuntimeError('Incomplete class; live records not replaced')
    with store.connect() as db:
        if db.execute('SELECT COUNT(*) FROM pending_answers').fetchone()[0]:raise RuntimeError('Unresolved submissions remain')
    report=dict(students=10,sessions=40,answers=len(answers),model_calls_this_execution=models.calls,cache_hits_this_execution=models.cache_hits,
                run_id=run_id,synthetic=True,question_bank_size=sum(map(len,bank.values())),
                scores={name:[a['score'] for a in ledger['answers'] if a['student']==name] for name in NAMES})
    write(args.work/'report.json',report)
    if args.publish:
        # Replace only student/assessment records, preserving saved graph snapshots.
        with sqlite3.connect(args.database) as db:
            db.execute('PRAGMA foreign_keys=ON');db.execute('ATTACH DATABASE ? AS staged',(str(staged.resolve()),))
            db.execute('BEGIN IMMEDIATE')
            for table in tables:db.execute('DELETE FROM '+table)
            db.execute('INSERT OR IGNORE INTO runs SELECT * FROM staged.runs')
            for table in reversed(tables):db.execute('INSERT INTO '+table+' SELECT * FROM staged.'+table)
            db.execute('DELETE FROM fact_approvals WHERE run_id=?',(run_id,))
            db.execute('INSERT INTO fact_approvals(run_id,fact_id,fingerprint,approved,reason,at) SELECT run_id,fact_id,fingerprint,approved,reason,at FROM staged.fact_approvals WHERE run_id=?',(run_id,))
            if db.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('Invalid demo record references')
        print('PUBLISHED',args.database,flush=True)
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()
