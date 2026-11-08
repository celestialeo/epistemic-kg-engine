"""Chrome/Playwright checks for run views and persistent learning graphs."""
import json
from pathlib import Path
import socket
import threading
import time
import uuid

from playwright.sync_api import sync_playwright, expect
import uvicorn
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from tests.test_professor import TeachingModels, write_run


def main():
    root = Path('outputs/professor_checks') / ('views_' + uuid.uuid4().hex[:10])
    root.mkdir(parents=True)
    write_run(root/'runs')
    database = root/'students.sqlite3'
    models = TeachingModels()
    app = create_app([], professor_store=StudentStore(database), runs_root=root/'runs', model_factory=lambda s,t: models)
    errors = []
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0));sock.listen(128)
        url = f'http://127.0.0.1:{sock.getsockname()[1]}'
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning'))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic()+15
        while not server.started:
            if time.monotonic()>deadline:
                raise RuntimeError('Test server failed to start')
            time.sleep(.05)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome', headless=True)
                page = browser.new_page(viewport={'width':1440, 'height':1100})
                page.on('pageerror', lambda error: errors.append(str(error)))
                topic = page.request.get(url+'/api/professor/catalog').json()['topics'][0]
                page.goto(url+'/professor?run='+topic['id'])
                expect(page.locator('#professor-tab')).to_be_enabled()
                page.locator('#results-tab').click()
                expect(page.locator('#run-results')).to_be_visible()
                expect(page.locator('#professor-view')).to_be_hidden()
                expect(page.locator('#run-cards')).to_contain_text('Unavailable')
                expect(page.locator('#original-text')).to_have_text('Unavailable')
                page.screenshot(path=str(root/'results-desktop.png'), full_page=True)
                page.locator('#professor-tab').click()
                expect(page.locator('#graph-details')).to_be_visible()
                assert page.locator('#professor-view').evaluate('node=>node.lastElementChild.id') == 'graph-details'
                for name in ['Ada', 'Grace']:
                    page.locator('#student-name').fill(name)
                    page.get_by_role('button', name='Add student', exact=True).click()
                    expect(page.locator('#view-title')).to_have_text(name)
                page.locator('#class-view').click()
                expect(page.locator('#student-comparison tr')).to_have_count(2)
                page.locator('#student-comparison').get_by_role('button', name='Ada', exact=True).click()
                expect(page.locator('#view-title')).to_have_text('Ada')
                page.locator('#graph-mode').select_option('explore')
                frame = page.frame_locator('#graph')
                expect(frame.locator('#query-form')).to_be_visible()
                graph = page.request.get(url+'/api/professor/runs/'+topic['id']+'/knowledge').json()['graph']
                response = dict(interpretation=dict(concepts=['Water'], assertions=[]), checked_records=3,
                    matches=[dict(kind='edge', id='entry', status='match', record=graph['edges'][0], reason='Fixture exploration', input_quote='Water enters soil.')])
                page.route('**/runs/*/match', lambda route: route.fulfill(json=response))
                frame.locator('#query-text').fill('Water enters soil.');frame.locator('#query-submit').click()
                expect(frame.locator('#query-status')).to_contain_text('1 relationships found')
                def edge_status():
                    return page.locator('#graph').content_frame.locator('body').evaluate("()=>Object.fromEntries(edgeMatches)")
                assert edge_status() == {'entry':'match'}
                assert StudentStore(database).knowledge(StudentStore(database).students()[0]['id'], topic['id']) == {}
                # A query already in flight must not repaint knowledge after quiz start.
                page.unroute('**/runs/*/match')
                delayed = []
                page.route('**/runs/*/match', lambda route: delayed.append(route))
                frame.locator('#query-text').fill('Delayed exploration')
                frame.locator('#query-submit').click()
                expect(frame.locator('#query-submit')).to_be_disabled()
                def start(name):
                    page.locator('#start').click();page.locator('#quiz-student').select_option(label=name)
                    page.locator('#confirm-quiz-student').click()
                    expect(page.locator('#quiz-progress')).to_contain_text('Question 1')
                    expect(page.locator('#submit-answer')).to_be_enabled()
                def answer():
                    page.locator('#answer').fill('Water enters soil.');page.locator('#submit-answer').click()
                    expect(page.locator('#feedback')).to_contain_text('100%');expect(page.locator('#next')).to_be_enabled()
                def finish():
                    page.locator('#next').click();expect(page.locator('#quiz-complete')).to_be_visible()
                start('Ada')
                expect(frame.locator('#query-form')).to_be_hidden()
                assert len(delayed) == 1
                delayed[0].fulfill(json=response)
                expect(frame.locator('#query-submit')).to_be_enabled()
                assert edge_status() == {}
                answer();assert edge_status() == {'entry':'match'};finish()
                page.locator('#class-view').click()
                expect(page.locator('#student-comparison')).to_contain_text('100% / 100%')
                expect(page.locator('#student-comparison')).to_contain_text('0% / 0%')
                page.locator('#student-comparison').get_by_role('button', name='Grace', exact=True).click()
                expect(page.locator('#view-title')).to_have_text('Grace');expect(page.locator('#start')).to_be_enabled()
                assert edge_status() == {}
                start('Grace')
                page.locator('#reveal').click();expect(page.locator('#help')).to_be_visible()
                expect(page.locator('#submit-answer')).to_be_enabled()
                answer();assert edge_status() == {'entry':'related'};finish()
                page.locator('#class-view').click()
                expect(page.locator('#overlay-counts')).to_contain_text('1/2 independently know; 2/2 assessed')
                page.screenshot(path=str(root/'class-desktop.png'), full_page=True)
                # No local storage in a fresh browser context: the server owns knowledge.
                page = browser.new_page(viewport={'width':1440, 'height':1100})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url+'/professor?run='+topic['id'])
                expect(page.locator('#student-comparison tr')).to_have_count(2)
                page.locator('#student-comparison').get_by_role('button', name='Ada', exact=True).click()
                expect(page.locator('#start')).to_be_enabled()
                assert edge_status() == {'entry':'match'}
                newer = write_run(root/'runs', name='run_02', timestamp='2026-10-30T12:00:00+00:00')
                path = newer/'artifacts/graph.json';newgraph=json.loads(path.read_text())
                newgraph['edges'].append(dict(newgraph['edges'][0], id='qualified', conditions='when wet'))
                path.write_text(json.dumps(newgraph))
                page.locator('#refresh').click();expect(page.locator('#status')).to_contain_text('Latest completed')
                catalog = page.request.get(url+'/api/professor/catalog').json();latest=catalog['topics'][0]
                page.locator('#topic').select_option(latest['id'])
                expect(page.locator('#version-note')).to_contain_text('run_02');expect(page.locator('#start')).to_be_enabled()
                report = page.request.get(url+'/api/professor/runs/'+latest['id']+'/knowledge',
                    params={'student_id':next(s['id'] for s in catalog['students'] if s['name']=='Ada')}).json()
                assert report['selected']['metrics']['knowledge_coverage'] == 50
                assert report['selected']['metrics']['average_score'] is None
                assert set(report['knowledge']) == {'entry'}
                # A saved grading failure must be retryable after local storage
                # is lost, using the server's original submission/request ID.
                start('Ada')
                models.fail = True
                page.locator('#answer').fill('Water enters soil.')
                page.locator('#submit-answer').click()
                expect(page.locator('#status')).to_contain_text('saved and awaiting grading')
                expect(page.locator('#retry')).to_be_enabled()
                store = StudentStore(database)
                active_session = next(s for s in store.history() if s['run_id'] == latest['id'])
                pending = store.pending_answers(active_session['id'])[0]
                page = browser.new_page(viewport={'width':1440, 'height':1100})
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(url+'/professor?run='+latest['id'])
                page.locator('#student-comparison').get_by_role('button', name='Ada', exact=True).click()
                page.locator('#history').get_by_role('button', name='Resume', exact=True).click()
                expect(page.locator('#retry')).to_be_enabled()
                expect(page.locator('#answer')).to_have_value(pending['text'])
                expect(page.locator('#submit-answer')).to_be_disabled()
                assert page.evaluate("JSON.parse(localStorage.getItem('professor:pending')).request_id") == pending['id']
                models.fail = False
                page.locator('#retry').click()
                expect(page.locator('#status')).to_contain_text('Assessment saved.')
                expect(page.locator('#retry')).to_be_hidden()
                assert store.pending_answers(active_session['id']) == []
                assert len(store.answers(active_session['id'])) == 1
                replay = page.request.post(url+'/api/professor/quiz', data=pending['request'])
                assert replay.ok
                assert len(store.answers(active_session['id'])) == 1
                page.screenshot(path=str(root/'student-desktop.png'), full_page=True)
                page.set_viewport_size({'width':390, 'height':844})
                page.screenshot(path=str(root/'student-mobile.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
                assert not errors, errors
                browser.close()
            result = dict(passed=True, browser='Chrome', javascript_errors=errors, artifacts=str(root),
                flow='views, exploration reset, adaptive completion, student isolation, assistance, class overlay, fresh-browser restore, graph versions, pending-answer recovery and idempotent retry, mobile')
            (root/'verification.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result))
        finally:
            server.should_exit=True;thread.join(timeout=10)


if __name__ == '__main__':
    main()
