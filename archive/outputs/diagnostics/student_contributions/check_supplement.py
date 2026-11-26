import json,sys
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.contributions import Contributions
from pipeline.graph_edits import digest
out=ROOT/'outputs/diagnostics/student_contributions/demo'
supplement=json.loads((out/'supplement.json').read_text())
store=StudentStore(ROOT/'outputs/professor/students.sqlite3')
service=Contributions(store)
marker=out/'subject_object_review_started.json'
if not marker.exists():
    prior=[]
    for item in supplement['results']:
        rows=service.rows(answer_id=item['answer_id'])
        assert not any(r['status']=='accepted' for r in rows)
        prior.extend(rows)
    with store.connect() as db:
        grade_hash=digest([list(r) for r in db.execute('SELECT * FROM answers ORDER BY id')])
        for item in supplement['results']:
            db.execute('DELETE FROM contributions WHERE answer_id=?',(item['answer_id'],))
            db.execute("UPDATE contribution_jobs SET status='pending',error=NULL WHERE answer_id=?",(item['answer_id'],))
    marker.write_text(json.dumps(dict(prior=prior,grade_hash=grade_hash),indent=2),encoding='utf-8')
with TestClient(create_app([],professor_store=store,runs_root=ROOT/'outputs/runs'),base_url='http://127.0.0.1') as client:
    if not (out/'compact_review.json').exists():
        item=supplement['results'][0]
        for row in service.rows(answer_id=item['answer_id']):
            if row['status']!='accepted':
                row.setdefault('review_history',[]).append(row.get('reviews',[]))
                row['status']='pending';service.save(row)
        service.job(item['answer_id'],'pending')
        (out/'compact_review.json').write_text('{}',encoding='utf-8')
    if not (out/'structural_connection_review.json').exists():
        for item in supplement['results']:
            for row in service.rows(answer_id=item['answer_id']):
                if row['status'] != 'accepted':
                    row.setdefault('review_history',[]).append(row.get('reviews',[]))
                    row['status']='pending';service.save(row)
            service.job(item['answer_id'],'pending')
        (out/'structural_connection_review.json').write_text('{}',encoding='utf-8')
    for item in supplement['results']:
        response=client.post('/api/professor/answers/'+item['answer_id']+'/contributions/check')
        response.raise_for_status();data=response.json()
        item['contributions']=[r for r in data['contributions'] if r['answer_id']==item['answer_id']]
        print(item['student'],[(r['status'],r['claim']['statement']) for r in item['contributions']],flush=True)
        (out/'supplement.json').write_text(json.dumps(supplement,indent=2),encoding='utf-8')
with store.connect() as db:
    assert digest([list(r) for r in db.execute('SELECT * FROM answers ORDER BY id')])==json.loads(marker.read_text())['grade_hash']
print('All saved grades unchanged.',flush=True)
