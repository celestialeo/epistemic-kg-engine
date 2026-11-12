"""Real-browser checks for three-tab navigation, scopes, ownership and persistence."""
import json
import asyncio
from pathlib import Path
import sys
import uuid

from playwright.sync_api import sync_playwright, expect
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.submission import start_server, stop_server
import pipeline.submission as notebook_server
from tests.test_professor import TeachingModels, write_run
from pipeline.models import ModelResponseError, ModelServiceError


class WorkspaceModels(TeachingModels):
    reject_questions = False
    help_failure = None

    def ask(self, role, *args, **kwargs):
        if self.reject_questions and role == 'quiz_question':
            raise ModelResponseError('Fixture: no suitable draft')
        if role == self.help_failure:
            raise ModelServiceError('Fixture: help model unavailable')
        return super().ask(role, *args, **kwargs)


def main():
    root=Path('outputs/professor_checks')/('workspace_'+uuid.uuid4().hex[:10])
    root.mkdir(parents=True)
    runs=root/'runs'
    write_run(runs,topic='water',name='run_01')
    write_run(runs,topic='water',name='run_02',timestamp='2026-10-30T12:00:00+00:00')
    rainfall=write_run(runs,topic='rainfall')
    file=rainfall/'artifacts/graph.json'
    graph=json.loads(file.read_text());graph['edges'][0]['conditions']='during rain';file.write_text(json.dumps(graph))
    store=StudentStore(root/'students.sqlite3')
    model=WorkspaceModels()
    def serve():
        policy = asyncio.get_event_loop_policy()
        try:
            if sys.platform == 'win32':
                # Selector only for the fixture server; Playwright needs Proactor.
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            url = start_server(create_app([],professor_store=store,runs_root=runs,model_factory=lambda s,t:model))['url']
            notebook_server._server_state[0].config.timeout_graceful_shutdown = 2
            return url
        finally:
            asyncio.set_event_loop_policy(policy)
    url=serve();errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url+'/professor')
            expect(page.locator('#tab-quiz')).to_have_attribute('aria-current','page')
            expect(page.locator('.main-navigation button')).to_have_count(3)
            expect(page.locator('#scope-topic')).to_have_value('')
            expect(page.locator('#source-context')).to_contain_text('2 unique relationships')
            for name in ('Ada','Grace'):
                page.locator('#student-name').fill(name);page.get_by_role('button',name='Add student',exact=True).click()
                expect(page.locator('#status')).to_have_text('Student added.')
            catalog=page.request.get(url+'/api/professor/catalog').json()
            ada=next(s['id'] for s in catalog['students'] if s['name']=='Ada')
            grace=next(s['id'] for s in catalog['students'] if s['name']=='Grace')
            water=next(t for t in catalog['topics'] if t['title']=='water')
            rain=next(t for t in catalog['topics'] if t['title']=='rainfall')
            old=next(t for t in catalog['versions'] if t['title']=='water' and t['run_name']=='run_01')
            page.locator('#student-select').select_option(ada)
            expect(page.locator('#start')).to_be_enabled()
            page.locator('#quiz-source').select_option(water['id'])
            def start():
                page.locator('#start').click();expect(page.locator('#quiz-student')).to_have_value(ada)
                page.locator('#confirm-quiz-student').click();expect(page.locator('#submit-answer')).to_be_enabled()
            model.reject_questions=True
            page.locator('#start').click();page.locator('#confirm-quiz-student').click()
            expect(page.locator('#status')).to_contain_text("Couldn't generate a suitable question")
            expect(page.locator('#pending-banner')).to_be_hidden()
            expect(page.locator('#try-another-concept')).to_be_visible()
            assert store.history()==[]
            model.reject_questions=False
            page.locator('#try-another-concept').click()
            expect(page.locator('#submit-answer')).to_be_enabled()
            expect(page.locator('#quiz-run')).to_contain_text('run_02')
            page.locator('#answer').fill('Unsubmitted explanation survives navigation.')
            page.locator('#tab-class').click()
            expect(page.locator('#student-cards .student-card')).to_have_count(2)
            page.locator('#learning-details > summary').click()
            expect(page.locator('#learning-source-details')).to_contain_text('Graph communities')
            expect(page.locator('#advanced-learning-metrics')).to_contain_text('n = 2 students')
            page.locator('#learning-details > summary').click()
            page.evaluate('scrollTo(0, 0)')
            page.screenshot(path=str(root/'class-overview.png'),full_page=True)
            page.locator('.student-card').filter(has=page.get_by_role('heading',name='Grace',exact=True)).click()
            expect(page.locator('#student-title')).to_have_text('Grace')
            page.locator('#back-to-class').click()
            page.locator('.student-card').filter(has=page.get_by_role('heading',name='Ada',exact=True)).click()
            page.locator('#quiz-this-student').click()
            expect(page.locator('#tab-quiz')).to_have_attribute('aria-current','page')
            expect(page.locator('#answer')).to_have_value('Unsubmitted explanation survives navigation.')
            page.locator('#scope-topic').select_option(rain['topic_key'])
            expect(page.locator('#quiz')).to_be_hidden()
            page.locator('#scope-topic').select_option('')
            expect(page.locator('#quiz')).to_be_visible()
            model.help_failure='quiz_hint'
            page.locator('#hint').click()
            expect(page.locator('#status')).to_contain_text('No hint was shown')
            expect(page.locator('#help')).to_be_hidden()
            expect(page.locator('#pending-banner')).to_be_hidden()
            expect(page.locator('#reveal')).to_be_enabled()
            model.help_failure=None
            page.locator('#hint').click();expect(page.locator('#help')).to_be_visible()
            model.help_failure='quiz_reveal'
            page.locator('#reveal').click()
            expect(page.locator('#status')).to_contain_text('Showing the saved validated answer')
            expect(page.locator('#help')).to_contain_text('Saved validated answer: Water enters soil.')
            expect(page.locator('#pending-banner')).to_be_hidden()
            model.help_failure=None
            page.locator('#answer').fill('Water enters soil.');page.locator('#submit-answer').click()
            expect(page.locator('#feedback')).to_contain_text('100%')
            page.screenshot(path=str(root/'quiz.png'),full_page=True)
            page.locator('#next').click();expect(page.locator('#quiz-complete')).to_be_visible()
            page.locator('#quiz-source').select_option(rain['id']);start()
            # A failed answer must stay attached to this student/run across restart.
            model.fail=True
            page.locator('#answer').fill('Water enters soil.');page.locator('#submit-answer').click()
            expect(page.locator('#status')).to_contain_text('saved and awaiting grading')
            expect(page.locator('#retry')).to_be_enabled()
            pending_session=next(s for s in store.history(ada) if not s['completed'])
            pending=store.pending_answers(pending_session['id'])[0]
            page.locator('#tab-insights').click()
            expect(page.locator('#insights-view')).to_be_visible()
            expect(page.locator('#pending-banner')).to_be_visible()
            context.close();stop_server();url=serve()
            context=browser.new_context(viewport={'width':1440,'height':1000})
            page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url+'/professor');page.locator('#tab-class').click()
            page.locator('.student-card').filter(has=page.get_by_role('heading',name='Ada',exact=True)).click()
            expect(page.locator('#history')).to_contain_text('Resume pending answer')
            page.locator('#history').get_by_role('button',name='Resume pending answer').click()
            expect(page.locator('#scope-topic')).to_have_value(rain['topic_key'])
            expect(page.locator('#topic')).to_have_value(rain['id'])
            expect(page.locator('#answer')).to_have_value('Water enters soil.')
            expect(page.locator('#retry')).to_be_enabled()
            model.fail=False;page.locator('#retry').click();expect(page.locator('#status')).to_have_text('Assessment saved.')
            assert len(store.answers(pending_session['id']))==1
            assert store.pending_answers(pending_session['id'])==[]
            replay=page.request.post(url+'/api/professor/quiz',data=pending['request']);assert replay.ok
            assert len(store.answers(pending_session['id']))==1
            page.locator('#tab-class').click()
            expect(page.locator('#student-title')).to_have_text('Ada')
            page.locator('#history').get_by_role('button',name='Inspect answers').first.click()
            expect(page.locator('#review')).to_be_visible()
            page.locator('#review .override select').first.select_option('related')
            page.get_by_label('Feedback for the student',exact=True).fill('Partly correct in this fixture.')
            page.get_by_label('Reason for this correction',exact=True).fill('Demonstration correction.')
            page.get_by_role('button',name='Save correction',exact=True).click()
            expect(page.locator('#status')).to_contain_text('Correction saved')
            expect(page.locator('#review')).to_contain_text('Current score: 50%')
            page.screenshot(path=str(root/'student-detail.png'),full_page=True)
            page.locator('#scope-topic').select_option('')
            expect(page.locator('#source-context')).to_contain_text('2 unique relationships')
            expect(page.locator('#history .history-item')).to_have_count(2)
            page.locator('#tab-insights').click()
            expect(page.locator('#run-cards')).to_contain_text('Unavailable')
            expect(page.locator('#validation-cards')).to_contain_text('Unavailable')
            expect(page.locator('#insight-breakdown tr')).to_have_count(2)
            page.locator('#insight-run').select_option(water['id'])
            expect(page.locator('#insight-aggregate')).not_to_be_checked()
            page.screenshot(path=str(root/'run-insights.png'),full_page=True)
            page.locator('#scope-topic').select_option(water['topic_key']);page.locator('#topic').select_option(old['id'])
            expect(page.locator('#results-meta')).to_contain_text('run_01')
            page.locator('#tab-class').click()
            expect(page.locator('#student-title')).to_have_text('Ada')
            expect(page.locator('#history')).to_contain_text('Historical version')
            # Current scope persists on reload; historical quizzes are explicitly labelled.
            page.reload();expect(page.locator('#tab-class')).to_have_attribute('aria-current','page')
            expect(page.locator('#scope-topic')).to_have_value(water['topic_key'])
            expect(page.locator('#topic')).to_have_value(old['id'])
            expect(page.locator('#student-title')).to_have_text('Ada')
            page.locator('#quiz-this-student').click();expect(page.locator('#student-select')).to_have_value(ada)
            # Explore and statement comparison still use the original source viewer.
            page.locator('#graph-mode').select_option('explore')
            frame=page.frame_locator('#graph');expect(frame.locator('#query-form')).to_be_visible()
            report=page.request.get(url+'/api/professor/runs/'+old['id']+'/knowledge').json()
            edge=report['graph']['edges'][0]
            response=dict(interpretation=dict(concepts=['Water'],assertions=[]),checked_records=3,
                          matches=[dict(kind='edge',id=edge['id'],status='match',record=edge,reason='Browser fixture',input_quote='Water enters soil.')])
            before=store.knowledge(ada,old['id'])
            page.route('**/runs/*/match',lambda route:route.fulfill(json=response))
            frame.locator('#query-text').fill('Water enters soil.');frame.locator('#query-submit').click()
            expect(frame.locator('#query-status')).to_contain_text('1 relationships found')
            assert store.knowledge(ada,old['id'])==before
            # The previously assisted water fact can be demonstrated without help
            # in a later quiz. Green survives reload and is excluded by default.
            page.locator('#topic').select_option(water['id'])
            start()
            page.locator('#answer').fill('Water enters soil.')
            page.locator('#submit-answer').click()
            expect(page.locator('#feedback')).to_contain_text('100%')
            expect(page.locator('#submit-answer')).to_be_disabled()
            page.locator('#next').click()
            expect(page.locator('#quiz-complete')).to_be_visible()
            expect(page.locator('#start')).to_be_disabled()
            page.reload()
            expect(page.locator('#quiz-summary')).to_contain_text('100%')
            expect(page.locator('#start')).to_be_disabled()
            assert store.knowledge(ada,water['id'])['entry']['mark']=='match'
            assert not store.knowledge(ada,water['id'])['entry']['helped']
            page.locator('#review-mode').check()
            expect(page.locator('#start')).to_be_enabled()
            page.locator('#review-mode').uncheck()
            page.locator('#scope-topic').select_option('')
            aggregate = page.frame_locator('#graph')
            expect(aggregate.locator('.node circle').first).to_have_attribute('fill','#f3bf62')
            expect(aggregate.locator('.edge line[stroke="#54d99a"]')).to_have_count(1)
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(root/'mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow'
            assert not errors,errors
            result=dict(passed=True,artifacts=str(root),javascript_errors=errors,
                        checks='three tabs, context, aggregate scopes, graph versions, student ownership, hints, persistence after server/browser restart, pending retry idempotence, grading corrections, history, statement matching, generation recovery, safe hint failure, validated reveal fallback, yellow-to-green persistence, green exclusion, aggregate node colors, mobile')
            (root/'verification.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result))
            browser.close()
    finally:
        try:
            stop_server()
        except RuntimeError:
            # Only this isolated browser-fixture server is eligible for forced exit.
            # Chrome may leave an aborted keepalive request during teardown on Windows.
            if notebook_server._server_state:
                notebook_server._server_state[0].force_exit = True
            stop_server()


if __name__=='__main__':
    main()
