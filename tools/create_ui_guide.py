"""Capture the actual three-tab workspace with isolated demonstration data."""
import base64
import asyncio
import html
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright, expect
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
import pipeline.submission as server
from tests.test_professor import TeachingModels, write_run


def build():
    images = {}
    with tempfile.TemporaryDirectory(prefix='professor-guide-') as directory:
        root = Path(directory)
        write_run(root/'runs', topic='Water movement', name='demo-source-v1')
        write_run(root/'runs', topic='Soil and water', name='demo-source-v1')
        model = TeachingModels()
        app = create_app([], professor_store=StudentStore(root/'students.sqlite3'),
                         runs_root=root/'runs', model_factory=lambda s,t: model)
        policy = asyncio.get_event_loop_policy()
        try:
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            url = server.start_server(app)['url']
        finally:
            asyncio.set_event_loop_policy(policy)
        server._server_state[0].config.timeout_graceful_shutdown = 2
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel='chrome', headless=True)
                page = browser.new_page(viewport={'width':1280,'height':900})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(url+'/professor')
                expect(page.locator('#source-context')).to_contain_text('1 unique relationships')

                def capture(name, selector=None):
                    page.evaluate('scrollTo(0,0)')
                    target = page.locator(selector) if selector else page
                    images[name] = base64.b64encode(target.screenshot(animations='disabled')).decode()

                for name in ('Demo learner A', 'Demo learner B'):
                    page.locator('#student-name').fill(name)
                    page.get_by_role('button',name='Add student',exact=True).click()
                    expect(page.locator('#status')).to_have_text('Student added.')
                catalog = page.request.get(url+'/api/professor/catalog').json()
                student = next(s['id'] for s in catalog['students'] if s['name']=='Demo learner A')
                page.locator('#student-select').select_option(student)
                expect(page.locator('#start')).to_be_enabled()
                capture('navigation')
                capture('scope','.shared-scope')
                capture('setup','#assessment-area')
                page.locator('#start').click()
                page.locator('#confirm-quiz-student').click()
                expect(page.locator('#submit-answer')).to_be_enabled()
                page.locator('#hint').click()
                expect(page.locator('#help')).to_be_visible()
                page.locator('#answer').fill('Water enters soil.')
                page.locator('#submit-answer').click()
                expect(page.locator('#feedback')).to_contain_text('100%')
                capture('answer','#quiz')
                page.locator('#next').click()
                expect(page.locator('#quiz-complete')).to_be_visible()
                page.locator('#tab-class').click()
                expect(page.locator('#student-cards .student-card')).to_have_count(2)
                capture('class','#class-summary-view > .card:first-child')
                capture('students','#student-cards')
                page.locator('.student-card').filter(has=page.get_by_role('heading',name='Demo learner A',exact=True)).click()
                expect(page.locator('#student-title')).to_have_text('Demo learner A')
                capture('history','#history-area')
                page.locator('#history').get_by_role('button',name='Inspect answers').click()
                expect(page.locator('#review')).to_be_visible()
                capture('grading','#review')
                page.locator('#close-review').click()
                page.locator('#learning-details > summary').click()
                expect(page.locator('#learning-source-details')).to_contain_text('Graph communities')
                capture('advanced','#advanced-learning-metrics')
                page.locator('#learning-details > summary').click()
                page.locator('#scope-topic').select_option(catalog['topics'][0]['topic_key'])
                page.locator('#graph-mode').select_option('explore')
                frame = page.frame_locator('#graph')
                expect(frame.locator('#query-form')).to_be_visible()
                expect(frame.locator('.edge')).to_have_count(1)
                frame.locator('.edge').click()
                images['graph'] = base64.b64encode(frame.locator('.graph-shell').screenshot(animations='disabled')).decode()
                images['comparison'] = base64.b64encode(frame.locator('#query-form').screenshot(animations='disabled')).decode()
                page.locator('#tab-insights').click()
                expect(page.locator('#run-cards')).to_contain_text('Unavailable')
                capture('results','#run-cards')
                capture('quality','#reconstruction-scores')
                assert not errors, errors
                path = ROOT/'docs/Interactive_Graph_Guide.html'
                path.write_text(make_document(make_sections(images)),encoding='utf-8')
                preview = browser.new_page()
                preview.goto(path.as_uri(),wait_until='load')
                assert preview.locator('img').evaluate_all('(xs)=>xs.every(x=>x.complete && x.naturalWidth>0)')
                preview.pdf(path=str(path.with_suffix('.pdf')),format='A4',print_background=True,
                            prefer_css_page_size=True,display_header_footer=True,header_template='<span></span>',
                            footer_template='<div style="font-size:9px;width:100%;text-align:center">Professor workspace guide · Demonstration data · <span class="pageNumber"></span> / <span class="totalPages"></span></div>')
                browser.close()
                print('Updated HTML/PDF guide: 8 sections, 13 actual UI screenshots, no browser errors.')
        finally:
            try:
                server.stop_server()
            except RuntimeError:
                if server._server_state:
                    server._server_state[0].force_exit = True
                server.stop_server()


