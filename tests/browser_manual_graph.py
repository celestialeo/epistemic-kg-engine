"""Real-browser editing, original viewing, audit, reversion, and server restart."""
import asyncio
from pathlib import Path
import sys
import uuid

from playwright.sync_api import sync_playwright, expect
from pipeline.explorer import create_app
from pipeline.student_store import StudentStore
from pipeline.submission import start_server, stop_server
import pipeline.submission as notebook_server
from tests.test_professor import write_run, TeachingModels


def main():
    root = Path('outputs/professor_checks') / ('manual_' + uuid.uuid4().hex[:10])
    root.mkdir(parents=True)
    run = write_run(root / 'runs')
    original = (run / 'artifacts/graph.json').read_bytes()
    store = StudentStore(root / 'students.sqlite3')
    errors = []

    def serve():
        policy = asyncio.get_event_loop_policy()
        try:
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            url = start_server(create_app([], professor_store=store, runs_root=root / 'runs',
                                          model_factory=lambda s, t: TeachingModels()))['url']
            notebook_server._server_state[0].config.timeout_graceful_shutdown = 2
            return url
        finally:
            asyncio.set_event_loop_policy(policy)

    url = serve()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url + '/professor?view=insights')
            expect(page.locator('#manual-context')).to_contain_text('revision 0')
            expect(page.locator('#view-original')).to_be_hidden()
            page.locator('#professor-identity').fill('Professor Example')
            page.locator('#concept-label').fill('Cloud')
            page.locator('#concept-definition').fill('A collection of water droplets')
            page.locator('#save-concept').click()
            expect(page.locator('#manual-context')).to_contain_text('revision 1')
            page.locator('#relationship-source').select_option(label='water')
            page.locator('#relationship-target').select_option(label='Cloud')
            page.locator('#relationship-label').fill('forms')
            page.locator('#relationship-definition').fill('Combines into droplets')
            page.locator('#save-relationship').click()
            expect(page.locator('#manual-context')).to_contain_text('3 concepts · 2 relationships')
            page.locator('#edit-relationship').select_option(label='water → forms → Cloud')
            page.locator('#relationship-definition').fill('Condenses into airborne droplets')
            page.locator('#save-relationship').click()
            expect(page.locator('#manual-context')).to_contain_text('revision 3')
            page.locator('#edit-concept').select_option(label='Cloud')
            page.locator('#concept-label').fill('Cloud droplets')
            page.locator('#save-concept').click()
            expect(page.locator('#manual-context')).to_contain_text('revision 4')
            page.locator('#view-original').click()
            expect(page.locator('#graph-title')).to_have_text('Original generated graph')
            expect(page.locator('#manual-forms')).to_be_hidden()
            frame = page.frame_locator('#graph')
            expect(frame.get_by_text('Original generated graph — read-only. Manual edits remain saved.')).to_be_visible()
            expect(frame.locator('body')).not_to_contain_text('Cloud droplets')
            page.locator('#view-original').click()
            expect(page.locator('#manual-forms')).to_be_visible()
            expect(page.locator('#edit-concept option')).to_contain_text(['Add a new concept', 'water', 'soil', 'Cloud droplets'])
            page.locator('#view-manual-changes').click()
            expect(page.locator('#manual-change-list')).to_contain_text('Professor Example (self reported)')
            page.locator('#manual-change-list details').first.locator('summary').click()
            expect(page.locator('#manual-change-list details').first).to_contain_text('Before')
            expect(page.locator('#manual-change-list details').first).to_contain_text('After')
            page.on('dialog', lambda dialog: dialog.accept())
            page.locator('#edit-concept').select_option(label='Cloud droplets')
            page.locator('#delete-concept').click()
            expect(page.locator('#manual-context')).to_contain_text('2 concepts · 1 relationships')
            page.get_by_role('button', name='Revert change 5', exact=True).click()
            expect(page.locator('#manual-context')).to_contain_text('revision 6')
            expect(page.locator('#manual-change-list')).to_contain_text('revert change 5')
            page.locator('#edit-relationship').select_option(label='water → forms → Cloud droplets')
            page.locator('#delete-relationship').click()
            expect(page.locator('#manual-context')).to_contain_text('3 concepts · 1 relationships')
            page.get_by_role('button', name='Revert change 7', exact=True).click()
            expect(page.locator('#manual-context')).to_contain_text('3 concepts · 2 relationships')
            page.reload()
            expect(page.locator('#manual-context')).to_contain_text('revision 8')
            page.locator('#manual-editor').screenshot(path=str(root / 'editor.png'))
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('#manual-editor').scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
            page.screenshot(path=str(root / 'mobile.png'))
            page.close()
            stop_server()
            url = serve()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url + '/professor?view=insights')
            expect(page.locator('#manual-context')).to_contain_text('revision 8')
            expect(page.locator('#edit-concept option')).to_contain_text(['Add a new concept', 'water', 'soil', 'Cloud droplets'])
            assert (run / 'artifacts/graph.json').read_bytes() == original
            assert not errors, errors
            browser.close()
        print('Browser editing, connections, original viewing, audit, reversion, reload, restart, and mobile checks passed.')
        print('Screenshots:', root)
    finally:
        stop_server()


if __name__ == '__main__':
    main()
