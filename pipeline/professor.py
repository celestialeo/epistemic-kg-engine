"""Professor dashboard: python -m pipeline.professor --no-open."""
import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import socket
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal

from .quiz import QuizSession
from .student_store import StudentStore, grade, now, score

ROOT = Path(__file__).resolve().parents[1]


class StudentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Enter a student name")
        return value.strip()


class AssessmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "answer", "hint", "reveal", "next"]
    request_id: uuid.UUID
    student_id: uuid.UUID | None = None
    run_id: str | None = Field(default=None, max_length=80)
    focus_id: str | None = Field(default=None, max_length=300)
    session_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    text: str = Field(default="", max_length=1500)
    review_mode: bool = False


class OverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marks: dict[str, Literal["match", "related", "conflict", "not_demonstrated"]]
    feedback: str = Field(min_length=1, max_length=3000)
    reason: str = Field(min_length=1, max_length=1500)

    @field_validator("feedback", "reason")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Feedback and an override reason are required")
        return value.strip()


def run_identity(snapshot):
    payload = str(snapshot.directory) + json.dumps(snapshot.graph, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def topic_identity(snapshot):
    config = snapshot.manifest.get("config", {})
    key = config.get("input") or config.get("chapter") or str(snapshot.directory.parent)
    title = config.get("chapter")
    if not title or title == "custom":
        title = Path(config.get("input", snapshot.directory.parent.name)).stem
    return str(key), title.replace("-", " ").replace("_", " ")


def discover_latest(root, *, latest_only=True):
    from .explorer import load_snapshot
    latest, warnings, all_snapshots = {}, [], []
    for path in sorted({*Path(root).glob("*/*/manifest.json"), *Path(root).glob('*/manifest.json')}):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("status") not in {"completed", "completed_with_issues"}:
                continue
            snapshot = load_snapshot(path.parent)
            all_snapshots.append(snapshot)
            key, _ = topic_identity(snapshot)
            timestamp = manifest.get("started_at_utc") or manifest.get("started_at")
            stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() if timestamp else path.stat().st_mtime
            ordering = (stamp, path.parent.name)
            if key not in latest or ordering > latest[key][0]:
                latest[key] = (ordering, snapshot)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            warnings.append(f"Could not load {path.parent.name}: {exc}")
    return ([item[1] for item in latest.values()] if latest_only else all_snapshots), warnings


def recommend(graph, knowledge):
    adjacent = {node["id"]: [] for node in graph["nodes"]}
    for edge in graph["edges"]:
        for identifier in {edge["source"], edge["target"]}:
            adjacent[identifier].append(edge["id"])
    def priority(node):
        ids = adjacent[node["id"]]
        weak = sum(i in knowledge and (knowledge[i]["mark"] != "match" or knowledge[i]['helped']) for i in ids)
        unassessed = sum(i not in knowledge for i in ids)
        return (-weak, -unassessed, -len(ids), node["label"], node["id"])
    nodes = sorted(graph["nodes"], key=priority)
    if not nodes:
        raise ValueError("This graph has no concepts to quiz")
    chosen = nodes[0]
    ids = adjacent[chosen["id"]]
    reason = ("Review previously assessed gaps" if any(i in knowledge and (knowledge[i]["mark"] != "match" or knowledge[i]['helped']) for i in ids)
              else "Assess material not yet covered" if any(i not in knowledge for i in ids)
              else "All eligible facts are covered; enable review mode or choose another topic")
    return dict(id=chosen["id"], label=chosen["label"], reason=reason)


def install_dashboard(app, snapshots, store, runs_root, matcher_at, trace_at, check_origin, lock):
    from .explorer import Snapshot, explorer_page
    indices = {}
    for run in store.runs():
        saved = run["snapshot"]
        indices[run["id"]] = len(snapshots)
        snapshots.append(Snapshot(Path(run["directory"]), saved["graph"], saved["manifest"], saved["quiz_aliases"]))

    def catalog():
        found, warnings = discover_latest(runs_root, latest_only=False)
        for snapshot in found:
            identifier = run_identity(snapshot)
            if identifier not in indices:
                key, title = topic_identity(snapshot)
                store.register_run(identifier, key, title, snapshot)
                indices[identifier] = len(snapshots)
                snapshots.append(snapshot)
        # Preserve historical topics even if their source directory was moved.
        latest = {}
        for run in store.runs():
            manifest = run["snapshot"]["manifest"]
            stamp = manifest.get("started_at_utc") or manifest.get("started_at") or ""
            if run["topic_key"] not in latest or stamp > latest[run["topic_key"]][0]:
                latest[run["topic_key"]] = (stamp, run)
        topics = []
        for _, run in latest.values():
            snapshot = run["snapshot"]
            manifest = snapshot["manifest"]
            topics.append(dict(id=run["id"], title=run["title"], topic_key=run["topic_key"],
                run_name=Path(run["directory"]).name, status=manifest["status"],
                started_at=manifest.get("started_at"), concepts=snapshot["graph"]["nodes"],
                relationships=len(snapshot["graph"]["edges"])))
        return sorted(topics, key=lambda t: t["title"]), warnings

    def student_exists(identifier):
        if str(identifier) not in {s["id"] for s in store.students()}:
            raise HTTPException(404, "Student not found")

    def run_index(identifier):
        if identifier not in indices:
            raise HTTPException(404, "Run not found; refresh the topic list")
        return indices[identifier]

    def detail(identifier):
        try:
            row = store.session(identifier)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        index = run_index(row["run_id"])
        # Reading history never loads Ollama or regenerates questions.
        session = restore_session(row, index)
        apply_overrides(session)
        return dict(id=row["id"], student_id=row["student_id"], run_id=row["run_id"],
                    created_at=row["created_at"], state=session.public(), answers=store.answers(identifier),
                    pending_answers=store.pending_answers(identifier))

    def restore_session(row, index):
        session = QuizSession.restore(snapshots[index].graph, None, row['checkpoint'])
        # Existing saved assessments use the same persistent knowledge and
        # adaptive rules after upgrading, without regenerating their question.
        from .knowledge import display_state
        facts = store.knowledge(row['student_id'], row['run_id'])
        session.adaptive = True
        session.edge_status = display_state(snapshots[index].graph, facts)['edge_status']
        session.independent = {k for k, f in facts.items() if f['mark'] == 'match' and not f['helped']}
        session.assisted = {k for k, f in facts.items() if f['mark'] == 'match' and f['helped']}
        return session

    def apply_overrides(session):
        # Knowledge was rebuilt from effective grades across the student's
        # history. Only the current question's feedback needs an override here.
        answers = store.answers(session.id)
        current_answers = [a for a in answers if a["question"]["id"] == session.question["id"]]
        if current_answers and current_answers[-1]["overrides"]:
            session.question["feedback"] = "Professor review: " + current_answers[-1]["effective_feedback"]

    catalog()

    @app.get("/professor", response_class=HTMLResponse)
    def dashboard():
        return Path(__file__).with_name("professor.html").read_text(encoding="utf-8")

    @app.get("/professor.js")
    def script():
        return Response(Path(__file__).with_name("professor.js").read_text(encoding="utf-8"), media_type="application/javascript")

    @app.get("/professor.css")
    def style():
        return Response(Path(__file__).with_name("professor.css").read_text(encoding="utf-8"), media_type="text/css")

    @app.get("/api/professor/catalog")
    def get_catalog():
        with lock:
            topics, warnings = catalog()
            versions = [dict(id=r['id'], title=r['title'], topic_key=r['topic_key'],
                run_name=Path(r['directory']).name, status=r['snapshot']['manifest'].get('status'),
                concepts=r['snapshot']['graph']['nodes'], relationships=len(r['snapshot']['graph']['edges']))
                for r in store.runs()]
            return dict(students=store.students(), topics=topics, versions=versions, warnings=warnings)

    @app.get('/api/professor/runs/{run_id}/results')
    def results(run_id: str):
        from .run_results import summarize
        return summarize(snapshots[run_index(run_id)])

    @app.get('/api/professor/runs/{run_id}/knowledge')
    def knowledge(run_id: str, student_id: uuid.UUID | None = None):
        run_index(run_id)
        if student_id:
            student_exists(student_id)
        with lock:
            return store.graph_analytics(run_id, str(student_id) if student_id else None)

    @app.post("/api/professor/students")
    def add_student(value: StudentInput, request: Request):
        check_origin(request)
        return store.add_student(value.name)

    @app.get("/api/professor/analytics")
    def analytics(student_id: uuid.UUID | None = None):
        if student_id:
            student_exists(student_id)
        with lock:
            topics, _ = catalog()
            return store.analytics(topics, str(student_id) if student_id else None)

    @app.get("/api/professor/students/{student_id}/history")
    def history(student_id: uuid.UUID):
        student_exists(student_id)
        return store.history(str(student_id))

    @app.get("/api/professor/sessions/{session_id}")
    def session_state(session_id: uuid.UUID):
        return detail(str(session_id))

    @app.get("/api/professor/recommendation/{student_id}/{run_id}")
    def recommendation(student_id: uuid.UUID, run_id: str):
        student_exists(student_id)
        return recommend(snapshots[run_index(run_id)].graph, store.knowledge(str(student_id), run_id))

    @app.post("/api/professor/quiz")
    def action(command: AssessmentCommand, request: Request):
        check_origin(request)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Another graph request is running. Please wait, then retry.")
        answer_saved = False
        try:
            signature = command.model_dump_json()
            cached = store.cached(str(command.request_id), signature)
            if cached is not None:
                return cached
            answer = None
            if command.action == "start":
                student_exists(command.student_id)
                index = run_index(command.run_id)
                graph = snapshots[index].graph
                prior = store.knowledge(str(command.student_id), command.run_id)
                focus = command.focus_id or recommend(graph, prior)["id"]
                if not command.review_mode and all(e['id'] in prior and prior[e['id']]['mark'] == 'match'
                        and not prior[e['id']]['helped'] for e in graph['edges']):
                    raise ValueError('All eligible facts are covered. Enable review mode or choose another topic.')
                session = QuizSession(graph, uuid.uuid4(), matcher_at(index).models, focus_id=focus,
                                      prior_knowledge=prior, adaptive=True, review_mode=command.review_mode)
                row = dict(id=session.id, student_id=str(command.student_id), run_id=command.run_id, created_at=now())
            else:
                row = store.session(str(command.session_id))
                index = run_index(row["run_id"])
                waiting = store.pending_answers(row["id"])
                if waiting and waiting[0]["id"] != str(command.request_id):
                    raise HTTPException(409, "An answer is saved and awaiting grading. Retry that pending request first.")
                session = restore_session(row, index)
                apply_overrides(session)
                session._require_active(command.question_id)
                if command.action == "answer":
                    if not command.text.strip():
                        raise ValueError("Enter an answer before submitting")
                    question = copy.deepcopy(session.question)
                    store.stage_answer(row["id"], str(command.request_id), command.text, signature)
                    answer_saved = True
                    session.answer(command.text.strip(), command.question_id, matcher_at(index))
                    marks = grade(question, session.last_result)
                    answer = dict(id=str(command.request_id), question=question, text=command.text.strip(),
                                  helped=bool(question["hints"] or question["revealed"]),
                                  result=session.last_result, marks=marks, feedback=session.question["feedback"])
                elif command.action == "hint":
                    session.examiner.models = matcher_at(index).models
                    session.hint(command.question_id)
                elif command.action == "reveal":
                    session.examiner.models = matcher_at(index).models
                    session.reveal(command.question_id)
                else:
                    session.examiner.models = matcher_at(index).models
                    session.advance(command.question_id)
            row["checkpoint"] = session.checkpoint()
            response = dict(id=session.id, student_id=row["student_id"], run_id=row["run_id"], state=session.public(),
                            answer_score=score(answer["marks"]) if answer else None)
            store.commit_action(row, answer, str(command.request_id), signature, response)
            answer_saved = False
            trace_at(index).emit("professor.quiz_saved", session_id=session.id, student_id=row["student_id"],
                                 action=command.action, run_id=row["run_id"])
            return response
        except HTTPException:
            raise
        except KeyError as exc:
            if answer_saved:
                raise HTTPException(503, f"Your answer is saved and awaiting grading: {exc}. Retry the same request.") from exc
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            if answer_saved:
                raise HTTPException(503, f"Your answer is saved and awaiting grading: {exc}. Retry the same request.") from exc
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            if answer_saved:
                raise HTTPException(503, f"Your answer is saved and awaiting grading: {exc}. Retry the same request.") from exc
            raise HTTPException(503, f"Assessment could not be saved: {exc}. Retry the same request.") from exc
        finally:
            lock.release()

    @app.post("/api/professor/answers/{answer_id}/override")
    def override(answer_id: uuid.UUID, value: OverrideInput, request: Request):
        check_origin(request)
        with lock:
            try:
                store.override(str(answer_id), value.marks, value.feedback, value.reason)
                return dict(saved=True)
            except KeyError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.get("/professor/graph/{run_id}", response_class=HTMLResponse)
    def graph(run_id: str, embedded: bool = False):
        index = run_index(run_id)
        page = explorer_page(snapshots[index], index, len(snapshots))
        # Use the existing interactive graph and query console. Quiz actions live
        # in the parent dashboard, where student ownership is explicit.
        bridge = '''<script>
        document.querySelector('.study-controls').hidden=true;
        let classOverlay=null;
        for(let i=0;i<=10;i++){
          const marker=el('marker',{id:'class-arrow-'+i,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:6,markerHeight:6,orient:'auto-start-reverse'},svg.querySelector('defs'));
          el('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:`hsl(150 55% ${28+i*4}%)`},marker);
        }
        const coverageHighlight=highlight;
        highlight=function(){
          coverageHighlight();
          if(!classOverlay)return;
          for(const edge of links){
            const entry=classOverlay.find(row=>row.id===edge.id);if(!entry)continue;
            const color=entry.proportion===null?'#62738d':`hsl(150 55% ${28+entry.proportion*40}%)`;
            edge.line.setAttribute('stroke',color);edge.line.setAttribute('stroke-width',2+5*(entry.proportion||0));
            edge.line.setAttribute('marker-end',entry.proportion===null?'url(#arrow-query-unmapped)':`url(#class-arrow-${Math.round(entry.proportion*10)})`);edge.group.style.opacity=1;
            const title=edge.group.querySelector('title');
            if(title)title.textContent=`${entry.known}/${entry.students} independently know; ${entry.assessed}/${entry.students} assessed`;
          }
        };
        window.addEventListener('message',event=>{
          if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='professor-coverage')return;
          queryGeneration++;classOverlay=event.data.overlay||null;
          $('query-results').replaceChildren();$('query-text').value='';$('query-status').textContent='';
          const state=event.data.state; quizMode=Boolean(state);quizFinished=Boolean(state?.completed);
          nodeMatches.clear();edgeMatches.clear();
          for(const [id,status] of Object.entries(state?.node_status||{}))nodeMatches.set(id,status);
          for(const [id,status] of Object.entries(state?.edge_status||{}))edgeMatches.set(id,status);
          document.body.classList.toggle('quiz-mode',Boolean(state));
          $('query-form').hidden=Boolean(state)||Boolean(classOverlay);
          for(const selector of ['.match-legend','#match-help','.graph-heading .legend','main aside>p.muted']){
            const item=document.querySelector(selector);if(item)item.hidden=Boolean(state)||Boolean(classOverlay);
          }
          $('details').replaceChildren();$('detail-title').textContent='Explore the knowledge';
          $('hint').textContent=state?'Select a concept or relationship to inspect it.':classOverlay?'Hover over a relationship for independent knowledge and assessment counts.':'Select a concept or relationship to explore it.';
          $('explorer-title').textContent=classOverlay?'Class knowledge':state?'Saved student knowledge':'Explore this graph';
          document.querySelector('.query-intro').textContent=classOverlay?'Brighter, thicker relationships are independently known by more students. Hover for sample sizes.':state?'Green: independently correct. Amber: partial or assisted. Red: incorrect. Gray: unassessed.':'Enter a concept, relationship, or statement. Exploration highlights are temporary and never count as student knowledge.';
          focus=null;selected=null;$('search').value='';$('background').checked=true;
          render();
        });
        </script>'''
        if embedded:
            bridge += '''<style>
            body{background:#101827;display:flow-root}
            header{padding:12px 0 20px;max-width:none}
            header>.eyebrow,header>h1,header>#run,.run-meta a{display:none}
            #explorer{margin:0 auto;max-width:800px;padding:0 12px}
            #explorer h2{font-size:24px;letter-spacing:-.5px}
            .query-intro{margin-bottom:14px}
            .graph-shell{margin:0;border-radius:10px;box-shadow:none;max-width:none}
            main{height:540px;min-height:0;grid-template-columns:minmax(0,1fr) 260px}
            @media(max-width:800px){main{height:auto;grid-template-columns:1fr}
              #canvas{height:400px;min-height:0}aside{max-height:300px}}
            </style><script>
            const reportHeight=()=>parent.postMessage({type:'professor-graph-height',height:Math.ceil(document.body.getBoundingClientRect().height)},location.origin);
            new ResizeObserver(reportHeight).observe(document.body);
            reportHeight();
            </script>'''
        return page.replace('<script src="/quiz.js"></script>', bridge)


def serve(*, runs_root=ROOT / "outputs/runs", database=ROOT / "outputs/professor/students.sqlite3",
          selected_run=None, port=0, open_browser=True):
    """The pipeline's shared graph, quiz and professor interaction step."""
    from .explorer import create_app, load_snapshot
    import uvicorn
    store = StudentStore(database)
    selected_id = None
    if selected_run is not None:
        snapshot = load_snapshot(selected_run)
        selected_id = run_identity(snapshot)
        key, title = topic_identity(snapshot)
        store.register_run(selected_id, key, title, snapshot)
    app = create_app([], professor_store=store, runs_root=runs_root)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        url = f"http://127.0.0.1:{sock.getsockname()[1]}/professor"
        if selected_id:
            url += "?run=" + selected_id
        if open_browser:
            app.state.open_url = url
        print(f"\n[Interacting with graph]\nGraph, quiz & professor dashboard: {url}\n"
              f"Student history: {store.path}\nKeep this terminal open. Press Ctrl+C to stop.", flush=True)
        try:
            uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
        except KeyboardInterrupt:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=ROOT / "outputs/runs")
    parser.add_argument("--database", type=Path, default=ROOT / "outputs/professor/students.sqlite3")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    serve(runs_root=args.runs_root, database=args.database, port=args.port, open_browser=not args.no_open)


if __name__ == "__main__":
    main()