def make_sections(images):
    def picture(key, caption):
        return f'<figure><img src="data:image/png;base64,{images[key]}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>'
    def page(title, content):
        return (title, '<section><p class="kicker">ECSE 679 · PROFESSOR WORKSPACE · DEMONSTRATION DATA</p><h1>'+title+'</h1>'+content+'</section>')
    return [
        page('One workspace, three tabs', picture('navigation','The actual interface, with demonstration learners.')+'''
<p><b>Quiz</b> is for one student's practice. <b>Run Insights</b> explains the saved source graph. <b>Class Overview</b> shows the class and opens student details.</p>
<p>The topic and source-version selectors apply across all three tabs. Switching views keeps the selected student and topic. Advanced information is expandable.</p>
<p class="note">All screenshots use isolated demonstration records and deterministic test grading. They are interface examples, not evaluation results or real student performance.</p>
<pre>python run_pipeline.py --interact --chapter ai-test</pre>
<p>This opens saved work without rerunning extraction. Omit the chapter filter for the latest eligible input. Restart the server and refresh the browser after updating the notebook.</p>'''),
        page('Topics and source versions', picture('scope','All Topics combines the latest graph from each input topic.')+'''
<p><b>Topic</b> means an input document or chapter. <b>Source graph version</b> means one saved pipeline run for that input. Its run name and ID identify the exact graph behind learning results.</p>
<p><b>All Topics</b> includes one latest version per input topic. It shows an aggregate plus topic breakdowns. Exactly matching relationships count once: here two source occurrences represent one unique relationship.</p>
<p>Matching requires the same recorded endpoint meaning, direction and relation fields, including conditions. No synonym matching is inferred. Topic rows may overlap: do not add them to calculate the aggregate.</p>
<p>Choose a specific topic to select an older version. History retains earlier quizzes and labels them. Resuming a quiz explicitly selects its original source version.</p>'''+picture('setup','Practice always uses one identified source version.')),
        page('Start, answer and resume a quiz', picture('answer','A hint makes this correct demonstration answer assisted, even with an answer score of 100%.')+'''
<ol><li>Choose a student, quiz source, and optionally a starting concept.</li><li>Click <b>Start quiz</b> and confirm the student. Questions skip green facts and prioritize gaps. Yellow becomes green only after a full-relationship demonstration without help.</li><li>Type and submit an answer. A hint or reveal marks later answers as assisted. A correct short answer can score 100% while the full relationship stays yellow.</li><li>Use <b>Next question</b>. Enable review to revisit independently known facts.</li></ol>
<p>Each quiz belongs to one student and source run. In All Topics, exactly matching evidence avoids retesting known overlapping facts. A quiz never mixes source versions.</p>
<p>Saved quizzes offer <b>Resume</b>. Pending grading keeps the submitted answer and original request ID; use <b>Retry pending request</b> after the model recovers. Green stays earned across quizzes and restarts. Failed question drafts offer Try another concept. Failed hints show no answer; Reveal can use a display-checked saved answer, labelled Saved validated answer. Help errors do not erase grades. Unsubmitted text is not a durable answer.</p>'''),
        page('Read and explore the graph', picture('graph','Circles are concepts; arrows are directed relationships. Select an arrow to inspect its saved record and evidence.')+'''
<p>Drag, zoom, search, or use <b>Fit graph</b> and <b>Show all</b>. Distance and position are layout choices, not scores.</p>
<p>Student colors: <b>green</b> independent; <b>amber</b> partial or assisted; <b>red</b> incorrect or not demonstrated; <b>gray</b> unassessed. A concept circle is green only when all its connected facts are green. Mixed known and unknown links make it yellow. Counts distinguish states sharing a color.</p>
<p>In source exploration, blue means document and orange means background. In class view, brighter and thicker relationships mean more students independently know them, using the full roster.</p>'''+picture('comparison','Choose a specific topic and Explore / compare statements for temporary model matching.')+'''
<p>Comparison does not grade a student. All Topics retains every relationship's source records; open one source for statement comparison.</p>'''),
        page('Read the class overview', picture('class','Class metrics and common patterns. Unassessed material is not a difficulty.')+picture('students','Cards show miniature learning graphs and scope-wide metrics.')+'''
<p>Coverage averages include every roster member. Answer scores include only students with measurements; <b>n</b> shows the sample size. Each student has equal weight.</p>
<p>Strengths show independent evidence. Difficulties separate partial, incorrect and not-demonstrated judgments from assisted successes. These are observed patterns, not diagnoses.</p>
<p>Click a card for details within Class Overview. <b>Back to Class</b> returns; <b>Quiz This Student</b> carries the context to Quiz. Miniatures preview up to 30 concepts and 60 links; metrics use the full scope.</p>'''),
        page('Review results and correct grading', picture('history','History labels source versions and whether they contribute to current metrics.')+picture('grading','Recorded answers retain the original judgment, assistance status, evidence and corrections.')+'''
<p>Use <b>Inspect answers</b>. Expand expected-answer and evidence details, choose a corrected mark per requested fact, write feedback and a reason, then save.</p>
<p>Question grading and graph matching are separate. If matching is unresolved, the question grade is saved and relationship progress stays unchanged. Use <b>Retry graph matching</b> here; it does not create another grade.</p>
<p>Original grading and corrections remain stored. Corrections respect the assessed scope: a component question cannot award full mastery, and assisted answers remain assisted.</p>
<p>Older sessions remain available. Independent mastery transfers across exact, unambiguous semantic matches with provenance. Answer scores are not copied. Correcting all invalid supporting awards can revoke green.</p>'''),
        page('Understand learning metrics', picture('advanced','Expandable metrics separate assistance, connectivity, fragmentation and concentration.')+'''
<table><tr><th>Metric</th><th>Meaning and denominator</th></tr>
<tr><td>Known without help</td><td>Independently correct unique relationships / all unique relationships in scope.</td></tr>
<tr><td>Checked</td><td>Resolved relationship assessments / all unique relationships. Unresolved matching does not add coverage.</td></tr>
<tr><td>Answer performance</td><td>Mean latest answer per distinct session/question. Revisions count once. Assisted scores are also reported separately.</td></tr>
<tr><td>Connected understanding</td><td>Mastered concepts in the largest undirected mastered component / all mastered endpoints.</td></tr>
<tr><td>Concentration</td><td>Shares of independently known facts across graph communities (HHI). Near 1 means concentrated.</td></tr></table>
<p>Coverage retains independently earned green across later attempts. Scores still reflect each answer; professor corrections can invalidate supporting credit. Different questions can test the same fact; answer performance and unique-fact coverage measure different things.</p>
<p>Expand <b>Advanced learning metrics and progress</b> for source-specific trends, exact values and graph communities. Separate versions are never joined into a fabricated trend. Definitions remain available at the bottom.</p>'''),
        page('Inspect a saved pipeline run', picture('results','Missing timings or background validation measurements say Unavailable.')+picture('quality','This demonstration has no reconstruction score; none is invented.')+'''
<p><b>Run Insights</b> shows the selected saved graph, extraction and validation records, and available quality measurements. All Topics adds aggregate graph counts and a source breakdown with per-run inspection.</p>
<p>Expand <b>Review background facts for quizzes</b> to inspect generated claims and record an approval or revocation with a reason. Approval is specific to this graph version. Unapproved background facts cannot be used in quizzes.</p>
<p>Reconstruction compares rebuilt text with the original. It measures pipeline fidelity, not student learning or independently verified truth. Missing measurements stay unavailable.</p>
<p>Expand validation records, original/reconstructed text or advanced diagnostics when needed. Timings are duration, not quality. No mixed-version quality score is fabricated.</p>
<p>Records persist in <code>outputs/professor/students.sqlite3</code>. Viewing saved graphs needs no extraction. New quizzes, grading and statement matching need the configured model service. This is a local professor-operated app.</p>
<pre>python -m pipeline.explorer "PATH_TO_RUN_DIRECTORY"
python -m pipeline.professor --runs-root outputs/runs --no-open</pre>'''),
    ]



