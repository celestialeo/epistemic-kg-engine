"""Verify a completed saved graph in Chrome with an isolated professor database."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect, TimeoutError as BrowserTimeout
from pipeline.explorer import create_app, load_snapshot
from pipeline.graph_quality import require_quality
from pipeline.professor import run_identity, topic_identity
from pipeline.student_store import StudentStore
from pipeline.submission import start_server, stop_server
import pipeline.submission as server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.output or Path('outputs/professor_checks') / ('graph_quality_' + uuid.uuid4().hex[:10])
    root.mkdir(parents=True, exist_ok=True)
    snapshot = load_snapshot(args.run)
    graph = snapshot.graph
    quality_required = snapshot.manifest.get('graph_quality_required', False)
    require_quality(graph, required=quality_required)
    source = snapshot.manifest.get('source_run')
    source_unchanged = None
    if source:
        digest = hashlib.sha256((Path(source)/'artifacts/graph.json').read_bytes()).hexdigest()
        assert digest == snapshot.manifest['source_graph_sha256'], 'Source graph changed'
        source_unchanged = True
    elif snapshot.manifest.get('config', {}).get('input'):
        input_path = Path(snapshot.manifest['config']['input'])
        assert input_path.read_bytes().decode('utf-8-sig') == (args.run/'input.txt').read_bytes().decode('utf-8'), 'Source text changed'
        source_unchanged = True
    store = StudentStore(root/'students.sqlite3')
    run_id = run_identity(snapshot)
    topic, title = topic_identity(snapshot)
    store.register_run(run_id, topic, title, snapshot)
    policy = asyncio.get_event_loop_policy()
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        def no_inference(*args, **kwargs):
            raise AssertionError('Opening a reviewed graph must not repeat inference')
        url = start_server(create_app([args.run], professor_store=store, runs_root=root/'empty',
                                      model_factory=no_inference))['url']
        server._server_state[0].config.timeout_graceful_shutdown = 2
    finally:
        asyncio.set_event_loop_policy(policy)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width':1440, 'height':1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url+'/professor?run='+run_id)
            expect(page.locator('#scope-topic')).to_have_value(topic)
            material = page.request.get(url+'/api/professor/runs/'+run_id+'/quiz-material').json()
            results = page.request.get(url+'/api/professor/runs/'+run_id+'/results').json()
            if quality_required:
                assert results['validation_records']['graph_quality']['status'] == 'passed'
            elif snapshot.manifest.get('graph_acceptance_policy') == 'document_review_and_background_debate':
                assert results['graph_quality_status'] == 'not_run'
                assert results['validation_records']['graph_quality'] is None
            assert results['accepted'] == sum(e['origin']=='background' for e in graph['edges'])
            assert len(material['facts']) == sum(e['origin']=='background' for e in graph['edges'])
            assert all(not f['eligible'] for f in material['facts'] if f['fact']['origin']=='background')
            page.goto(url+'/professor/graph/'+run_id)
            expect(page.locator('#nodes .node')).to_have_count(len(graph['nodes']))
            expect(page.locator('#edges .edge')).to_have_count(len(graph['edges']))
            captions = page.locator('#edges .edge-caption text').all_text_contents()
            assert captions == [e['label'].replace('_', ' ') + (' ['+e['modality']+']' if e.get('modality') else '') for e in graph['edges']]
            page.wait_for_function('ticks >= UI_SETTINGS.graph_simulation_ticks')
            page.locator('#nodes .node circle').first.click()
            expect(page.locator('#details')).not_to_be_empty()
            nodes = {n['id']: n for n in graph['nodes']}
            checked_edges = []
            obstructed_labels = []
            page.screenshot(path=str(root/'overview-before-filter.png'), full_page=True)
            expect(page.locator('#relationship-list button')).to_have_count(len(graph['edges']))
            list_ids = page.locator('#relationship-list button').evaluate_all('(buttons) => buttons.map(b => b.dataset.edgeId)')
            for index, edge in enumerate(graph['edges']):
                try:
                    page.locator('#edges .edge-caption text').nth(index).click(timeout=3000)
                except BrowserTimeout:
                    obstructed_labels.append(edge['id'])
                # A readable, keyboard-accessible selection must always work.
                page.locator('#relationship-list button').nth(list_ids.index(edge['id'])).click()
                expect(page.locator('#details')).to_contain_text(edge['definition'])
                for field in ('conditions', 'purpose', 'timing'):
                    if edge.get(field):
                        expect(page.locator('#details')).to_contain_text(edge[field])
                for participant in edge.get('participants', []):
                    expect(page.locator('#details')).to_contain_text(nodes[participant['node']]['label'])
                checked_edges.append(edge['id'])
            page.locator('#reset').click()
            page.wait_for_function('ticks >= UI_SETTINGS.graph_simulation_ticks')
            page.screenshot(path=str(root/'reviewed-graph.png'), full_page=True)
            page.reload()
            expect(page.locator('#nodes .node')).to_have_count(len(graph['nodes']))
            page.set_viewport_size({'width':390, 'height':844})
            page.wait_for_function('ticks >= UI_SETTINGS.graph_simulation_ticks')
            page.locator('#relationship-list button').first.click()
            expect(page.locator('#details')).not_to_be_empty()
            page.screenshot(path=str(root/'reviewed-graph-mobile.png'), full_page=True)
            assert not errors, errors
            browser.close()
        report = dict(passed=True, run=str(args.run), nodes=len(graph['nodes']), edges=len(graph['edges']),
                      labels=sorted({e['label'] for e in graph['edges']}), javascript_errors=errors,
                      source_unchanged=source_unchanged, background_approval_required=True,
                      graph_acceptance_policy=snapshot.manifest.get('graph_acceptance_policy'),
                      extra_graph_review_required=quality_required,
                      checked_edges=checked_edges, edge_selection='unfiltered graph labels and relationship list',
                      obstructed_labels=obstructed_labels, mobile_relationship_selection=True)
        (root/'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(dict(report, artifacts=str(root))))
    finally:
        try:
            stop_server()
        except RuntimeError:
            if server._server_state:
                server._server_state[0].force_exit=True
            stop_server()


if __name__ == '__main__':
    main()
