"""Isolated, explicitly synthetic browser checks for class/student graph metrics."""
import asyncio
import json
from pathlib import Path
import uuid
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect

from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.submission import start_server, stop_server
import pipeline.submission as notebook_server
from tests.test_professor import write_run


def main():
    root=Path('outputs/professor_checks')/('metrics_'+uuid.uuid4().hex[:10])
    runs=root/'runs'
    run=write_run(runs,topic='Water cycle · demonstration')
    labels=['Sunlight','Evaporation','Water vapor','Condensation','Clouds','Rainfall','Runoff','Rivers','Ocean','Infiltration','Groundwater','Soil']
    pairs=[(0,1),(1,2),(2,3),(3,4),(4,5),(3,5),(5,6),(6,7),(7,8),(6,8),(8,1),(5,9),(9,10),(10,11),(11,9),(10,8)]
    graph=dict(run_id='Demo graph',nodes=[dict(id=str(i),label=label,kind='concept',definition=label,origin='document') for i,label in enumerate(labels)],
               edges=[dict(id='e'+str(i),source=str(a),target=str(b),label='connects to',origin='document',definition='Synthetic demonstration relationship') for i,(a,b) in enumerate(pairs)])
    (run/'artifacts/graph.json').write_text(json.dumps(graph),encoding='utf-8')
    store=StudentStore(root/'students.sqlite3')
    ada=store.add_student('Ada · demo')['id'];grace=store.add_student('Grace · demo')['id'];sam=store.add_student('Sam · unassessed demo')['id']
    profiles={ada:{'e'+str(i):dict(mark='match' if i<10 else 'related',helped=False) for i in range(13)},
              grace:{'e'+str(i):dict(mark='match',helped=i==5) for i in [0,1,2,5,11,12]}}
    def knowledge(student_id,run_id,runs,history,include_current=True):
        return {key:dict(f,at='2026-11-11T12:00:00+00:00',source_run_id=run_id) for key,f in profiles.get(student_id,{}).items()}
    previous=asyncio.get_event_loop_policy()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        url=start_server(create_app([],professor_store=store,runs_root=runs))['url']
        notebook_server._server_state[0].config.timeout_graceful_shutdown=2
    finally:
        asyncio.set_event_loop_policy(previous)
    errors=[]
    try:
        with patch.object(StudentStore,'_knowledge',staticmethod(knowledge)),sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1050})
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url+'/professor');page.locator('#tab-class').click()
            expect(page.locator('#metrics-grid .analysis-card:visible')).to_have_count(4)
            expect(page.locator('#class-location')).to_have_text('Class Overview / All students')
            expect(page.locator('#metrics-grid [data-metric="relationship_coverage"]')).to_contain_text('31.2%')
            page.locator('#metric-explorer').scroll_into_view_if_needed()
            page.locator('#metric-explorer').screenshot(path=str(root/'class-breadth.png'))
            page.locator('[data-filter="connections"]').click()
            expect(page.locator('#metrics-grid .analysis-card:visible')).to_have_count(5)
            expect(page.locator('[data-metric="average_degree"]')).to_contain_text('n = 2 / 3 students')
            page.locator('[data-metric="global_efficiency"] summary').click()
            expect(page.locator('[data-metric="global_efficiency"] details')).to_have_attribute('open','')
            page.locator('[data-filter="topics"]').click()
            expect(page.locator('#metrics-grid .analysis-card:visible')).to_have_count(3)
            page.locator('[data-filter="all"]').click()
            expect(page.locator('#metrics-grid .analysis-card:visible')).to_have_count(12)
            page.locator('#class-student-switch').select_option(ada)
            expect(page.locator('#metrics-owner')).to_contain_text('INDIVIDUAL RESULTS')
            expect(page.locator('#class-collective')).to_be_hidden()
            expect(page.locator('#graph-title')).to_contain_text('Ada')
            expect(page.locator('#graph-mode')).to_be_hidden()
            expect(page.locator('#student-strengths')).to_contain_text('10 relationships')
            expect(page.locator('#student-support')).to_contain_text('3 relationships')
            expect(page.locator('#student-unassessed')).to_contain_text('3 relationships')
            page.locator('[data-filter="connections"]').click()
            page.locator('#metric-explorer').screenshot(path=str(root/'student-connections.png'))
            page.locator('#concept-details > summary').click()
            expect(page.locator('#concept-table tbody tr')).to_have_count(12)
            page.locator('#concept-search').fill('Rainfall')
            expect(page.locator('#concept-table tbody tr')).to_have_count(1)
            page.locator('#concept-sort').select_option('completeness')
            page.locator('#concept-search').fill('')
            page.locator('#concept-details').screenshot(path=str(root/'student-concepts.png'))
            page.locator('#class-student-switch').select_option(sam)
            expect(page.locator('[data-metric="average_degree"] .analysis-value')).to_have_text('Unavailable')
            expect(page.locator('#student-support')).to_contain_text('No evidence')
            expect(page.locator('#student-unassessed')).to_contain_text('16 relationships')
            page.locator('#class-student-switch').select_option(ada)
            page.reload();expect(page.locator('#student-title')).to_contain_text('Ada')
            page.set_viewport_size({'width':390,'height':844})
            page.locator('[data-filter="all"]').click()
            expect(page.locator('#metrics-grid .analysis-card:visible')).to_have_count(12)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),'Mobile page overflow'
            page.locator('#metric-explorer').screenshot(path=str(root/'mobile-metrics.png'))
            page.locator('#back-to-class').click()
            expect(page.locator('#class-student-switch')).to_have_value('')
            expect(page.locator('#metrics-owner')).to_have_text('CLASS PATTERNS')
            assert not errors,errors
            browser.close()
            result=dict(passed=True,artifacts=str(root),javascript_errors=errors,
                        checks='12 metrics, category filters, class/student means, missing evidence, reference comparison, concept search/sort, degree distribution, student switching, reload, mobile')
            (root/'verification.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result))
    finally:
        try:stop_server()
        except RuntimeError:
            if notebook_server._server_state:notebook_server._server_state[0].force_exit=True
            stop_server()


if __name__=='__main__':main()