def make_document(sections):
    links = ''.join(f'<a href="#page-{i}">{i+1}. {html.escape(title)}</a>' for i, (title, _) in enumerate(sections))
    pages = ''.join(body.replace('<section>', f'<section id="page-{i}">', 1) for i, (_, body) in enumerate(sections))
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Interactive Graph — Simple User Guide</title><style>
@page{size:A4;margin:13mm 14mm 18mm}
*{box-sizing:border-box}body{margin:0;background:#e8edf4;color:#17243a;font:14px/1.5 'Segoe UI',Arial,sans-serif}
nav{max-width:820px;margin:24px auto;padding:22px;background:white;border-radius:10px;display:grid;grid-template-columns:1fr 1fr;gap:10px}a{color:#235fa5}
section{background:white;max-width:820px;margin:20px auto;padding:35px 40px;break-after:page;page-break-after:always}section:last-child{break-after:auto}
h1{font-size:29px;line-height:1.15;letter-spacing:-.7px;margin:7px 0 10px}h2{font-size:17px;margin:22px 0 7px}p{margin:10px 0}.kicker{font-size:10px;font-weight:700;letter-spacing:1.5px;color:#356d9f}.lead{font-size:16px;color:#53647a;margin-bottom:18px}
figure{margin:14px 0;break-inside:avoid}img{display:block;width:auto;max-width:100%;max-height:390px;object-fit:contain;object-position:left top;border:1px solid #d7dfe9;border-radius:5px}figure.large img{max-height:500px}figure.small-image img{max-height:230px;width:auto;max-width:100%}figcaption{font-size:11px;color:#5d6c80;margin:6px 0}
table{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0}th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid #dce3ec}th{background:#eaf1f9;color:#244c72}td:first-child{font-weight:600;width:29%}li{margin:6px 0}ul,ol{padding-left:22px}
.callout,.note{padding:13px 16px;border-left:4px solid #3980b8;background:#edf5fc;margin:17px 0}.note{border-color:#c18c32;background:#fff7e7;font-size:13px}.small{font-size:11px;color:#58677b}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:12px;background:#eef2f7;border:1px solid #dbe3ed;font:12px/1.55 Consolas,monospace}
@media print{body{background:white;font-size:12px;line-height:1.45}nav{display:none}section{max-width:none;margin:0;padding:0}h1{font-size:25px}.lead{font-size:14px}h2{font-size:15px}img{max-height:345px}figure.large img{max-height:460px}figure.small-image img{max-height:190px}table{font-size:11px}th,td{padding:6px 8px}.callout,.note{margin:12px 0;padding:10px 13px}pre{font-size:11px}p{margin:8px 0}li{margin:4px 0}}
@media(max-width:700px){section{padding:24px 18px;margin:10px}nav{margin:10px;grid-template-columns:1fr}h1{font-size:25px}}
@media screen{figure img{cursor:zoom-in}figure img:focus{outline:3px solid #3980b8}figure.expanded img{max-height:none;cursor:zoom-out}figure.expanded{overflow:auto}}
</style></head><body><nav aria-label="Guide contents">''' + links + '</nav>' + pages + '''<script>for(const figure of document.querySelectorAll('figure')){const img=figure.querySelector('img');img.tabIndex=0;img.title='Click or press Enter to enlarge this screenshot';const toggle=()=>figure.classList.toggle('expanded');img.onclick=toggle;img.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();toggle();}};}</script></body></html>'''


if __name__ == '__main__':
    build()
