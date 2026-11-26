import json,sys
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.contributions import Contributions
from pipeline.graph_edits import digest
out=ROOT/'outputs/diagnostics/student_contributions/demo'
store=StudentStore(ROOT/'outputs/professor/students.sqlite3');service=Contributions(store)
marker=out/'duplicate_audit.json'
if not marker.exists():
    candidates=[r for r in service.rows() if r['status']=='duplicate' and r.get('reviews')
        and not any(a.get('duplicate_fact_id') and b.get('duplicate_fact_id')
                    for a,b in zip(r['reviews'][::2],r['reviews'][1::2]))]
    with store.connect() as db:grade_hash=digest([list(r) for r in db.execute('SELECT * FROM answers ORDER BY id')])
    marker.write_text(json.dumps(dict(original=candidates,grade_hash=grade_hash),indent=2),encoding='utf-8')
    for row in candidates:
        row.setdefault('review_history',[]).append(row.get('reviews',[]))
        row['status']='pending';service.save(row);service.job(row['answer_id'],'pending')
saved=json.loads(marker.read_text())
with TestClient(create_app([],professor_store=store,runs_root=ROOT/'outputs/runs'),base_url='http://127.0.0.1') as client:
    for answer_id in dict.fromkeys(r['answer_id'] for r in saved['original']):
        response=client.post('/api/professor/answers/'+answer_id+'/contributions/check')
        response.raise_for_status()
        print([(r['status'],r['claim']['statement']) for r in service.rows(answer_id=answer_id)],flush=True)
with store.connect() as db:assert digest([list(r) for r in db.execute('SELECT * FROM answers ORDER BY id')])==saved['grade_hash']
print('Duplicate audit complete; grades unchanged.',flush=True)
