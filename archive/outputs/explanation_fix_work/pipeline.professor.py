from .settings import render_asset
from .settings import setting
"""Professor dashboard: python -m pipeline.professor --no-open."""
import _submission_runtime as _notebook
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
from .quiz_examiner import QuestionGenerationError, HelpGenerationError
from .student_store import StudentStore, grade, now, score

ROOT = _notebook.root


class StudentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=setting('ui', 'student_name_chars'))

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
    run_id: str | None = Field(default=None, max_length=setting('text', 'modality_chars'))
    focus_id: str | None = Field(default=None, max_length=setting('text', 'identifier_chars'))
    session_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    text: str = Field(default="", max_length=setting('ui', 'input_chars'))
    review_mode: bool = False
    scope_all: bool = False


class FactApprovalInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approved: bool
    reason: str = Field(min_length=1,max_length=setting('ui', 'input_chars'))


class GraphEditInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: uuid.UUID
    revision: int = Field(ge=0)
    action: Literal['add', 'edit', 'delete', 'revert']
    entity: Literal['concept', 'relationship'] | None = None
    id: str | None = Field(default=None, max_length=300)
    values: dict = Field(default_factory=dict)
    change_revision: int | None = Field(default=None, ge=1)
    professor: str | None = Field(default=None, max_length=200)
    reason: str = Field(default='', max_length=1500)


class OverrideInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marks: dict[str, Literal["match", "related", "conflict", "not_demonstrated"]]
    feedback: str = Field(min_length=1, max_length=setting('text', 'feedback_chars'))
    reason: str = Field(min_length=1, max_length=setting('ui', 'input_chars'))

    @field_validator("feedback", "reason")
    @classmethod
    def clean(cls, value):
        if not value.strip():
            raise ValueError("Feedback and an override reason are required")
        return value.strip()


class ContributionReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['approve', 'reject', 'undo']
    professor: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1500)


