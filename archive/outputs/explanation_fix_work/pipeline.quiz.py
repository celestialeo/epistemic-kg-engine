"""Input-sized graph traversal with server-owned progress and answer mapping."""
from .settings import setting
from collections import Counter
import uuid

from .quiz_examiner import QuizExaminer
from .quiz_grading import assess_rubric, learner_result


class QuizSession:
    LEGACY_ROUND_LIMIT = 5  # Saved checkpoints before limits were recorded used this protocol.

    def __init__(self, graph, page_id, models, *, focus_id=None, prior_status=None,
                 prior_knowledge=None, adaptive=False, review_mode=False):
        self.graph = graph
        self.examiner = QuizExaminer(models, graph)
        self.questions = []
        self.id = str(uuid.uuid4())
        self.page_id = str(page_id)
        self.nodes = {n["id"]: n for n in graph["nodes"]}
        self.edges = {e["id"]: e for e in graph["edges"]}
        if not self.nodes:
            raise ValueError("This graph has no concepts to quiz")
        self.adjacent = {identifier: [] for identifier in self.nodes}
        from .graph_quality import edge_node_ids
        for edge in self.edges.values():
            for identifier in edge_node_ids(edge):
                self.adjacent[identifier].append(edge)
        self.root = min(self.nodes, key=lambda n: (
            -sum(e["origin"] == "document" for e in self.adjacent[n]),
            self.nodes[n]["label"], n))
        if focus_id is not None:
            if focus_id not in self.nodes:
                raise ValueError("The selected topic is not in this graph")
            self.root = focus_id
        self.focus = self.root
        self.round = 1
        self.number = 1
        self.completed = False
        self.adaptive = adaptive
        self.review_mode = review_mode
        self.completion_reason = None
        self.examiner.approvals = graph.get('_quiz_approvals', {})
        self.edge_status = {k: v for k, v in (prior_status or {}).items()
                            if k in self.edges and v in {"match", "related", "conflict"}}
        self.independent = set()
        self.assisted = set()
        self.revealed = set()
        self.asked = set()
        self.deferred_facts = set()
        self.generation_skips = []
        self.history = []
        self.last_result = None
        self.round_start_matches = set()
        if prior_knowledge is not None:
            self.edge_status = {k: ('related' if v['mark'] == 'match' and v['helped'] else v['mark'])
                                for k, v in prior_knowledge.items() if k in self.edges}
            self.independent = {k for k, v in prior_knowledge.items()
                                if k in self.edges and v['mark'] == 'match' and not v['helped']}
            self.assisted = {k for k, v in prior_knowledge.items()
                             if k in self.edges and v['mark'] == 'match' and v['helped']}
            self.round_start_matches = set(self.independent)
        if adaptive and not self._eligible():
            raise ValueError('No eligible unmastered facts remain. Choose another topic, enable review for known facts, or approve background facts in Run Insights.')
        self.LIMIT = setting('ui', 'quiz_round_questions') or max(1, len(self._eligible()))
        self.FOCUS_QUESTIONS = setting('ui', 'quiz_focus_questions')
        self.question = self._question()

    def checkpoint(self):
        """JSON-safe runtime state; restored without asking a new question."""
        keys = ("id", "page_id", "questions", "root", "focus", "round", "number",
                "completed", "edge_status", "history", "last_result", "question",
                "adaptive", "review_mode", "completion_reason", "LIMIT", "FOCUS_QUESTIONS")
        return {'graph_snapshot': self.graph, 'deferred_facts': sorted(self.deferred_facts), 'generation_skips': self.generation_skips, 'scope_run_ids': getattr(self, 'scope_run_ids', None), **{key: getattr(self, key) for key in keys},
                **{key: sorted(getattr(self, key)) for key in
                   ("independent", "assisted", "revealed", "asked", "round_start_matches")}}

    @classmethod
    def restore(cls, graph, models, checkpoint):
        session = cls.__new__(cls)
        session.graph = graph
        session.examiner = QuizExaminer(models, graph)
        session.examiner.approvals = graph.get('_quiz_approvals', {})
        session.nodes = {n["id"]: n for n in graph["nodes"]}
        session.edges = {e["id"]: e for e in graph["edges"]}
        session.adjacent = {identifier: [] for identifier in session.nodes}
        from .graph_quality import edge_node_ids
        for edge in session.edges.values():
            for identifier in edge_node_ids(edge):
                session.adjacent[identifier].append(edge)
        for key in ("id", "page_id", "questions", "root", "focus", "round", "number",
                    "completed", "edge_status", "history", "last_result", "question"):
            setattr(session, key, checkpoint[key])
        for key in ("independent", "assisted", "revealed", "asked", "round_start_matches"):
            setattr(session, key, set(checkpoint[key]))
        session.adaptive = checkpoint.get('adaptive', False)
        session.review_mode = checkpoint.get('review_mode', False)
        session.scope_run_ids = checkpoint.get('scope_run_ids')
        session.deferred_facts = set(checkpoint.get('deferred_facts', []))
        session.generation_skips = checkpoint.get('generation_skips', [])
        session.completion_reason = checkpoint.get('completion_reason')
        session.LIMIT = checkpoint.get('LIMIT', cls.LEGACY_ROUND_LIMIT)
        session.FOCUS_QUESTIONS = checkpoint.get('FOCUS_QUESTIONS', 2)  # Historical traversal protocol.
        return session

    def _eligible(self):
        from .assessment import eligible_fact
        return [e for e in self.edges.values() if eligible_fact(e, self.examiner.approvals) and e['id'] not in self.deferred_facts and
                (self.review_mode or (e['id'] not in self.asked and e['id'] not in self.independent))]

    def _unmapped(self, node):
        return [e for e in self.adjacent[node] if self.edge_status.get(e["id"]) != "match"]

    def _other(self, edge, node):
        return edge["target"] if edge["source"] == node else edge["source"]

    def _node_status(self):
        if self.adaptive:
            from .knowledge import learning_node_status
            return learning_node_status(self.graph, self.edge_status)
        # Green endpoints are earned by a matched relationship, not a name mention.
        rank = {"not_demonstrated": 1, "related": 2, "conflict": 3, "match": 4}
        statuses = {}
        for identifier, status in self.edge_status.items():
            for node in (self.edges[identifier]["source"], self.edges[identifier]["target"]):
                if rank[status] > rank.get(statuses.get(node), 0):
                    statuses[node] = status
        return statuses

    def _question(self, number=None):
        number = self.number if number is None else number
        focus, fallback, targets = self.focus, None, []
        if self.adaptive:
            return self._adaptive_question(number)
        elif number == 1:
            focus = self.root
            targets = list(self.adjacent[self.root])
        elif 1 < number <= 1 + self.FOCUS_QUESTIONS:
            focus = self.root
            candidates = self._unmapped(self.root)
            if not candidates:
                candidates = self.adjacent[self.root]
                fallback = "review_already_covered_material"
            fresh = [edge for edge in candidates if edge["id"] not in self.asked]
            candidates = fresh or candidates
            if candidates:
                edge = min(candidates, key=lambda e: (
                    -len(self.adjacent[self._other(e, self.root)]),
                    self.nodes[self._other(e, self.root)]["label"], e["id"]))
                neighbor = self._other(edge, self.root)
                targets = [e for e in candidates if self._other(e, self.root) == neighbor]
            else:
                fallback = "review_subject_definition"
        else:
            statuses = self._node_status()
            neighbors = {self._other(e, focus) for e in self.adjacent[focus]} - {focus}
            green = [n for n in neighbors if statuses.get(n) == "match"]
            if green:
                focus = min(green, key=lambda n: (
                    -len(self._unmapped(n)), -len(self.adjacent[n]), self.nodes[n]["label"], n))
            else:
                fallback = "reinforce_current_subject"
            targets = self._unmapped(focus)
            if not targets:
                targets = list(self.adjacent[focus])
                fallback = fallback or "review_already_covered_material"
        from .assessment import eligible_fact
        targets = [e for e in targets if eligible_fact(e, self.examiner.approvals)]
        if not targets:
            from .quiz_examiner import QuestionGenerationError
            raise QuestionGenerationError('No eligible facts at this focus. Review background material in Run Insights or choose another concept.')
        question_id = str(uuid.uuid4())
        # No traversal state changes until question generation and review succeed.
        generated = self.examiner.question(focus, [e["id"] for e in targets], number,
            self.questions, "quiz:" + self.id + ":" + question_id, fallback)
        self.focus = focus
        self.questions.append(generated["text"])
        if self.adaptive or 1 < number <= 1 + self.FOCUS_QUESTIONS:
            self.asked.update(e["id"] for e in targets)
        return dict(id=question_id, number=number, focus_id=focus,
                    target_ids=[e["id"] for e in targets], fallback=fallback,
                    attempts=0, hints=0, hint_history=[], revealed=False,
                    feedback=None, help_text=None, **generated)

    def _adaptive_question(self, number):
        from .models import ModelResponseError
        from .quiz_examiner import QuestionGenerationError
        candidates = self._eligible()
        if not candidates:
            raise ValueError('No unmastered facts remain in this round. Choose another topic or start a new quiz.')
        known_nodes = {n for key in self.independent for n in
                       (self.edges[key]['source'], self.edges[key]['target'])}
        candidates.sort(key=lambda e: (
            e['id'] in self.independent, e['id'] in self.asked,
            self.focus not in (e['source'], e['target']), e['origin'] != 'document',
            e['id'] in self.edge_status, not bool({e['source'], e['target']} & known_nodes)))
        skipped = []
        for edge in candidates:
            focus = self.focus if self.focus in (edge['source'], edge['target']) else edge['source']
            question_id = str(uuid.uuid4())
            fallback = 'independent_review' if edge['id'] in self.independent else 'assess_unmastered_fact'
            try:
                generated = self.examiner.question(focus, [edge['id']], number,
                    self.questions, 'quiz:' + self.id + ':' + question_id, fallback)
            except ModelResponseError as exc:
                skipped.append(dict(fact_id=edge['id'], reason=str(exc)))
                continue
            # Failed drafts never count as assessed or asked. Defer them only
            # after another reviewed question succeeds; retry in a future quiz.
            self.deferred_facts.update(item['fact_id'] for item in skipped)
            self.generation_skips.extend(skipped)
            self.focus = focus
            self.questions.append(generated['text'])
            self.asked.add(edge['id'])
            return dict(id=question_id, number=number, focus_id=focus,
                        target_ids=[edge['id']], fallback=fallback,
                        attempts=0, hints=0, hint_history=[], revealed=False,
                        feedback=None, help_text=None, **generated)
        raise QuestionGenerationError(
            "Couldn't generate a suitable question from the selected material. "
            "Existing progress is unchanged. Try another starting concept or topic. "
            "Rejected drafts remain in the run's explorer logs.")

    def question_mastered(self):
        ids = self.question.get('target_ids', [])
        return self.adaptive and not self.review_mode and bool(ids) and all(key in self.independent for key in ids)

    def _require_material(self):
        from .assessment import eligible_fact
        from .models import ModelResponseError
        if any(not eligible_fact(self.edges[f['id']],self.examiner.approvals)
               for f in self.question['examiner_material']['facts']):
            raise ModelResponseError('Background material needs professor approval in Run Insights before quiz use. Existing progress is unchanged.')

    def _require_active(self, question_id):
        if self.completed:
            raise ValueError("This round is complete. Choose Continue to start another round.")
        if str(question_id) != self.question["id"]:
            raise ValueError("This action refers to an older question. Refresh the quiz state.")

    def answer(self, text, question_id, matcher):
        self._require_active(question_id)
        from .assessment import validate_spec, mastery_marks, eligible_fact, SPEC_RULES, validate_graph_consistency
        from .quiz_grading import QuizGrader
        from .quiz_examiner import ExamQuestion, QuestionReview, validate_review
        from .models import ModelResponseError
        question = dict(self.question)
        facts = question['examiner_material']['facts']
        if any(not eligible_fact(self.edges[f['id']], self.examiner.approvals) for f in facts):
            raise ModelResponseError('Assessment unresolved: background facts require professor approval in Run Insights; the saved answer is retained.')
        # Legacy active questions are reviewed without rewriting the saved question.
        if 'assessment_spec' not in question:
            def validate_legacy(draft):
                if draft.question != question['text'] or draft.expected_answer != question['expected_answer'] or set(draft.assessed_fact_ids)!={f['id'] for f in facts}:
                    raise ValueError('Preserve the exact saved question, expected answer and assessed fact IDs; only add the specification')
                validate_spec([c.model_dump() for c in draft.assessment_spec], [f['id'] for f in facts])
            draft = matcher.models.ask('quiz_legacy_spec',
                'Preserve question, expected_answer and assessed_fact_ids exactly. Supply only a defensible assessment_spec. '+SPEC_RULES,
                dict(question=question['text'],expected_answer=question['expected_answer'],material=question['examiner_material']),
                ExamQuestion, 'legacy-spec:'+self.id+':'+str(question_id), validator=validate_legacy)
            if draft.question != question['text'] or draft.expected_answer != question['expected_answer'] or set(draft.assessed_fact_ids)!={f['id'] for f in facts}:
                raise ModelResponseError('Legacy assessment specification changed the saved question or scope')
            review = matcher.models.ask('quiz_question_review',
                'Review this saved question and its specification. '+SPEC_RULES,
                dict(material=question['examiner_material'],**draft.model_dump()), QuestionReview,
                'legacy-spec-review:'+self.id+':'+str(question_id), validator=lambda r:validate_review(r,draft.question))
            if not (review.specification_aligned and review.grounded_in_material and review.open_question and review.plain_exam_language and not review.reveals_answer):
                raise ModelResponseError('Saved assessment specification remains unresolved: '+review.reason)
            question['assessment_spec']=[c.model_dump() for c in draft.assessment_spec]
        question['assessment_spec']=validate_spec(question['assessment_spec'],[f['id'] for f in facts])
        contextual = question.get('grading_policy') == 'contextual_v3'
        question['assessment_version'] = 3 if contextual else 2
        if contextual:
            from .quiz_grading import assess_contextual
            result = assess_contextual(matcher.models, question, text)
        else:
            grader = getattr(matcher, 'quiz_grader', None) or QuizGrader(self.graph, matcher.models)
            statements = grader.statements(text, question['text'])
            result = dict(input=text, statements=statements, matches=[], uncredited=[], judgments=[], checked_records=0,
                          assessment_version=2, assessment_spec=question['assessment_spec'])
            # Question grading never depends on whole-graph matching.
            result['rubric'] = assess_rubric(matcher.models, question, result)
            try:
                mapped = grader.match(text, question['text'], statements=statements)
                result.update({key:mapped[key] for key in ('matches','uncredited','judgments','checked_records')})
                validate_graph_consistency(result)
                result['graph_assessment'] = dict(status='resolved')
            except Exception as exc:
                result['graph_assessment'] = dict(status='unresolved', error=str(exc))
        assessed = mastery_marks(question, result)
        result['mastery_marks'] = assessed
        self.question = question
        helped = bool(self.question["hints"] or self.question["revealed"])
        # Preserve every statement citation, then combine this answer's verdicts.
        # An explicit contradiction cannot be hidden by another agreeing statement.
        for identifier, status in assessed.items():
            if self.adaptive and identifier in self.independent:
                # Scores still record this answer. Existing independent mastery
                # is retained; professor corrections replay effective evidence.
                continue
            self.edge_status[identifier] = 'related' if self.adaptive and helped and status == 'match' else status
            if self.adaptive:
                self.independent.discard(identifier)
                self.assisted.discard(identifier)
            if status == "match":
                if helped:
                    self.assisted.add(identifier)
                else:
                    self.independent.add(identifier)
            else:
                self.independent.discard(identifier)
                self.assisted.discard(identifier)
        self.question["attempts"] += 1
        counts = Counter(assessed.values())
        mapping = (f"Relationship progress: {counts['match']} supported, {counts['related']} related, "
                   f"{counts['conflict']} contradicted.")
        labels = {"complete": "Complete", "partial": "Partly answered",
                  "contradiction": "Contradiction", "not_demonstrated": "Not demonstrated"}
        feedback = [labels[item["status"]] + ": " + item["demonstrated"] +
                    (" Still missing: " + item["missing"] if item["missing"] else "")
                    for item in result["rubric"]]
        if result['graph_assessment']['status']=='unresolved':
            mapping = 'Question graded. Graph matching is unresolved; relationship progress is unchanged. Retry graph matching from answer history.'
        else:
            mapping += (' Correct component answers count toward the question score, not full relationship mastery.' if any(c['scope']=='component' for c in question['assessment_spec']) else ' Green: independent understanding. Yellow: partial or assisted. Red: contradicted or not demonstrated.')
        self.question["feedback"] = mapping + "\n" + "\n".join(feedback)
        self.history.append(dict(action="answer", round=self.round, question_id=self.question["id"],
                                 number=self.number, text=text, helped=helped, result=result))
        self.last_result = result
        if self.number == self.LIMIT:
            self.completed = True
        return self.public()

    def hint(self, question_id):
        self._require_active(question_id)
        self._require_material()
        if self.question_mastered():
            raise ValueError('This material is already green. Continue to another question.')
        text = self.examiner.help(self.question, False,
            "quiz:" + self.id + ":" + self.question["id"] + ":hint:" + str(self.question["hints"] + 1))
        self.question["hints"] += 1
        self.question["hint_history"].append(text)
        self.question["help_text"] = text
        self.question["help_source"] = getattr(self.examiner, "last_help_source", None)
        self.history.append(dict(action="hint", round=self.round, question_id=self.question["id"], text=text))
        return self.public()

    def reveal(self, question_id):
        self._require_active(question_id)
        self._require_material()
        if self.question_mastered():
            raise ValueError('This material is already green. Continue to another question.')
        text = self.examiner.help(self.question, True,
            "quiz:" + self.id + ":" + self.question["id"] + ":reveal")
        self.question["revealed"] = True
        self.question["help_text"] = text
        self.question["help_source"] = getattr(self.examiner, "last_help_source", None)
        identifiers = [fact["id"] for fact in self.question["examiner_material"]["facts"]]
        self.revealed.update(identifiers)
        self.history.append(dict(action="reveal", round=self.round, question_id=self.question["id"],
                                 edge_ids=identifiers, text=text))
        return self.public()

    def advance(self, question_id):
        self._require_active(question_id)
        if not self.question["attempts"] and not self.question["revealed"] and not self.question_mastered():
            raise ValueError("Answer or reveal this question before continuing")
        previous = dict(self.question)
        if self.number == self.LIMIT or (self.adaptive and not self._eligible()):
            self.completed = True
            if self.adaptive:
                self.completion_reason = ('This round is complete. Some facts were deferred because a suitable question could not be generated; they remain unassessed or retain their previous state.' if self.deferred_facts else 'This round is complete. Green facts stay known; start another quiz to revisit yellow or other remaining gaps.')
        else:
            question = self._question(self.number + 1)
            self.number += 1
            self.last_result = None
            self.question = question
        self.history.append(dict(action="question_completed", round=self.round, question=previous))
        return self.public()

    def continue_session(self):
        if not self.completed:
            raise ValueError("Finish the current round first")
        question = self._question(1)
        self.history.append(dict(action="session_completed", round=self.round, summary=self.summary()))
        self.round_start_matches = {i for i, status in self.edge_status.items() if status == "match"}
        self.round += 1
        self.number = 1
        self.completed = False
        self.asked.clear()
        self.last_result = None
        self.question = question
        return self.public()

    def summary(self):
        counts = Counter(self.edge_status.values())
        matched = {i for i, status in self.edge_status.items() if status == "match"}
        return dict(total_relationships=len(self.edges), matched=counts["match"], partial=counts["related"],
                    contradicted=counts["conflict"], untouched=len(self.edges)-len(self.edge_status),
                    unmapped=len(self.edges)-len(matched),
                    coverage_percent=round(100 * len(matched) / len(self.edges), 1) if self.edges else 0,
                    newly_mapped=len(matched-self.round_start_matches),
                    independent=len(matched & self.independent),
                    assisted=len((matched & self.assisted)-self.independent), revealed=len(self.revealed),
                    document_matched=sum(self.edges[i]["origin"] == "document" for i in matched),
                    document_total=sum(e["origin"] == "document" for e in self.edges.values()),
                    background_matched=sum(self.edges[i]["origin"] == "background" for i in matched),
                    background_total=sum(e["origin"] == "background" for e in self.edges.values()))

    def public(self):
        return dict(quiz_id=self.id, round=self.round, limit=self.LIMIT, completed=self.completed,
                    completion_reason=self.completion_reason, question_mastered=self.question_mastered(), generation_skips=list(self.generation_skips),
                    question={**{k: self.question[k] for k in
                        ("id", "number", "text", "attempts", "hints", "revealed", "feedback", "help_text")}, "help_source": self.question.get("help_source")},
                    edge_status=dict(self.edge_status), node_status=self._node_status(),
                    summary=self.summary(), last_result=learner_result(self.last_result))

    def saved(self):
        return dict(**self.public(), page_id=self.page_id, run_id=self.graph.get("run_id"),
                    root=self.root, question_internal=dict(self.question), history=self.history,
                    last_result_internal=self.last_result)

    def examiner_view(self):
        return dict(quiz_id=self.id, question=dict(self.question), assessment=self.last_result)
