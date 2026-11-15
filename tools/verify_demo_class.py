"""Read-only browser verification of the published synthetic AI-test class."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright,expect
from pipeline.explorer import create_app,load_snapshot
from pipeline.professor import run_identity,topic_identity
from pipeline.student_store import StudentStore
from pipeline.professor_scope import summarize_scope
from pipeline.submission import start_server,stop_server
import pipeline.submission as server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    store=StudentStore(args.database);snapshot=load_snapshot(args.run)
    run_id=run_identity(snapshot);topic,_=topic_identity(snapshot)
    students=store.students();history=store.history();answers=store.answers()
    assert len(students)==10 and all('(demo)' not in s['name'] for s in students)
    assert len(history)==40 and all(s['completed'] for s in history)
    assert all(sum(h['student_id']==s['id'] for h in history)==4 for s in students)
    assert all(a['result']['assessment_version']==3 and not a['overrides'] for a in answers)
    assert all(a['result']['graph_assessment']['status']=='resolved' for a in answers)
    summary=summarize_scope(store,topic=topic,run_id=run_id)
    totals={state:sum(s['categories'][state] for s in summary['students']) for state in summary['students'][0]['categories']}
    assert totals['independent']>0 and (totals['partial']+totals['assisted_correct'])>0
    assert (totals['incorrect']+totals['not_demonstrated'])>0
    prior=asyncio.get_event_loop_policy();asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        url=start_server(create_app([],professor_store=store,runs_root=args.run.parent))['url']
        server._server_state[0].config.timeout_graceful_shutdown=2
    finally:asyncio.set_event_loop_policy(prior)
    errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda e:errors.append(str(e)))
            # Deleted-roster requests must not leave an unusable pending banner.
            old_id=str(uuid.uuid4())
            page.add_init_script("localStorage.setItem('professor:active',JSON.stringify({id:"+json.dumps(old_id)+"}));localStorage.setItem('professor:pending',JSON.stringify({action:'answer',session_id:"+json.dumps(old_id)+"}));")
            page.goto(url+'/professor?run='+run_id+'&view=class')
            expect(page.locator('#class-summary-view')).to_be_visible()
            expect(page.locator('#pending-banner')).to_be_hidden()
            expect(page.locator('#student-cards .student-card')).to_have_count(10)
            expect(page.locator('#student-cards .student-card').first).to_be_enabled()
            expect(page.locator('#scope-topic')).to_have_value(topic)
            page.locator('#class-summary-view > section').first.screenshot(path=str(args.output/'class-summary.png'))
            page.locator('#roster-section').screenshot(path=str(args.output/'ten-students.png'))
            for name in ['Maya Chen','Amara Okafor','Leo Martin']:
                s=next(s for s in students if s['name']==name)
                page.locator('#class-student-switch').select_option(s['id'])
                expect(page.locator('#student-title')).to_have_text(name)
                expect(page.locator('#history .history-item')).to_have_count(4)
                expect(page.locator('#graph-title')).to_contain_text(name)
                expect(page.locator('#class-student-switch')).to_be_enabled()
                page.locator('#history').get_by_role('button',name='Inspect answers').first.click()
                expect(page.locator('#review')).to_be_visible()
                assert page.locator('#answers .answer-card').count()>0
                page.locator('#close-review').click()
                page.locator('#student-metrics').screenshot(path=str(args.output/(name.split()[0].lower()+'-metrics.png')))
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors,errors
            browser.close()
        report=dict(passed=True,students=10,sessions=40,answers=len(answers),categories=totals,javascript_errors=errors,
            students_summary=[dict(name=s['name'],coverage=s['metrics']['knowledge_coverage'],categories=s['categories']) for s in summary['students']])
        (args.output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
    finally:
        try:stop_server()
        except RuntimeError:
            if server._server_state:server._server_state[0].force_exit=True
            stop_server()


if __name__=='__main__':main()
