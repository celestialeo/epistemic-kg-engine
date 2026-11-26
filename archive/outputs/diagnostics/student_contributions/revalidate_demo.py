"""Recheck demo contributions after extraction fixes; preserve real saved grades."""
import json, sqlite3, sys
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.graph_edits import digest
from pipeline.contributions import Contributions
out=ROOT/'outputs/diagnostics/student_contributions/demo'
ledger=json.loads((out/'ledger.json').read_text(encoding='utf-8'))
assert ledger['completed']
dbpath=ROOT/'outputs/professor/students.sqlite3'
store=StudentStore(dbpath)
marker=out/'final_validation_started.json'
if not marker.exists():
    backup=Path(ledger['backup']).parent/'before_final_validation.sqlite3'
    with sqlite3.connect(dbpath) as src,sqlite3.connect(backup) as dst:src.backup(dst)
    rows=Contributions(store).rows()
    assert not any(r['status']=='accepted' for r in rows), 'Keep accepted graph edits; do not reset their attribution'
    (out/'prior_validation.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    with store.connect() as db:
        db.execute('DELETE FROM contributions')
        db.execute("UPDATE contribution_jobs SET status='pending',error=NULL")
        grade_hash=digest([list(r) for r in db.execute('SELECT * FROM answers ORDER BY id')])
    marker.write_text(json.dumps(dict(backup=str(backup),grade_hash=grade_hash)),encoding='utf-8')
if not (out/'connection_review_updated.json').exists():
    service=Contributions(store)
    for row in service.rows():
        if row['status'] in {'needs_review','validating','validated'}:
            row.setdefault('review_history',[]).append(row.get('reviews',[]))
            row.pop('publication_error',None)
            row['status']='pending';service.save(row)
            service.job(row['answer_id'],'pending')
    (out/'connection_review_updated.json').write_text('{}',encoding='utf-8')
with TestClient(create_app([],professor_store=store,runs_root=ROOT/'outputs/runs'),base_url='http://127.0.0.1') as client:
    for answer in store.answers():
        response=client.post('/api/professor/answers/'+answer['id']+'/contributions/check')
        response.raise_for_status();data=response.json()
        rows=[r for r in data['contributions'] if r['answer_id']==answer['id']]
        job=next(j for j in data['jobs'] if j['answer_id']==answer['id'])
        print(answer['id'],answer['score'],[(r['status'],r['claim']['statement']) for r in rows],job,flush=True)
        for result in ledger['results']:
            if result['answer_id']==answer['id']:result.update(contributions=rows,job=job)
        ledger['validation_version']=3
        (out/'ledger.json').write_text(json.dumps(ledger,indent=2),encoding='utf-8')
with store.connect() as db:
    assert digest([list(r) for r in db.execute('SELECT * FROM answers ORDER BY id')])==json.loads(marker.read_text())['grade_hash']
print('Revalidation completed. All original grades and answers unchanged.',flush=True)
