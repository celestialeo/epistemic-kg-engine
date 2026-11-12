"""Browser checks for explicit background approval and independent matching retry."""
import json
from pathlib import Path
import uuid

from playwright.sync_api import sync_playwright, expect
from pipeline.explorer import create_app
from pipeline.models import ModelResponseError
from pipeline.student_store import StudentStore
from pipeline.submission import start_server, stop_server
import pipeline.submission as server
from tests.test_professor import TeachingModels, write_run


class Models(TeachingModels):
    matching_fails=True
    def ask(self,role,*args,**kwargs):
        if role=='quiz_meaning' and self.matching_fails:
            raise ModelResponseError('Fixture: overlapping source and target evidence after bounded retries')
        return super().ask(role,*args,**kwargs)


def main():
    root=Path('outputs/professor_checks')/('assessment_'+uuid.uuid4().hex[:10]);root.mkdir(parents=True)
    runs=root/'runs';run=write_run(runs)
    p=run/'artifacts/graph.json';graph=json.loads(p.read_text())
    graph['edges'].append(dict(id='background_return',source='soil',target='water',label='retains',origin='background',
                              definition='Soil can retain water.',evidence='Generated supporting text requires review.'))
    p.write_text(json.dumps(graph))
    store=StudentStore(root/'students.sqlite3');models=Models();errors=[]
    url=start_server(create_app([],professor_store=store,runs_root=runs,model_factory=lambda *_:models))['url']
    server._server_state[0].config.timeout_graceful_shutdown=2
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url+'/professor')
            page.locator('#student-name').fill('Ada');page.get_by_role('button',name='Add student',exact=True).click()
            expect(page.locator('#status')).to_have_text('Student added.')
            page.locator('#tab-insights').click();page.locator('#background-review > summary').click()
            expect(page.locator('#background-facts')).to_contain_text('Not approved; excluded from quizzes.')
            page.get_by_label('Review reason or supporting reference').fill('Professor checked the course reference in this fixture.')
            page.get_by_role('button',name='Approve for quizzes',exact=True).click()
            expect(page.locator('#background-facts')).to_contain_text('Approved for quizzes.')
            page.reload();page.locator('#background-review > summary').click()
            expect(page.locator('#background-facts')).to_contain_text('Approved for quizzes.')
            page.get_by_label('Review reason or supporting reference').fill('Revoke for the isolated matching test.')
            page.get_by_role('button',name='Revoke quiz approval').click()
            expect(page.locator('#background-facts')).to_contain_text('Not approved; excluded from quizzes.')
            page.screenshot(path=str(root/'background-approval.png'),full_page=True)
            page.locator('#tab-quiz').click();page.locator('#start').click();page.locator('#confirm-quiz-student').click()
            expect(page.locator('#submit-answer')).to_be_enabled()
            page.locator('#answer').fill('Water enters soil.');page.locator('#submit-answer').click()
            expect(page.locator('#feedback')).to_contain_text('100%')
            expect(page.locator('#feedback')).to_contain_text('Graph matching is unresolved')
            answer=store.answers()[0]
            self_run=store.history()[0]['run_id'];student=store.students()[0]['id']
            assert store.knowledge(student,self_run)=={}
            page.locator('#tab-class').click()
            page.locator('.student-card').filter(has=page.get_by_role('heading',name='Ada',exact=True)).click()
            page.locator('#history').get_by_role('button',name='Inspect answers').click()
            expect(page.locator('#review')).to_contain_text('Full relationship:')
            page.get_by_role('button',name='Retry graph matching').click()
            expect(page.locator('#status')).to_contain_text('Graph matching remains unresolved')
            assert store.answers()[0]['score']==100 and store.knowledge(student,self_run)=={}
            models.matching_fails=False
            page.get_by_role('button',name='Retry graph matching').click()
            expect(page.locator('#status')).to_contain_text('Graph matching completed')
            expect(page.get_by_role('button',name='Retry graph matching')).to_have_count(0)
            assert len(store.answers())==1 and store.answers()[0]['id']==answer['id']
            assert store.answers()[0]['score']==100
            assert store.knowledge(student,self_run)['entry']['mark']=='match'
            page.screenshot(path=str(root/'matching-retry.png'),full_page=True)
            assert errors==[],errors
            browser.close()
        print(json.dumps(dict(passed=True,artifacts=str(root),javascript_errors=errors,
            checks='versioned approval/revocation, reload persistence, question score during graph failure, matching retry without duplicate grade, scope explanation')))
    finally:stop_server()


if __name__=='__main__':main()
