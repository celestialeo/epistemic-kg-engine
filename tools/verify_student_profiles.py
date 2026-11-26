"""Verify saved fictional profiles and capture their normal professor views.

Read-only except for replaying an already completed, idempotent answer receipt.
No generation, grading, corrections or contribution decisions are requested.
"""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.contributions import Contributions
from pipeline.quiz import QuizSession
from pipeline.assessment import eligible_fact


def no_models(*args):
    raise AssertionError('Saved-profile verification must not call a model')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',action='store_true')
    args=parser.parse_args()
    work=ROOT/'outputs/student_profiles'
    ledger=json.loads((work/'metadata.json').read_text(encoding='utf-8'))
    store=StudentStore(ROOT/'outputs/professor/students.sqlite3')
    expected={s['id']:s['name'] for s in ledger['students'].values()}
    assert {s['id']:s['name'] for s in store.students()}==expected
    assert len(expected)==3
    assert all(not any(label in name.lower() for label in ('demo','test','simulated')) for name in expected.values())
    for relative,digest in ledger['baseline_hashes'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest, relative
    runs=store.runs(); assert len(runs)==3
    before_answers=store.answers()
    with store.connect() as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
        assert db.execute('SELECT COUNT(*) FROM overrides').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM fact_approvals').fetchone()[0]==0
        assert not db.execute('SELECT session_id,question FROM answers GROUP BY session_id,question HAVING count(*)>1').fetchall()
    rows=Contributions(store).rows(); ids={r['id'] for r in rows}
    for run in runs:
        for edge in run['snapshot']['graph']['edges']:
            if edge.get('origin')=='student':
                assert edge['student_id'] in expected and edge['contribution_id'] in ids
                assert not eligible_fact(edge,store.approvals(run['id'],run['snapshot']['graph']))
    def app(): return create_app([],professor_store=StudentStore(store.path),runs_root=ROOT/'outputs/runs',model_factory=no_models)
    with TestClient(app(),base_url='http://127.0.0.1') as client:
        def get(path):
            response=client.get('/api/professor/'+path);response.raise_for_status();return response.json()
        assert len(get('catalog')['students'])==3
        for student_id in expected:
            for run in runs:
                live=get('runs/'+run['id']+'/knowledge?'+urlencode(dict(student_id=student_id)))
                assert live['knowledge']==StudentStore(store.path).knowledge(student_id,run['id'])
        for key,entry in ledger['sessions'].items():
            if not entry.get('state'): continue
            restored=get('sessions/'+entry['state']['id'])
            assert restored['student_id']==entry['student_id'] and restored['run_id']==entry['run_id']
            checkpoint=store.session(entry['state']['id'])['checkpoint']
            quiz=QuizSession.restore(checkpoint['graph_snapshot'],None,checkpoint)
            assert not quiz.review_mode
            assert not ({e['id'] for e in quiz._eligible()} & quiz.independent)
            # Inspect review eligibility in memory only: no administrative quiz
            # or fabricated assessment is added to the student's natural history.
            quiz.review_mode=True
            assert quiz.independent <= {e['id'] for e in quiz._eligible()}
            for submission in entry.get('submissions',{}).values():
                answer=next(a for a in before_answers if a['id']==submission['answer_id'])
                assert answer['text']==submission['answer'] and answer['question']['text']==submission['question']['text']
                assert answer['score']==submission['score'] and not answer['overrides']
                assert not ({f['id'] for f in answer['question']['examiner_material']['facts']} & set(checkpoint['round_start_matches']))
        replay=next(r for r in ledger['commands'].values() if r['body']['action']=='answer' and r['status']=='completed')
        response=client.post('/api/professor/quiz',json=replay['body']);response.raise_for_status()
        assert response.json()==replay['response']
    assert store.answers()==before_answers
    pending=[p for e in ledger['sessions'].values() if e.get('state') for p in store.pending_answers(e['state']['id'])]
    result=dict(passed=True,students=expected,source_graph_hashes_preserved=True,
                database_integrity='ok',sessions=len(store.history()),answers=len(before_answers),
                pending_answers=len(pending),contribution_statuses=dict(Counter(r['status'] for r in rows)),
                persistence_after_new_app=True,student_ownership=True,idempotent_answer_replay=True,
                green_excluded_from_normal_quizzes=True,explicit_review_can_include_green=True,
                unapproved_student_contributions_excluded_from_quizzes=True,
                natural_records_have_no_professor_overrides=True)
    if args.browser:
        from playwright.sync_api import sync_playwright,expect
        from pipeline.submission import start_server,stop_server
        import pipeline.submission as notebook_server
        policy=asyncio.get_event_loop_policy()
        try:
            if sys.platform=='win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            url=start_server(app())['url']
            notebook_server._server_state[0].config.timeout_graceful_shutdown=2
        finally: asyncio.set_event_loop_policy(policy)
        capture=work/'interface';capture.mkdir(exist_ok=True)
        errors=[]
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                page=browser.new_page(viewport=dict(width=1440,height=1000))
                page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(url+'/professor')
                expect(page.locator('#practice-policy')).to_contain_text('Starting concept:')
                assert page.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(247, 246, 240)'
                page.locator('#tab-class').click()
                expect(page.locator('.student-card')).to_have_count(3)
                assert sorted(page.locator('.student-card h3').all_text_contents())==sorted(expected.values())
                for preview in page.locator('.student-card svg').all():
                    assert preview.locator('circle').count()<=30 and preview.locator('line').count()<=60
                    assert 'of' in preview.get_attribute('aria-label')
                page.locator('#roster-section').scroll_into_view_if_needed()
                page.screenshot(path=str(capture/'class-roster.png'))
                page.locator('.student-card').filter(has=page.get_by_role('heading',name='Elena Morales',exact=True)).click()
                expect(page.locator('#student-title')).to_have_text('Elena Morales')
                page.locator('#student-title').scroll_into_view_if_needed()
                page.screenshot(path=str(capture/'student-detail.png'))
                frame=page.frame_locator('#graph')
                expect(frame.locator('#canvas')).to_be_visible()
                expect(frame.locator('.node').first).to_be_visible()
                expect(frame.locator('main aside>p.muted')).to_contain_text('Green means independent mastery')
                assert frame.locator('body').evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(255, 255, 255)'
                page.locator('#graph-workspace').scroll_into_view_if_needed()
                page.screenshot(path=str(capture/'student-graph.png'))
                page.locator('#tab-quiz').click()
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(capture/'quiz.png'))
                page.set_viewport_size(dict(width=390,height=844))
                page.evaluate('scrollTo(0,0)')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(capture/'mobile.png'))
                assert not errors,errors
                result['browser']=dict(passed=True,javascript_errors=errors,mobile_overflow=False,artifacts=str(capture.relative_to(ROOT)))
                browser.close()
        finally:
            try: stop_server()
            except RuntimeError:
                # Only the temporary verification server created above is stopped.
                if notebook_server._server_state: notebook_server._server_state[0].force_exit=True
                stop_server()
    (work/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__': main()
