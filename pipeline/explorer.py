"""Local, read-only browser console for completed knowledge graphs."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import html
import json
import os
from pathlib import Path
import socket
import threading
from urllib.parse import urlsplit
from typing import Literal
import uuid
import webbrowser

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .graph_match import GraphMatcher
from .graph_view import render_graph, canonicalize_graph
from .models import Models
from .identity import concept_key
from .quiz import QuizSession
from .trace import Trace

ROOT = Path(__file__).resolve().parents[1]


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1500)
    page_id: uuid.UUID | None = None
    query_id: uuid.UUID | None = None

    @field_validator("text")
    @classmethod
    def nonempty(cls, text):
        if not text.strip():
            raise ValueError("Enter some text to match")
        return text.strip()


class Interaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=1)
    timestamp: str = Field(max_length=64)
    action: Literal["page_open", "page_hide", "page_show", "visibility", "select",
                    "search", "query_edit", "background", "labels", "focus", "reset",
                    "fit", "drag", "pan", "zoom", "resize", "scroll", "navigate",
                    "query_submit", "query_clear", "query_displayed", "query_error",
                    "quiz_edit", "quiz_exit", "quiz_resume"]
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def bounded_details(cls, value):
        if len(json.dumps(value, allow_nan=False).encode("utf-8")) > 32000:
            raise ValueError("Interaction details too large")
        return value


class InteractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: uuid.UUID
    events: list[Interaction] = Field(min_length=1, max_length=50)


class QuizCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "answer", "hint", "reveal", "next", "continue"]
    request_id: uuid.UUID
    page_id: uuid.UUID
    quiz_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    text: str = Field(default="", max_length=1500)


@dataclass
class Snapshot:
    directory: Path
    graph: dict
    manifest: dict
    quiz_aliases: dict = field(default_factory=dict)


def load_snapshot(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") not in {"completed", "completed_with_issues"}:
        raise ValueError(f"Explorer requires a completed run: {directory}")
    graph = json.loads((directory / "artifacts/graph.json").read_text(encoding="utf-8"))
    normalized = canonicalize_graph(graph)
    # Keep declared aliases as quiz metadata; minimal displayed nodes stay minimal.
    by_name = {node["label"]: node["id"] for node in normalized["nodes"]}
    aliases = {}
    for node in graph["nodes"]:
        name = node.get("label") or node["name"]
        identifier = by_name[concept_key(name)]
        aliases.setdefault(identifier, set()).update(
            value for value in [name, *(node.get("aliases") or [])] if isinstance(value, str) and value.strip())
    return Snapshot(directory, normalized, manifest, {k: sorted(v) for k, v in aliases.items()})


def make_models(snapshot, trace, overrides=None):
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
    config = {**snapshot.manifest.get("config", {}), **(overrides or {})}
    host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    if urlsplit(host).username or urlsplit(host).password:
        raise ValueError("Do not embed credentials in OLLAMA_HOST")
    models = Models(trace, config.get("model", "qwen3.5:9b"),
                    config.get("embedding_model", "nomic-embed-text"), host,
                    timeout=config.get("model_timeout", 600), think=config.get("think", False),
                    context_tokens=config.get("context_tokens", 8192),
                    max_output_tokens=config.get("max_output_tokens", 4096))
    models.preflight()
    return models


def explorer_page(snapshot, run_index, run_count):
    page = render_graph(snapshot.graph)
    score = snapshot.manifest.get("reconstruction_score")
    score_text = f"{score:.2f} / 100" if isinstance(score, (int, float)) else "unresolved"
    status = html.escape(snapshot.manifest["status"].replace("_", " "))
    controls = f'''<section id="explorer" data-endpoint="/runs/{run_index}/match" data-events-endpoint="/runs/{run_index}/events">
<h2 id="explorer-title">Ask this graph</h2>
<p class="query-intro">Follow an idea. Discover how it connects.</p>
<div class="study-controls"><button id="quiz-start" type="button">Start a 5-question quiz</button>
<button id="quiz-resume" type="button" hidden>Return to quiz</button>
<button id="quiz-exit" type="button" hidden>Explore freely</button>
<button id="quiz-retry" type="button" hidden>Retry quiz request</button></div>
<p id="quiz-status" role="status" aria-live="polite"></p>
<section id="quiz-panel" data-endpoint="/runs/{run_index}/quiz" hidden aria-label="Graph quiz">
<p id="quiz-progress" class="muted"></p><h3 id="quiz-question"></h3>
<form id="quiz-form"><label class="query-label" for="quiz-answer">Your answer</label>
<textarea id="quiz-answer" maxlength="1500" rows="3" required placeholder="Explain in your own words..."></textarea>
<div class="quiz-actions"><button id="quiz-submit" type="submit">Map my answer</button>
<button id="quiz-hint" type="button">Hint</button><button id="quiz-reveal" type="button">Reveal</button>
<button id="quiz-next" type="button" disabled>Next question</button></div></form>
<p class="muted">Answer in complete statements and name both things you are describing.</p>
<p id="quiz-feedback" role="status"></p><div id="quiz-help" hidden></div>
<button id="quiz-examiner-toggle" type="button" aria-expanded="false">Examiner view</button>
<section id="quiz-examiner" hidden><h3>Examiner details</h3><pre id="quiz-examiner-content"></pre></section>
<section id="quiz-summary" hidden><h3>Coverage after 5 questions</h3><p id="quiz-coverage"></p>
<p id="quiz-breakdown" class="muted"></p><button id="quiz-continue" type="button">Continue with 5 more questions</button></section>
</section>
<form id="query-form"><label class="query-label" for="query-text">Enter a concept, statement, or question</label>
<div class="query-composer"><textarea id="query-text" maxlength="1500" rows="2" required
aria-describedby="query-status match-help" placeholder="What would you like to explore?"></textarea>
<div class="query-controls"><span class="query-shortcut">Ctrl / ⌘ + Enter to match</span>
<button id="query-clear" type="button">Clear highlights</button>
<button id="query-submit" type="submit">Match graph <span aria-hidden="true">↗</span></button></div></div></form>
<p id="query-status" role="status" aria-live="polite">Ready to explore. Matching may take a few minutes on larger graphs.</p>
<p id="logging-status" class="muted" role="status">Saving interactions to this run.</p>
<div class="match-legend" aria-label="Match colors"><span class="match-key">Matched</span><span class="related-key" id="related-legend">Related</span><span class="conflict-key">Contradicted</span></div>
<p id="match-help" class="muted">A matching concept identifies a reference; it does not confirm your whole statement.</p>
<div class="run-meta"><span>Run: {status}</span><span>Reconstruction: {score_text}</span>
<a href="/">{'Choose a run' if run_count > 1 else 'Explorer home'}</a></div>
</section>'''
    page = page.replace("</header>", controls + "</header>", 1)
    page = page.replace("<aside>", '<aside><section id="query-results" aria-label="Matching results"></section>', 1)
    page = page.replace("</style>", "</style><link rel=\"stylesheet\" href=\"/explorer.css\">", 1)
    return page.replace("</html>", '<script src="/explorer.js"></script><script src="/quiz.js"></script></html>')


def create_app(directories, *, model_factory=make_models):
    snapshots = [load_snapshot(directory) for directory in directories]
    if not snapshots:
        raise ValueError("Select at least one completed run")
    sessions = {}
    matchers = {}
    quizzes = {}
    quiz_requests = {}
    received = {}
    session_lock = threading.Lock()
    lock = threading.Lock()

    def trace_at(index):
        snapshot = snapshot_at(index)
        with session_lock:
            if index not in sessions:
                session_id = "explorer_" + uuid.uuid4().hex
                trace = Trace(snapshot.directory / "explorer_sessions" / session_id, session_id)
                trace.stage = "explorer"
                trace.emit("explorer.started", source_run=str(snapshot.directory),
                           source_run_id=snapshot.graph.get("run_id"))
                sessions[index] = trace
            return sessions[index]

    def check_origin(request):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Use the explorer's local page to submit events or queries")

    @asynccontextmanager
    async def lifespan(app):
        if getattr(app.state, "open_url", None):
            asyncio.get_running_loop().call_later(.3, webbrowser.open, app.state.open_url)
        try:
            yield
        finally:
            for trace in sessions.values():
                trace.emit("explorer.closed")
                trace.close()

    app = FastAPI(title="Knowledge graph explorer", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def snapshot_at(index):
        if not 0 <= index < len(snapshots):
            raise HTTPException(404, "Run not found")
        return snapshots[index]

    def matcher_at(index):
        if index not in matchers:
            snapshot = snapshot_at(index)
            matchers[index] = GraphMatcher(snapshot.graph, model_factory(snapshot, trace_at(index)),
                                          quiz_aliases=snapshot.quiz_aliases)
        return matchers[index]

    @app.get("/", response_class=HTMLResponse)
    def home():
        if len(snapshots) == 1:
            return explorer_page(snapshots[0], 0, 1)
        links = "".join(f'<li><a href="/runs/{i}">{html.escape(s.directory.name)}</a></li>'
                        for i, s in enumerate(snapshots))
        return '<!doctype html><meta charset="utf-8"><title>Graph explorer</title><h1>Choose a graph</h1><ul>' + links + '</ul>'

    @app.get("/runs/{index}", response_class=HTMLResponse)
    def view(index: int):
        return explorer_page(snapshot_at(index), index, len(snapshots))

    @app.get("/explorer.js")
    def script():
        return Response(Path(__file__).with_name("explorer.js").read_text(encoding="utf-8"),
                        media_type="application/javascript")

    @app.get("/explorer.css")
    def style():
        return Response(Path(__file__).with_name("explorer.css").read_text(encoding="utf-8"), media_type="text/css")

    @app.get("/quiz.js")
    def quiz_script():
        return Response(Path(__file__).with_name("quiz.js").read_text(encoding="utf-8"),
                        media_type="application/javascript")

    @app.get("/runs/{index}/quiz/{quiz_id}")
    def quiz_state(index: int, quiz_id: uuid.UUID):
        snapshot_at(index)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "An answer is being evaluated. Please wait.")
        try:
            session = quizzes.get((index, str(quiz_id)))
            if session is None:
                raise HTTPException(404, "Quiz is not active on this server. Start a new session.")
            return session.public()
        finally:
            lock.release()

    @app.get("/runs/{index}/quiz/{quiz_id}/examiner")
    def quiz_examiner(index: int, quiz_id: uuid.UUID):
        snapshot_at(index)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "A quiz request is running. Please wait.")
        try:
            session = quizzes.get((index, str(quiz_id)))
            if session is None:
                raise HTTPException(404, "Quiz is not active on this server")
            trace_at(index).emit("quiz.examiner_view", quiz_id=str(quiz_id))
            return session.examiner_view()
        finally:
            lock.release()

    @app.post("/runs/{index}/quiz")
    def quiz_action(index: int, command: QuizCommand, request: Request):
        snapshot = snapshot_at(index)
        check_origin(request)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Another graph request is running. Please wait.")
        trace = None
        request_event = None
        try:
            signature = command.model_dump(mode="json")
            request_key = (index, str(command.request_id))
            cached = quiz_requests.get(request_key)
            if cached:
                if cached[0] != signature:
                    raise HTTPException(409, "Request ID already used for a different quiz action")
                return cached[1]
            trace = trace_at(index)
            request_event = trace.emit("quiz.request", **signature)
            if command.action == "start":
                session = QuizSession(snapshot.graph, command.page_id, matcher_at(index).models)
                quizzes[(index, session.id)] = session
                state = session.public()
            else:
                session = quizzes.get((index, str(command.quiz_id)))
                if session is None:
                    raise HTTPException(404, "Quiz is not active on this server. Start a new session.")
                if command.action == "answer":
                    if not command.text.strip():
                        raise ValueError("Enter an answer before submitting")
                    # Reject stale/completed questions before loading or calling a model.
                    session._require_active(command.question_id)
                    state = session.answer(command.text, command.question_id, matcher_at(index))
                elif command.action == "hint":
                    state = session.hint(command.question_id)
                elif command.action == "reveal":
                    state = session.reveal(command.question_id)
                elif command.action == "next":
                    state = session.advance(command.question_id)
                else:
                    state = session.continue_session()
            # Remember successful actions before writing snapshots, so delivery
            # retries cannot count an answer or advance a question twice.
            quiz_requests[request_key] = (signature, state)
            trace.emit("quiz.state", parent_id=request_event, **state)
            trace.save(f"quiz/{session.id}.json", session.saved())
            return state
        except HTTPException:
            raise
        except ValueError as exc:
            if trace:
                trace.emit("quiz.error", parent_id=request_event, error=str(exc))
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            if trace:
                trace.emit("quiz.error", parent_id=request_event, error=str(exc), error_type=type(exc).__name__)
            raise HTTPException(503, f"Quiz request failed: {exc}") from exc
        finally:
            lock.release()

    @app.post("/runs/{index}/events")
    def interactions(index: int, batch: InteractionBatch, request: Request):
        snapshot_at(index)
        check_origin(request)
        trace = trace_at(index)
        # Browser retries (including page-hide delivery) must not duplicate events.
        with session_lock:
            seen = received.setdefault((index, str(batch.page_id)), set())
            for event in batch.events:
                if event.sequence not in seen:
                    trace.emit("explorer.interaction", page_id=str(batch.page_id),
                               **event.model_dump())
                    seen.add(event.sequence)
        return {"saved": True}

    @app.post("/runs/{index}/match")
    def match(index: int, query: Query, request: Request):
        snapshot = snapshot_at(index)
        check_origin(request)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Another graph query is running. Wait for it to finish.")
        trace = None
        query_event = None
        try:
            trace = trace_at(index)
            query_event = trace.emit("explorer.query", text=query.text,
                                    page_id=str(query.page_id) if query.page_id else None,
                                    query_id=str(query.query_id) if query.query_id else None)
            matcher = matcher_at(index)
            result = matcher.match(query.text)
            trace.emit("explorer.result", parent_id=query_event, result=result)
            return result
        except Exception as exc:
            if trace:
                trace.emit("explorer.error", parent_id=query_event, error=str(exc), error_type=type(exc).__name__)
            raise HTTPException(503, f"Matching failed: {exc}") from exc
        finally:
            lock.release()

    return app


def serve(directories, *, port=0, open_browser=True, overrides=None):
    import uvicorn
    app = create_app(directories, model_factory=lambda snapshot, trace: make_models(snapshot, trace, overrides))
    # Bind before announcing/opening the URL. Port 0 chooses a free local port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        url = f"http://127.0.0.1:{sock.getsockname()[1]}"
        if open_browser:
            app.state.open_url = url
        print(f"\nGraph explorer: {url}\nKeep this terminal open. Press Ctrl+C to stop the explorer.", flush=True)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        try:
            server.run(sockets=[sock])
        except KeyboardInterrupt:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path, help="Completed run directories")
    parser.add_argument("--port", type=int, default=0, help="Local port; 0 selects a free port")
    parser.add_argument("--no-open", action="store_true", help="Print the URL without opening a browser")
    parser.add_argument("--model", help="Override the saved run's Ollama model")
    parser.add_argument("--context-tokens", type=int, help="Override the saved model context window")
    if not 0 <= (args := parser.parse_args(argv)).port <= 65535:
        parser.error("port must be between 0 and 65535")
    if args.context_tokens is not None and args.context_tokens < 1:
        parser.error("context-tokens must be positive")
    overrides = {k: getattr(args, k) for k in ("model", "context_tokens") if getattr(args, k) is not None}
    try:
        serve(args.runs, port=args.port, open_browser=not args.no_open, overrides=overrides)
    except Exception as exc:
        parser.exit(1, f"Explorer could not start: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