def run_identity(snapshot):
    payload = str(snapshot.directory) + json.dumps(snapshot.original_graph or snapshot.graph, sort_keys=True)
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
    from .graph_quality import edge_node_ids
    adjacent = {node["id"]: [] for node in graph["nodes"]}
    for edge in graph["edges"]:
        for identifier in edge_node_ids(edge):
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
        snapshots.append(Snapshot(Path(run["directory"]), saved["graph"], saved["manifest"], saved["quiz_aliases"], saved.get("original_graph", saved["graph"]), saved.get("revision", 0)))

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
        index = indices[identifier]
        from .graph_edits import ManualGraph
        snapshot = snapshots[index]
        state = ManualGraph(snapshot.directory, snapshot.original_graph or snapshot.graph).read()
        snapshot.original_graph = state['original']
        snapshot.graph = state['graph']
        snapshot.revision = state['revision']
        return index

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
                    pending_answers=store.pending_answers(identifier), scope_run_ids=session.scope_run_ids,
                    graph_review=session_review(row, index))

    def quiz_graph(index, run_id):
        graph=snapshots[index].graph
        return dict(graph, _quiz_approvals=store.approvals(run_id,graph))

    def pinned_graph(row, index):
        snapshot = snapshots[index]
        graph = row['checkpoint'].get('graph_snapshot', snapshot.original_graph or snapshot.graph)
        return dict(graph, _quiz_approvals=store.approvals(row['run_id'], graph))

    def session_review(row, index):
        from .graph_edits import semantics, affected
        old, current = pinned_graph(row, index), snapshots[index].graph
        changed = affected(old, current)
        requested = {f['id'] for f in row['checkpoint']['question'].get('examiner_material', {}).get('facts', [])}
        return dict(changed=bool(changed), affected_question=sorted(requested & set(changed)),
                    affected_relationships=changed,
                    message='The graph has changed. Historical answers are retained. Start a new quiz for the current graph.')

    def restore_session(row, index):
        session = QuizSession.restore(pinned_graph(row,index), None, row['checkpoint'])
        # Existing saved assessments use the same persistent knowledge and
        # adaptive rules after upgrading, without regenerating their question.
        from .knowledge import display_state
        facts = store.knowledge(row['student_id'], row['run_id'])
        if session.scope_run_ids:
            from .professor_scope import summarize_scope
            summary = summarize_scope(store, student_id=row['student_id'], source_run_ids=session.scope_run_ids)
            facts = summary['projected_knowledge'][row['run_id']]
        session.adaptive = True
        session.edge_status = display_state(session.graph, facts)['edge_status']
        session.independent = {k for k, f in facts.items() if k in session.edges and f['mark'] == 'match' and not f['helped']}
        session.assisted = {k for k, f in facts.items() if k in session.edges and f['mark'] == 'match' and f['helped']}
        return session

    def apply_overrides(session):
        # Knowledge was rebuilt from effective grades across the student's
        # history. Only the current question's feedback needs an override here.
        answers = store.answers(session.id)
        current_answers = [a for a in answers if a["question"]["id"] == session.question["id"]]
        if current_answers and current_answers[-1]["overrides"]:
            session.question["feedback"] = "Professor review: " + current_answers[-1]["effective_feedback"]

    catalog()

    from .contributions import Contributions
    contributions = Contributions(store)

    @app.get('/api/professor/runs/{run_id}/contributions')
    def contribution_list(run_id: str):
        snapshot = snapshots[run_index(run_id)]
        present = {e['id'] for e in snapshot.graph['edges']}
        return dict(run_id=run_id, jobs=contributions.jobs(run_id), contributions=[
            dict(row, published=row.get('edge_id') in present) for row in contributions.rows(run_id=run_id)])

    @app.post('/api/professor/answers/{answer_id}/contributions/check')
    def contribution_check(answer_id: uuid.UUID, request: Request):
        check_origin(request)
        # The just-rendered graph may hold the read lock briefly. Queue this
        # durable, idempotent check rather than failing a normal quiz submission.
        lock.acquire()
        try:
            answer = next((a for a in store.answers() if a['id'] == str(answer_id)), None)
            if answer is None: raise HTTPException(404, 'Graded answer not found')
            run_id = store.session(answer['session_id'])['run_id']
            index = run_index(run_id)
            try:
                contributions.check(str(answer_id), snapshots[index], matcher_at(index).models, trace_at(index))
            except Exception as exc:
                contributions.job(str(answer_id), 'needs_review', str(exc))
            return contribution_list(run_id)
        finally:
            lock.release()

    @app.post('/api/professor/contributions/{identifier}/review')
    def contribution_review(identifier: uuid.UUID, value: ContributionReviewInput, request: Request):
        check_origin(request)
        from .graph_edits import ManualGraph, EditConflict
        with lock:
            row = next((r for r in contributions.rows() if r['id'] == str(identifier)), None)
            if row is None: raise HTTPException(404, 'Contribution not found')
            snapshot = snapshots[run_index(row['run_id'])]
            try:
                contributions.decide(str(identifier), value.action, value.reason, value.professor,
                                     ManualGraph(snapshot.directory, snapshot.original_graph))
            except EditConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            return contribution_list(row['run_id'])

    @app.get("/professor", response_class=HTMLResponse)
    def dashboard():
        return render_asset("pipeline/professor.html")

    @app.get("/professor.js")
    def script():
        return Response(render_asset("pipeline/professor.js"), media_type="application/javascript")

    @app.get("/professor.css")
    def style():
        return Response(_notebook.asset_text("pipeline/professor.css"), media_type="text/css")

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

    @app.get('/api/professor/runs/{run_id}/quiz-material')
    def quiz_material(run_id: str):
        graph=snapshots[run_index(run_id)].graph
        approvals=store.approvals(run_id,graph)
        names={n['id']:n['label'] for n in graph['nodes']}
        return dict(run_id=run_id, facts=[dict(fact=e, source_name=names[e['source']], target_name=names[e['target']],
            approval=approvals.get(e['id']), eligible=e.get('origin') not in {'background', 'student'} or e['id'] in approvals)
            for e in graph['edges'] if e.get('origin') in {'background', 'student'}])

    @app.post('/api/professor/runs/{run_id}/facts/{fact_id}/approval')
    def approve_fact(run_id: str, fact_id: str, value: FactApprovalInput, request: Request):
        check_origin(request)
        with lock:
            graph=snapshots[run_index(run_id)].graph
            fact=next((e for e in graph['edges'] if e['id']==fact_id),None)
            if fact is None:
                raise HTTPException(404,'Fact not found in this source version')
            try:
                store.approve_fact(run_id,fact,value.approved,value.reason)
            except ValueError as exc:
                raise HTTPException(422,str(exc)) from exc
            return quiz_material(run_id)

    @app.get('/api/professor/runs/{run_id}/manual-graph')
    def manual_graph(run_id: str):
        from .graph_edits import ManualGraph
        snapshot = snapshots[run_index(run_id)]
        state = ManualGraph(snapshot.directory, snapshot.original_graph).read()
        reviews = [dict(session_id=s['id'], student_id=s['student_id'], answer_id=a['id'],
                        affected_relationships=a['graph_changes'])
                   for s in store.history() if s['run_id'] == run_id for a in s['answers'] if a['graph_changes']]
        return dict(run_id=run_id, **state, affected_assessments=reviews)

    @app.post('/api/professor/runs/{run_id}/manual-graph')
    def edit_graph(run_id: str, command: GraphEditInput, request: Request):
        check_origin(request)
        from .graph_edits import ManualGraph, EditConflict
        with lock:
            snapshot = snapshots[run_index(run_id)]
            user = request.scope.get('user')
            identity = getattr(user, 'display_name', None) if getattr(user, 'is_authenticated', False) else None
            actor = (dict(name=identity, source='authenticated') if identity else
                     dict(name=command.professor.strip(), source='self_reported') if command.professor and command.professor.strip() else None)
            payload = command.model_dump(mode='json', exclude={'professor'})
            try:
                state = ManualGraph(snapshot.directory, snapshot.original_graph).apply(payload, actor)
            except EditConflict as exc:
                raise HTTPException(409, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            snapshot.graph = state['graph']; snapshot.revision = state['revision']
            return manual_graph(run_id)

    @app.post('/api/professor/answers/{answer_id}/retry-matching')
    def retry_matching(answer_id: uuid.UUID, request: Request):
        check_origin(request)
        if not lock.acquire(blocking=False):
            raise HTTPException(409,'Another request is running; retry shortly')
        try:
            answer=next((a for a in store.answers() if a['id']==str(answer_id)),None)
            if answer is None:
                raise HTTPException(404,'Answer not found')
            result=copy.deepcopy(answer['result'])
            result.setdefault('graph_assessment_history',[]).append(copy.deepcopy(result.get('graph_assessment',{})))
            if result.get('assessment_version')!=2:
                raise HTTPException(422,'Legacy answers keep their historical assessment; use professor review')
            if result.get('graph_assessment',{}).get('status')=='resolved':
                return dict(status='resolved',already_resolved=True)
            from .quiz_grading import QuizGrader
            from .assessment import mastery_marks,eligible_fact,validate_graph_consistency
            row=store.session(answer['session_id'])
            index=run_index(row['run_id']);graph=pinned_graph(row,index)
            edges={e['id']:e for e in graph['edges']}
            try:
                if any(not eligible_fact(edges[c['fact_id']],graph['_quiz_approvals']) for c in result['assessment_spec']):
                    raise ValueError('Background approval is required for this assessment')
                from .graph_match import GraphMatcher
                historical_matcher = GraphMatcher(graph, matcher_at(index).models)
                mapped=historical_matcher.quiz_grader.match(answer['text'],answer['question']['text'],statements=result['statements'])
                result.update({k:mapped[k] for k in ('matches','uncredited','judgments','checked_records')})
                validate_graph_consistency(result)
                result['graph_assessment']=dict(status='resolved')
            except Exception as exc:
                result['graph_assessment']=dict(status='unresolved',error=str(exc))
            result['mastery_marks']=mastery_marks(answer['question'],result)
            store.update_graph_assessment(str(answer_id),result)
            trace_at(index).emit('professor.graph_assessment_retried',answer_id=str(answer_id),**result['graph_assessment'])
            return result['graph_assessment']
        finally:
            lock.release()

    @app.get('/api/professor/runs/{run_id}/knowledge')
    def knowledge(run_id: str, student_id: uuid.UUID | None = None):
        run_index(run_id)
        if student_id:
            student_exists(student_id)
        with lock:
            return store.graph_analytics(run_id, str(student_id) if student_id else None)

    @app.get('/api/professor/scope')
    def scope(topic: str | None = None, run_id: str | None = None, student_id: uuid.UUID | None = None):
        from .professor_scope import summarize_scope
        if student_id:
            student_exists(student_id)
        with lock:
            catalog()
            try:
                return summarize_scope(store, topic, run_id, str(student_id) if student_id else None)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc

    @app.get('/professor/scope-graph', response_class=HTMLResponse)
    def combined_graph(topic: str | None = None, run_id: str | None = None,
                       student_id: uuid.UUID | None = None, mode: str = 'class'):
        from .professor_scope import scope_graph_page
        if mode not in {'class', 'student', 'source'}:
            raise HTTPException(422, 'Unknown graph display')
        return scope_graph_page(scope(topic, run_id, student_id), mode)

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
            signature = command.model_dump_json(exclude={'scope_all'} if not command.scope_all else None)
            cached = store.cached(str(command.request_id), signature)
            if cached is not None:
                return cached
            answer = None
            if command.action == "start":
                student_exists(command.student_id)
                index = run_index(command.run_id)
                graph = quiz_graph(index,command.run_id)
                prior = store.knowledge(str(command.student_id), command.run_id)
                if command.scope_all:
                    from .professor_scope import summarize_scope
                    summary = summarize_scope(store, student_id=str(command.student_id))
                    if command.run_id not in summary['projected_knowledge']:
                        raise ValueError('All Topics quizzes use a latest source version; select a specific topic to quiz an older run')
                    prior = summary['projected_knowledge'][command.run_id]
                focus = command.focus_id or recommend(graph, prior)["id"]
                if not command.review_mode and all(e['id'] in prior and prior[e['id']]['mark'] == 'match'
                        and not prior[e['id']]['helped'] for e in graph['edges']):
                    raise ValueError('All eligible facts are covered. Enable review mode or choose another topic.')
                session = QuizSession(graph, uuid.uuid4(), matcher_at(index).models, focus_id=focus,
                                      prior_knowledge=prior, adaptive=True, review_mode=command.review_mode)
                session.scope_run_ids = [r['id'] for r in summary['runs']] if command.scope_all else None
                row = dict(id=session.id, student_id=str(command.student_id), run_id=command.run_id, created_at=now())
            else:
                row = store.session(str(command.session_id))
                index = run_index(row["run_id"])
                waiting = store.pending_answers(row["id"])
                if waiting and waiting[0]["id"] != str(command.request_id):
                    raise HTTPException(409, "An answer is saved and awaiting grading. Retry that pending request first.")
                review = session_review(row, index)
                if (review['affected_question'] and not waiting) or (command.action == 'next' and review['changed']):
                    raise HTTPException(409, dict(code='graph_changed', message=review['message']))
                session = restore_session(row, index)
                apply_overrides(session)
                session._require_active(command.question_id)
                if command.action == "answer":
                    if not command.text.strip():
                        raise ValueError("Enter an answer before submitting")
                    if session.question_mastered() and not session.question['attempts'] and not waiting:
                        raise ValueError('This material is already green from saved progress. Continue to the next question.')
                    question = copy.deepcopy(session.question)
                    store.stage_answer(row["id"], str(command.request_id), command.text, signature)
                    answer_saved = True
                    from .graph_match import GraphMatcher
                    historical_matcher = GraphMatcher(session.graph, matcher_at(index).models)
                    session.answer(command.text.strip(), command.question_id, historical_matcher)
                    from .graph_edits import semantics
                    session.question['graph_fingerprints'] = semantics(session.graph)
                    question=copy.deepcopy(session.question)
                    marks = grade(question, session.last_result)
                    answer = dict(id=str(command.request_id), question=question, text=command.text.strip(),
                                  helped=bool(question["hints"] or question["revealed"]),
                                  result=session.last_result, marks=marks, feedback=session.question["feedback"])
                elif command.action in {'hint', 'reveal'}:
                    try:
                        session.examiner.models = matcher_at(index).models
                    except Exception as model_error:
                        if command.action == 'hint':
                            raise HelpGenerationError('hint') from model_error
                        # A saved, reviewed expected answer needs no model startup.
                        trace_at(index).emit('quiz.reveal_fallback', session_id=session.id,
                                             phase='model_setup', reason=str(model_error))
                        session.examiner.models = None
                    if command.action == 'hint':
                        session.hint(command.question_id)
                    else:
                        session.reveal(command.question_id)
                else:
                    session.examiner.models = matcher_at(index).models
                    if command.focus_id:
                        if command.focus_id not in session.nodes:
                            raise ValueError('The selected starting concept is not in this graph')
                        session.focus = command.focus_id
                    session.advance(command.question_id)
            from .graph_edits import semantics
            session.question.setdefault('graph_fingerprints', semantics(session.graph))
            row["checkpoint"] = session.checkpoint()
            response = dict(id=session.id, student_id=row["student_id"], run_id=row["run_id"], state=session.public(),
                            contribution_answer_id=answer['id'] if answer else None,
                            answer_score=score(answer["marks"]) if answer else None, scope_run_ids=getattr(session, "scope_run_ids", None), graph_review=session_review(row, index))
            store.commit_action(row, answer, str(command.request_id), signature, response)
            answer_saved = False
            trace_at(index).emit("professor.quiz_saved", session_id=session.id, student_id=row["student_id"],
                                 action=command.action, run_id=row["run_id"])
            return response
        except HelpGenerationError as exc:
            raise HTTPException(422, dict(code=exc.action + '_generation', message=str(exc),
                                         progress_unchanged=True)) from exc
        except QuestionGenerationError as exc:
            raise HTTPException(422, dict(code='question_generation', message=str(exc),
                                         progress_unchanged=True)) from exc
        except HTTPException:
            raise
        except KeyError as exc:
            if answer_saved:
                store.mark_unresolved(str(command.request_id), exc)
                raise HTTPException(503, f"Your answer is saved and awaiting grading (unresolved; no grade or mastery change): {exc}. Retry the same request.") from exc
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            if answer_saved:
                store.mark_unresolved(str(command.request_id), exc)
                raise HTTPException(503, f"Your answer is saved and awaiting grading (unresolved; no grade or mastery change): {exc}. Retry the same request.") from exc
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            if answer_saved:
                store.mark_unresolved(str(command.request_id), exc)
                raise HTTPException(503, f"Your answer is saved and awaiting grading (unresolved; no grade or mastery change): {exc}. Retry the same request.") from exc
            if command.action in {'start', 'next'}:
                raise HTTPException(503, f"Could not prepare the question: {exc}. Existing quiz progress is unchanged. Retry the same request.") from exc
            if command.action in {'hint', 'reveal'}:
                label = 'Hint' if command.action == 'hint' else 'Answer reveal'
                raise HTTPException(503, f"{label} request could not be completed: {exc}. Retry the same request.") from exc
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
    def graph(run_id: str, embedded: bool = False, version: Literal['edited', 'original'] = 'edited'):
        index = run_index(run_id)
        if version == 'original':
            from .graph_view import render_graph
            page = render_graph(snapshots[index].original_graph)
            return page.replace('<header>', '<header><p role="status">Original generated graph — read-only. Manual edits remain saved.</p>', 1)
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
          document.querySelector('.query-intro').textContent=classOverlay?'Brighter, thicker relationships are independently known by more students. Hover for sample sizes.':state?'Green: correct without help. Amber: partial or assisted. Red: incorrect or not demonstrated. Gray: not yet assessed.':'Enter a concept, relationship, or statement. Exploration highlights are temporary and never count as student knowledge.';
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
        sock.listen(setting('operations', 'server_backlog'))
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
