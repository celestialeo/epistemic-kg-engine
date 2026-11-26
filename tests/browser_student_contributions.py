"""Browser verification with fixture models, isolated from the real demo database."""
import asyncio
import json
from pathlib import Path
import uuid
from playwright.sync_api import sync_playwright, expect
from pipeline.explorer import create_app, load_snapshot
from pipeline.student_store import StudentStore
from pipeline.submission import start_server, stop_server
from tests.test_professor import write_run
from tests.test_student_contributions import ContributionModels


def main():
    root=Path('outputs/diagnostics/student_contributions')/('browser_'+uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    run=write_run(root/'runs')
    store=StudentStore(root/'students.sqlite3'); model=ContributionModels()
    model.claim['source']['existing_id']=next(n['id'] for n in load_snapshot(run).graph['nodes'] if n['label']=='soil')
    def serve():
        old=asyncio.get_event_loop_policy()
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            return start_server(create_app([],professor_store=store,runs_root=root/'runs',model_factory=lambda s,t:model))['url']
        finally: asyncio.set_event_loop_policy(old)
    url=serve(); errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport=dict(width=1440,height=1000))
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url+'/professor')
            page.locator('#student-name').fill('Contribution tester')
            page.get_by_role('button',name='Add student',exact=True).click()
            expect(page.locator('#status')).to_have_text('Student added.')
            page.locator('#start').click();page.locator('#confirm-quiz-student').click()
            expect(page.locator('#submit-answer')).to_be_enabled()
            page.locator('#answer').fill('Water enters soil. Soil stores carbon.')
            page.locator('#submit-answer').click()
            expect(page.locator('#status')).to_have_text('Grade saved. Contribution review completed.')
            expect(page.locator('#feedback')).to_contain_text('100%')
            card=page.locator('.contribution-card')
            expect(card).to_contain_text('accepted')
            page.locator('#graph-mode').select_option('explore')
            frame=page.frame_locator('#graph')
            expect(frame.locator('.legend')).to_contain_text('student contribution')
            # Check actual SVG stroke, not merely the legend text.
            expect(frame.locator('line[stroke="#f472b6"]')).to_have_count(1)
            card.screenshot(path=str(root/'accepted.png'))
            page.reload();expect(page.locator('.contribution-card')).to_contain_text('accepted')
            card=page.locator('.contribution-card')
            card.get_by_label('Professor name').fill('Reviewer')
            card.get_by_label('Review reason').fill('Browser undo verification')
            card.get_by_role('button',name='Undo graph addition').click()
            expect(page.locator('.contribution-card')).to_contain_text('undone')
            assert len(store.answers())==1 and store.answers()[0]['score']==100
            page.goto('about:blank');stop_server();url=serve()
            page.goto(url+'/professor')
            expect(page.locator('.contribution-card')).to_contain_text('undone')
            assert not errors,errors
            browser.close()
        (root/'result.json').write_text(json.dumps(dict(passed=True,errors=errors)),encoding='utf-8')
        print('Browser contribution grading, automatic validation, pink graph, undo and restart passed:',root)
    finally: stop_server()


if __name__=='__main__': main()
