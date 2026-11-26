"""Read-only verification and browser evidence for the actual demo database."""
import asyncio,json,sys
from collections import Counter
from pathlib import Path
ROOT=Path.cwd();sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright,expect
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.contributions import Contributions
from pipeline.submission import start_server,stop_server
out=ROOT/'outputs/diagnostics/student_contributions/demo'
ledger=json.loads((out/'ledger.json').read_text())
store=StudentStore(ROOT/'outputs/professor/students.sqlite3')
students=store.students();assert len(students)==2
rows=Contributions(store).rows()
history=store.history();answers=store.answers()
assert len(answers)==12 and len(history)==4 and all(s['completed'] for s in history)
assert {a['score'] for a in answers}=={0,50,100}
accepted=[r for r in rows if r['status']=='accepted']
assert all(any(r['student_id']==s['id'] for r in accepted) for s in students),'Each student must have a validated graph addition'
with store.connect() as db:assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
app=lambda:create_app([],professor_store=StudentStore(store.path),runs_root=ROOT/'outputs/runs')
with TestClient(app(),base_url='http://127.0.0.1') as client:
    catalog=client.get('/api/professor/catalog').json();assert len(catalog['versions'])==2
    graph=client.get('/api/professor/runs/'+ledger['run_id']+'/manual-graph').json()['graph']
    additions=[e for e in graph['edges'] if e['origin']=='student']
    assert len(additions)==len(accepted)
    assert {e['contribution_id'] for e in additions}=={r['id'] for r in accepted}
    material=client.get('/api/professor/runs/'+ledger['run_id']+'/quiz-material').json()
    assert all(not r['eligible'] for r in material['facts'] if r['fact']['origin']=='student')
    for session in history:
        detail=client.get('/api/professor/sessions/'+session['id']).json()
        assert not detail['graph_review']['changed']
        assert all(not a['graph_changes'] for a in detail['answers'])
summary=dict(students=[dict(name=s['name'],id=s['id'],sessions=sum(h['student_id']==s['id'] for h in history),
    scores=[a['score'] for h in history if h['student_id']==s['id'] for a in h['answers']],
    accepted=sum(r['student_id']==s['id'] for r in accepted)) for s in students],
    answers=len(answers),contributions=dict(Counter(r['status'] for r in rows)),
    graph=dict(nodes=len(graph['nodes']),edges=len(graph['edges']),student_edges=len(additions)),
    accepted=[dict(student=r['student_name'],claim=r['claim']['statement'],edge_id=r['edge_id']) for r in accepted],
    backup=ledger['backup'],run_id=ledger['run_id'],live_model='qwen3.5:9b',grading_mocked=False,validation_mocked=False)
old=asyncio.get_event_loop_policy()
try:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    url=start_server(app())['url']
finally:asyncio.set_event_loop_policy(old)
errors=[]
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport=dict(width=1600,height=1100))
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url+'/professor?view=insights&run='+ledger['run_id'])
        expect(page.locator('.contribution-card')).to_have_count(len(rows))
        if page.locator('#insight-aggregate').is_visible():page.locator('#insight-aggregate').uncheck()
        frame=page.frame_locator('#graph')
        expect(frame.locator('line[stroke="#f472b6"]')).to_have_count(len(accepted))
        page.locator('#graph-workspace').screenshot(path=str(out/'actual_graph.png'))
        page.locator('.contribution-card').filter(has_text=accepted[0]['claim']['statement']).first.screenshot(path=str(out/'actual_contribution.png'))
        page.locator('#tab-class').click()
        expect(page.locator('#student-cards .student-card')).to_have_count(2)
        page.locator('#class-view').screenshot(path=str(out/'actual_students.png'))
        page.reload();expect(page.locator('.contribution-card')).to_have_count(len(rows))
        page.goto('about:blank');browser.close()
        assert not errors,errors
finally:stop_server()
summary['browser_errors']=errors
(out/'verification.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2),flush=True)
