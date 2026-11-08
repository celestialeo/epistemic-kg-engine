"""Local professor records. Saved pipeline runs are never rewritten."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .quiz_grading import RUBRIC_MARKS
from .knowledge import fact_keys, metrics, mean, display_state, communities, DEFINITIONS

MARKS = {"match": 1.0, "related": .5, "conflict": 0.0, "not_demonstrated": 0.0}


def now():
    return datetime.now(timezone.utc).isoformat()


def score(marks):
    return round(100 * sum(MARKS[value] for value in marks.values()) / len(marks), 1) if marks else None


def grade(question, result):
    # Grade only facts actually supplied to the question writer, not its larger
    # traversal neighborhood. Omission means not demonstrated, not contradiction.
    marks = {fact["id"]: "not_demonstrated" for fact in question["examiner_material"]["facts"]}
    if "rubric" in result:
        rubric = result["rubric"]
        if (len(rubric) != len(marks) or {item["fact_id"] for item in rubric} != set(marks)
                or any(item["status"] not in RUBRIC_MARKS for item in rubric)):
            raise ValueError("Every requested rubric fact needs a resolved assessment")
        return {item["fact_id"]: RUBRIC_MARKS[item["status"]] for item in rubric}
    # Legacy results retain their original edge-based scoring.
    marks.update({key: value for key, value in graph_marks(result).items() if key in marks})
    return marks


def graph_marks(result):
    """Only validated graph matches, never partial rubric claims, color edges."""
    rank = {"related": 1, "match": 2, "conflict": 3}
    found = {}
    for item in result["matches"]:
        identifier, status = item["id"], item["status"]
        if rank[status] > rank.get(found.get(identifier), 0):
            found[identifier] = status
    return found


class StudentStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS students (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, topic_key TEXT NOT NULL, title TEXT NOT NULL,
                    directory TEXT NOT NULL, snapshot TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, student_id TEXT NOT NULL REFERENCES students(id),
                    run_id TEXT NOT NULL REFERENCES runs(id), created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, checkpoint TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS answers (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    created_at TEXT NOT NULL, question TEXT NOT NULL, text TEXT NOT NULL,
                    helped INTEGER NOT NULL, result TEXT NOT NULL, marks TEXT NOT NULL,
                    feedback TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS overrides (
                    id INTEGER PRIMARY KEY, answer_id TEXT NOT NULL REFERENCES answers(id),
                    created_at TEXT NOT NULL, marks TEXT NOT NULL, feedback TEXT NOT NULL,
                    reason TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, signature TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS pending_answers (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
                    created_at TEXT NOT NULL, text TEXT NOT NULL, signature TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS student_sessions ON sessions(student_id, created_at);
                CREATE INDEX IF NOT EXISTS session_answers ON answers(session_id, created_at);
                CREATE INDEX IF NOT EXISTS answer_overrides ON overrides(answer_id, id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def students(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM students ORDER BY name, id")]

    def add_student(self, name):
        student = dict(id=str(uuid.uuid4()), name=name, created_at=now())
        with self.connect() as db:
            db.execute("INSERT INTO students VALUES (:id,:name,:created_at)", student)
        return student

    def register_run(self, identifier, topic_key, title, snapshot):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?)", (
                identifier, topic_key, title, str(snapshot.directory),
                json.dumps(dict(graph=snapshot.graph, manifest=snapshot.manifest,
                                quiz_aliases=snapshot.quiz_aliases))))

    def runs(self):
        with self.connect() as db:
            return [dict(row, snapshot=json.loads(row["snapshot"])) for row in db.execute("SELECT * FROM runs")]

    def session(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise KeyError("Assessment not found")
            return dict(row, checkpoint=json.loads(row["checkpoint"]))

    def cached(self, identifier, signature):
        with self.connect() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (identifier,)).fetchone()
            pending = db.execute("SELECT signature FROM pending_answers WHERE id=?", (identifier,)).fetchone()
        if pending and pending["signature"] != signature:
            raise ValueError("Request ID was already used for a different action")
        if row:
            if row["signature"] != signature:
                raise ValueError("Request ID was already used for a different action")
            return json.loads(row["response"])

    def pending_answers(self, session_id):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM pending_answers WHERE session_id=?", (session_id,)).fetchall()
        return [dict(id=row["id"], session_id=row["session_id"], created_at=row["created_at"],
                     text=row["text"], grading_status="pending", score=None,
                     request=json.loads(row["signature"])) for row in rows]

    def stage_answer(self, session_id, request_id, text, signature):
        # Save the submission before calling the model. Pending work is separate
        # from graded answers so it cannot affect scores, coverage or progress.
        with self.connect() as db:
            row = db.execute("SELECT * FROM pending_answers WHERE id=? OR session_id=?",
                             (request_id, session_id)).fetchone()
            if row:
                if row["id"] != request_id or row["signature"] != signature:
                    raise ValueError("Retry the pending answer before submitting another action")
                return
            db.execute("INSERT INTO pending_answers VALUES (?,?,?,?,?)",
                       (request_id, session_id, now(), text, signature))

    def commit_action(self, session, answer, request_id, signature, response):
        # The checkpoint, grade, retry receipt and removal of the pending answer
        # commit together. A failed write leaves the original submission pending.
        with self.connect() as db:
            db.execute("""INSERT INTO sessions VALUES (?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,
                checkpoint=excluded.checkpoint""", (
                session["id"], session["student_id"], session["run_id"], session["created_at"],
                now(), json.dumps(session["checkpoint"])))
            if answer:
                db.execute("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?)", (
                    answer["id"], session["id"], now(), json.dumps(answer["question"]), answer["text"],
                    answer["helped"], json.dumps(answer["result"]), json.dumps(answer["marks"]), answer["feedback"]))
            db.execute("INSERT INTO requests VALUES (?,?,?)", (request_id, signature, json.dumps(response)))
            if answer:
                db.execute("DELETE FROM pending_answers WHERE id=?", (request_id,))

    def answers(self, session_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT answers.* FROM answers " +
                ("WHERE session_id=? " if session_id else "") + "ORDER BY created_at, rowid",
                (session_id,) if session_id else ()).fetchall()
            overrides = {}
            for row in db.execute("SELECT * FROM overrides ORDER BY id"):
                overrides.setdefault(row["answer_id"], []).append(dict(row, marks=json.loads(row["marks"])))
        result = []
        for row in rows:
            item = dict(row)
            for key in ("question", "result", "marks"):
                item[key] = json.loads(item[key])
            item["overrides"] = overrides.get(item["id"], [])
            effective = item["overrides"][-1] if item["overrides"] else item
            item.update(effective_marks=effective["marks"], effective_feedback=effective["feedback"],
                        score=score(effective["marks"]), original_score=score(item["marks"]))
            result.append(item)
        return result

    def override(self, answer_id, marks, feedback, reason):
        with self.connect() as db:
            row = db.execute("SELECT marks FROM answers WHERE id=?", (answer_id,)).fetchone()
            if row is None:
                raise KeyError("Answer not found")
            if set(marks) != set(json.loads(row["marks"])) or not marks:
                raise ValueError("Grade every assessed fact; do not add facts outside this question")
            if any(mark not in MARKS for mark in marks.values()):
                raise ValueError("Invalid fact grade")
            db.execute("INSERT INTO overrides(answer_id,created_at,marks,feedback,reason) VALUES (?,?,?,?,?)",
                       (answer_id, now(), json.dumps(marks), feedback, reason))

    def history(self, student_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM sessions " +
                ("WHERE student_id=? " if student_id else "") + "ORDER BY created_at, rowid",
                (student_id,) if student_id else ()).fetchall()
        answers = {}
        for answer in self.answers():
            answers.setdefault(answer["session_id"], []).append(answer)
        result = []
        runs = {r["id"]: r for r in self.runs()}
        for row in rows:
            checkpoint = json.loads(row["checkpoint"])
            attempts = answers.get(row["id"], [])
            # Revisions do not count as independent questions or inflate scores.
            latest = {a["question"]["id"]: a for a in attempts}
            values = [a["score"] for a in latest.values() if a["score"] is not None]
            result.append(dict(id=row["id"], student_id=row["student_id"], run_id=row["run_id"],
                topic_title=runs[row["run_id"]]["title"], run_name=Path(runs[row["run_id"]]["directory"]).name,
                created_at=row["created_at"], updated_at=row["updated_at"], completed=checkpoint["completed"],
                answer_count=len(attempts), question_count=len(latest),
                assisted_answers=sum(bool(a["helped"]) for a in latest.values()),
                score=round(sum(values)/len(values), 1) if values else None, answers=attempts))
        return result

    def knowledge(self, student_id, run_id, *, graph_only=False, include_current=True):
        return self._knowledge(student_id, run_id, {r['id']: r for r in self.runs()},
                               self.history(student_id), include_current)

    @staticmethod
    def _knowledge(student_id, run_id, runs, history, include_current=True):
        # Derive state from durable answer evidence; exploration never enters here.
        # Exact semantic transfer is conservative and retains the original audit trail.
        target = runs[run_id]
        def stamp(run):
            manifest = run['snapshot']['manifest']
            value = manifest.get('started_at_utc') or manifest.get('started_at')
            try:
                parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                return parsed.timestamp() if parsed.tzinfo else None
            except (AttributeError, ValueError):
                return None
        target_keys = {key: identifier for identifier, key in fact_keys(target['snapshot']['graph']).items()}
        mappings = {}
        for run in runs.values():
            if run['id'] == run_id:
                if include_current:
                    mappings[run_id] = {e['id']: e['id'] for e in run['snapshot']['graph']['edges']}
            elif run['topic_key'] == target['topic_key'] and stamp(run) is not None and stamp(target) is not None and stamp(run) < stamp(target):
                mappings[run['id']] = {identifier: target_keys[key] for identifier, key in
                    fact_keys(run['snapshot']['graph']).items() if key in target_keys}
        facts = {}
        attempts = [(session['run_id'], a) for session in history
                    if session['student_id'] == student_id and session['run_id'] in mappings for a in session['answers']]
        # Current-version evidence always supersedes transferred evidence.
        for source, answer in sorted(attempts, key=lambda pair: (pair[0] == run_id, pair[1]['created_at'])):
            marks = dict(answer['effective_marks'])
            # Validated incidental statements are also evidence, but the requested
            # rubric takes precedence for facts actually assessed by the question.
            marks = {**graph_marks(answer['result']), **marks}
            for identifier, mark in marks.items():
                if identifier not in mappings[source]:
                    continue
                facts[mappings[source][identifier]] = dict(mark=mark, helped=bool(answer['helped']),
                    at=answer['created_at'], source_run_id=source, source_fact_id=identifier,
                    answer_id=answer['id'], transferred=source != run_id)
        return facts

    def graph_analytics(self, run_id, student_id=None):
        runs = {r['id']: r for r in self.runs()}
        run = runs[run_id]
        graph = run['snapshot']['graph']
        groups = communities(graph)
        history = self.history()
        students = self.students()
        rows, knowledge = [], {}
        for student in students:
            facts = self._knowledge(student['id'], run_id, runs, history)
            knowledge[student['id']] = facts
            attempts = sorted([a for s in history if s['student_id'] == student['id'] and s['run_id'] == run_id
                               for a in s['answers']], key=lambda a: a['created_at'])
            baseline = self._knowledge(student['id'], run_id, runs, history, include_current=False)
            progress, seen = [], []
            if baseline:
                m = metrics(graph, baseline, groups=groups)
                progress.append(dict(at=None, label='Transferred baseline', **{k: m[k] for k in
                    ('knowledge_coverage', 'assessment_coverage', 'average_score')}))
            for answer in attempts:
                seen.append(answer)
                for key, mark in {**graph_marks(answer['result']), **answer['effective_marks']}.items():
                    baseline[key] = dict(mark=mark, helped=answer['helped'])
                m = metrics(graph, baseline, seen, groups)
                progress.append(dict(at=answer['created_at'], **{k: m[k] for k in
                    ('knowledge_coverage', 'assessment_coverage', 'average_score')}))
            rows.append(dict(**student, metrics=metrics(graph, facts, attempts, groups), progress=progress,
                             transferred=sum(f['transferred'] for f in facts.values())))
        fields = ('knowledge_coverage', 'assessment_coverage', 'average_score', 'independent_score',
                  'assisted_score', 'connected_understanding', 'mastered_components',
                  'isolated_mastered_concepts', 'concentration')
        averages = {k: dict(value=mean([r['metrics'][k] for r in rows], 3 if k == 'concentration' else 1),
                           n=sum(r['metrics'][k] is not None for r in rows)) for k in fields}
        overlay = []
        for edge in graph['edges']:
            evidence = [facts[edge['id']] for facts in knowledge.values() if edge['id'] in facts]
            known = sum(f['mark'] == 'match' and not f['helped'] for f in evidence)
            overlay.append(dict(id=edge['id'], source=edge['source'], target=edge['target'], label=edge['label'],
                known=known, assessed=len(evidence), students=len(students),
                proportion=known/len(students) if students else None))
        topics = []
        for index, group in enumerate(groups):
            values = [r['metrics']['topics'][index] for r in rows]
            topics.append(dict(title=group['title'], total=len(group['facts'])*len(students),
                assessed=sum(v['assessed'] for v in values), unassessed=sum(v['unassessed'] for v in values),
                knowledge_coverage=mean([v['knowledge_coverage'] for v in values]),
                assessed_score=mean([v['assessed_score'] for v in values]),
                assessed_students=sum(v['assessed'] > 0 for v in values)))
        class_progress, evolving = [], {}
        events = [(p['at'], r['id'], p) for r in rows for p in r['progress'] if p['at']]
        for at, identifier, point in sorted(events, key=lambda event: (event[0], event[1])):
            evolving[identifier] = point
            class_progress.append(dict(at=at, students=len(students), assessed_students=len(evolving),
                knowledge_coverage=mean([evolving.get(r['id'], {}).get('knowledge_coverage',
                    next((p['knowledge_coverage'] for p in r['progress'] if p['at'] is None), 0)) for r in rows]),
                average_score=mean([p['average_score'] for p in evolving.values()])))
        selected = next((r for r in rows if r['id'] == student_id), None)
        facts = knowledge.get(student_id, {})
        scoped_history = [s for s in history if s['run_id'] == run_id and (not student_id or s['student_id'] == student_id)]
        return dict(run_id=run_id, run_name=Path(run['directory']).name, students=rows,
            assessment_count=sum(s['score'] is not None for s in scoped_history),
            answer_count=sum(s['answer_count'] for s in scoped_history),
            selected=selected, averages=averages, topics=topics, overlay=overlay,
            progress=class_progress, definitions=DEFINITIONS, knowledge=facts,
            state=display_state(graph, facts), graph=graph)

    def analytics(self, topics, student_id=None):
        students = self.students()
        selected = [s for s in students if not student_id or s["id"] == student_id]
        history = self.history(student_id)
        runs = {r["id"]: r for r in self.runs()}
        rows = []
        for topic in topics:
            sessions = [s for s in history if s['run_id'] == topic['id']]
            assessed = [s for s in sessions if s["score"] is not None]
            # Class scores weight students equally, using each student's latest
            # assessed session, rather than rewarding frequent quiz takers.
            latest = {}
            for session in sorted(assessed, key=lambda s: s["updated_at"]):
                latest[session["student_id"]] = session
            scores = [s["score"] for s in latest.values()]
            evolving, class_trend = {}, []
            for session in assessed:
                evolving[session["student_id"]] = session["score"]
                class_trend.append(dict(at=session["created_at"],
                    score=round(sum(evolving.values())/len(evolving), 1),
                    assessed_students=len(evolving)))
            coverage = []
            graph = runs[topic["id"]]["snapshot"]["graph"]
            for student in selected:
                facts = self.knowledge(student["id"], topic["id"], graph_only=True)
                coverage.append(dict(student_id=student["id"], assessed=len(facts),
                    independent=sum(f["mark"] == "match" and not f["helped"] for f in facts.values()),
                    assisted=sum(f["mark"] == "match" and f["helped"] for f in facts.values()),
                    partial=sum(f["mark"] == "related" for f in facts.values()),
                    unassessed=len(graph["edges"])-len(facts), total=len(graph["edges"])))
            rows.append(dict(**topic, score=round(sum(scores)/len(scores), 1) if scores else None,
                assessment_count=len(assessed), started_count=len(sessions),
                completed_count=sum(s["completed"] for s in sessions),
                answer_count=sum(s["answer_count"] for s in sessions),
                assessed_students=len(latest), unassessed_students=len(selected)-len(latest),
                assessment_status="assessed" if scores else "unassessed", coverage=coverage, class_trend=class_trend,
                trend=[dict(session_id=s["id"], student_id=s["student_id"], run_id=s["run_id"],
                            run_name=s["run_name"],
                            at=s["created_at"], score=s["score"], assisted_answers=s["assisted_answers"])
                       for s in assessed]))
        ranked = sorted((row for row in rows if row["score"] is not None), key=lambda row: row["score"])
        # Relative rankings avoid inventing a passing threshold. Unassessed
        # topics are separate suggestions to assess, never classified as weak.
        return dict(topics=rows, student_count=len(selected),
            assessment_count=sum(row["assessment_count"] for row in rows),
            answer_count=sum(row["answer_count"] for row in rows),
            strongest=[row["title"] for row in ranked if row["score"] == ranked[-1]["score"]] if ranked else [],
            weakest=[row["title"] for row in ranked if row["score"] == ranked[0]["score"]] if ranked else [],
            review_topics=[dict(title=row["title"], reason="Demonstrated gaps in assessed answers", score=row["score"])
                           for row in ranked if row["score"] < 100],
            unassessed=[row["title"] for row in rows if row["score"] is None])
