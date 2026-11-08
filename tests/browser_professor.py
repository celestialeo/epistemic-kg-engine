"""Optional real-browser flow: python -m tests.browser_professor (requires Playwright + Chrome)."""
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
    root = Path("outputs/professor_checks") / ("browser_" + uuid.uuid4().hex[:10])
    root.mkdir(parents=True)
    write_run(root / "runs")
    write_run(root / "runs", topic="unassessed-topic")
    models = TeachingModels()
    app = create_app([], professor_store=StudentStore(root / "students.sqlite3"), runs_root=root / "runs",
                     model_factory=lambda s, t: models)
    errors = []
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(128)
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        thread = threading.Thread(target=server.run, kwargs={"sockets":[sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Test server did not start")
            time.sleep(.05)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="chrome", headless=True)
                page = browser.new_page(viewport={"width":1440,"height":1100})
                page.on("pageerror", lambda error: errors.append(str(error)))
                topics = page.request.get(url + "/api/professor/catalog").json()["topics"]
                selected = next(t for t in topics if t["title"] == "water")
                page.goto(url + "/professor?run=" + selected["id"])
                expect(page.locator("#topic")).to_have_value(selected["id"])
                expect(page.locator("#graph-details")).to_be_visible()
                assert page.locator("body").evaluate("node => getComputedStyle(node).colorScheme") == "dark"
                expect(page.frame_locator("#graph").locator("#search")).to_be_visible()
                page.get_by_role("button", name="Start quiz", exact=True).click()
                expect(page.locator("#quiz-student-note")).to_contain_text("No students have been created")
                expect(page.get_by_role("button", name="Begin quiz", exact=True)).to_be_disabled()
                page.get_by_role("button", name="Cancel", exact=True).click()
                assert not StudentStore(root / "students.sqlite3").history()
                page.get_by_label("Add a student", exact=True).fill("Ada Lovelace")
                page.get_by_role("button", name="Add student", exact=True).click()
                expect(page.locator("#view-title")).to_have_text("Ada Lovelace")
                page.get_by_label("Add a student", exact=True).fill("Grace Hopper")
                page.get_by_role("button", name="Add student", exact=True).click()
                expect(page.locator("#view-title")).to_have_text("Grace Hopper")
                page.locator('#roster').get_by_role("button", name="Ada Lovelace", exact=True).click()
                expect(page.locator("#view-title")).to_have_text("Ada Lovelace")
                page.get_by_label("Input topic / saved run", exact=True).select_option(label="water")
                page.locator('#review-mode').check()
                page.locator('details.card').evaluate('node=>node.open=true')
                expect(page.locator("#recommendation")).to_contain_text("not yet covered")
                page.get_by_role("button", name="Start quiz", exact=True).click()
                expect(page.get_by_role("dialog")).to_be_visible()
                expect(page.get_by_label("Student taking this quiz", exact=True)).to_have_value("")
                expect(page.get_by_role("button", name="Begin quiz", exact=True)).to_be_disabled()
                page.get_by_role("button", name="Cancel", exact=True).click()
                assert not StudentStore(root / "students.sqlite3").history()
                page.get_by_role("button", name="Start quiz", exact=True).click()
                page.get_by_label("Student taking this quiz", exact=True).select_option(label="Ada Lovelace")
                page.get_by_role("button", name="Begin quiz", exact=True).click()
                expect(page.locator("#quiz-progress")).to_contain_text("Question 1")
                expect(page.locator("#quiz-run")).to_contain_text("Student: Ada Lovelace")
                for number in range(1,6):
                    page.get_by_label("Student’s answer", exact=True).fill("Water enters soil.")
                    page.get_by_role("button", name="Submit answer", exact=True).click()
                    expect(page.locator("#feedback")).to_contain_text("100%")
                    if number < 5:
                        page.get_by_role("button", name="Next question", exact=True).click()
                        expect(page.locator("#quiz-progress")).to_contain_text(f"Question {number+1}")
                expect(page.locator("#quiz-complete")).to_be_visible()
                page.get_by_role("button", name="Inspect answers", exact=True).click()
                expect(page.locator(".answer-card")).to_have_count(5)
                first = page.locator(".answer-card").first
                first.locator("select").select_option("related")
                first.get_by_label("Feedback for the student").fill("Good start; explain the movement more fully.")
                first.get_by_label("Reason for this override (saved in audit history)").fill("Professor assessed the explanation as incomplete.")
                first.get_by_role("button", name="Save override").click()
                expect(page.locator("#status")).to_contain_text("Override saved")
                expect(page.locator(".answer-card").first).to_contain_text("Score: 50%")
                expect(page.locator("#topic-analytics")).to_contain_text("90%")
                page.reload()
                expect(page.locator("#view-title")).to_have_text("Ada Lovelace")
                expect(page.locator("#topic-analytics")).to_contain_text("90%")
                expect(page.locator("#history")).to_contain_text("5 questions")
                page.get_by_role("button", name="Class overview", exact=True).click()
                expect(page.locator("#topic-analytics")).to_contain_text("1 assessed · 1 unassessed students")
                expect(page.locator("#topic-analytics")).to_contain_text("Unassessed")
                page.locator('details.card').evaluate('node=>node.open=true')
                page.get_by_label("Input topic / saved run", exact=True).select_option(value=next(t["id"] for t in topics if t["id"] != selected["id"]))
                expect(page.locator('#start')).to_be_enabled()
                graph_src = page.locator("#graph").get_attribute("src")
                page.locator("#trends a").first.click()
                expect(page.locator("#graph-return")).to_be_visible()
                assert len(browser.contexts[0].pages) == 1, "Graph history opened another tab"
                page.locator("#graph-return").click()
                expect(page.locator("#graph")).to_have_attribute("src", graph_src)
                page.get_by_label("Input topic / saved run", exact=True).select_option(label="water")
                page.screenshot(path=str(root / "class-desktop.png"), full_page=True)
                page.locator('#roster').get_by_role("button", name="Ada Lovelace", exact=True).click()
                expect(page.locator("#view-title")).to_have_text("Ada Lovelace")
                page.get_by_role("button", name="Start quiz", exact=True).click()
                page.get_by_label("Student taking this quiz", exact=True).select_option(label="Grace Hopper")
                page.get_by_role("button", name="Begin quiz", exact=True).click()
                expect(page.locator("#quiz-progress")).to_contain_text("Question 1")
                expect(page.locator("#view-title")).to_have_text("Grace Hopper")
                expect(page.locator("#quiz-run")).to_contain_text("Student: Grace Hopper")
                saved = StudentStore(root / "students.sqlite3")
                owners = {s["name"]: s["id"] for s in saved.students()}
                assert len(saved.history(owners["Ada Lovelace"])) == 1
                assert len(saved.history(owners["Grace Hopper"])) == 1
                assert saved.history(owners["Ada Lovelace"])[0]["answer_count"] == 5
                page.reload()
                expect(page.locator("#question")).not_to_be_empty()
                expect(page.locator("#quiz-progress")).to_contain_text("Question 1")
                expect(page.locator("#quiz-run")).to_contain_text("Student: Grace Hopper")
                frame = page.frame_locator("#graph")
                expect(frame.locator("#search")).to_be_visible()
                frame.locator("#search").fill("water")
                expect(frame.locator("#status")).to_contain_text("nodes")
                expect(frame.locator("#search")).to_be_visible()
                assert frame.locator(".run-meta a").is_hidden(), "Embedded graph includes duplicate navigation"
                expect(page.locator("#graph")).to_have_css("height", frame.locator("body").evaluate("node => Math.ceil(node.getBoundingClientRect().height) + 'px'"))
                page.screenshot(path=str(root / "student-desktop.png"), full_page=True)
                page.set_viewport_size({"width":390,"height":844})
                page.screenshot(path=str(root / "student-mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile horizontal overflow"
                assert not errors, errors
                browser.close()
            result = dict(passed=True, browser="Chrome", flow="roster, topics, full quiz, override, analytics, reload, graph, mobile",
                          javascript_errors=errors, model_calls=len(models.calls), artifacts=str(root))
            (root / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result))
        finally:
            server.should_exit = True
            thread.join(timeout=10)


if __name__ == "__main__":
    main()
