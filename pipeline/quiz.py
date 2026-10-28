"""Five-question graph traversal with server-owned progress and answer mapping."""
from collections import Counter
import uuid

from .quiz_examiner import QuizExaminer
from .quiz_grading import learner_result


class QuizSession:
    LIMIT = 5

    def __init__(self, graph, page_id, models):
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
        for edge in self.edges.values():
            for identifier in {edge["source"], edge["target"]}:
                self.adjacent[identifier].append(edge)
        self.root = min(self.nodes, key=lambda n: (
            -sum(e["origin"] == "document" for e in self.adjacent[n]),
            self.nodes[n]["label"], n))
        self.focus = self.root
        self.round = 1
        self.number = 1
        self.completed = False
        self.edge_status = {}
        self.independent = set()
        self.assisted = set()
        self.revealed = set()
        self.asked = set()
        self.history = []
        self.last_result = None
        self.round_start_matches = set()
        self.question = self._question()

    def _unmapped(self, node):
        return [e for e in self.adjacent[node] if self.edge_status.get(e["id"]) != "match"]

    def _other(self, edge, node):
        return edge["target"] if edge["source"] == node else edge["source"]

    def _node_status(self):
        # Green endpoints are earned by a matched relationship, not a name mention.
        rank = {"related": 1, "conflict": 2, "match": 3}
        statuses = {}
        for identifier, status in self.edge_status.items():
            for node in (self.edges[identifier]["source"], self.edges[identifier]["target"]):
                if rank[status] > rank.get(statuses.get(node), 0):
                    statuses[node] = status
        return statuses

    def _question(self, number=None):
        number = self.number if number is None else number
        focus, fallback, targets = self.focus, None, []
        if number == 1:
            focus = self.root
            targets = list(self.adjacent[self.root])
        elif number in (2, 3):
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
        question_id = str(uuid.uuid4())
        # No traversal state changes until question generation and review succeed.
        generated = self.examiner.question(focus, [e["id"] for e in targets], number,
            self.questions, "quiz:" + self.id + ":" + question_id, fallback)
        self.focus = focus
        self.questions.append(generated["text"])
        if number in (2, 3):
            self.asked.update(e["id"] for e in targets)
        return dict(id=question_id, number=number, focus_id=focus,
                    target_ids=[e["id"] for e in targets], fallback=fallback,
                    attempts=0, hints=0, hint_history=[], revealed=False,
                    feedback=None, help_text=None, **generated)

    def _require_active(self, question_id):
        if self.completed:
            raise ValueError("This five-question session is complete. Choose Continue to start another five.")
        if str(question_id) != self.question["id"]:
            raise ValueError("This action refers to an older question. Refresh the quiz state.")

    def answer(self, text, question_id, matcher):
        self._require_active(question_id)
        # Only mutate progress after the entire model result passes validation.
        result = matcher.match(text, question=self.question["text"])
        helped = bool(self.question["hints"] or self.question["revealed"])
        # Preserve every statement citation, then combine this answer's verdicts.
        # An explicit contradiction cannot be hidden by another agreeing statement.
        assessed = {}
        rank = {"related": 1, "match": 2, "conflict": 3}
        for match in result["matches"]:
            identifier, status = match["id"], match["status"]
            if rank[status] > rank.get(assessed.get(identifier), 0):
                assessed[identifier] = status
        for identifier, status in assessed.items():
            self.edge_status[identifier] = status
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
        self.question["feedback"] = (
            f"This answer correctly explains {counts['match']} facts, partly explains "
            f"{counts['related']}, and contradicts {counts['conflict']}."
            if counts else "No credit yet. Write complete statements naming both things you are describing.")
        self.history.append(dict(action="answer", round=self.round, question_id=self.question["id"],
                                 number=self.number, text=text, helped=helped, result=result))
        self.last_result = result
        if self.number == self.LIMIT:
            self.completed = True
        return self.public()

    def hint(self, question_id):
        self._require_active(question_id)
        text = self.examiner.help(self.question, False,
            "quiz:" + self.id + ":" + self.question["id"] + ":hint:" + str(self.question["hints"] + 1))
        self.question["hints"] += 1
        self.question["hint_history"].append(text)
        self.question["help_text"] = text
        self.history.append(dict(action="hint", round=self.round, question_id=self.question["id"], text=text))
        return self.public()

    def reveal(self, question_id):
        self._require_active(question_id)
        text = self.examiner.help(self.question, True,
            "quiz:" + self.id + ":" + self.question["id"] + ":reveal")
        self.question["revealed"] = True
        self.question["help_text"] = text
        identifiers = [fact["id"] for fact in self.question["examiner_material"]["facts"]]
        self.revealed.update(identifiers)
        self.history.append(dict(action="reveal", round=self.round, question_id=self.question["id"],
                                 edge_ids=identifiers, text=text))
        return self.public()

    def advance(self, question_id):
        self._require_active(question_id)
        if not self.question["attempts"] and not self.question["revealed"]:
            raise ValueError("Answer or reveal this question before continuing")
        previous = dict(self.question)
        if self.number == self.LIMIT:
            self.completed = True
        else:
            question = self._question(self.number + 1)
            self.number += 1
            self.last_result = None
            self.question = question
        self.history.append(dict(action="question_completed", round=self.round, question=previous))
        return self.public()

    def continue_session(self):
        if not self.completed:
            raise ValueError("Finish the current five questions first")
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
                    question={k: self.question[k] for k in
                        ("id", "number", "text", "attempts", "hints", "revealed", "feedback", "help_text")},
                    edge_status=dict(self.edge_status), node_status=self._node_status(),
                    summary=self.summary(), last_result=learner_result(self.last_result))

    def saved(self):
        return dict(**self.public(), page_id=self.page_id, run_id=self.graph.get("run_id"),
                    root=self.root, question_internal=dict(self.question), history=self.history,
                    last_result_internal=self.last_result)

    def examiner_view(self):
        return dict(quiz_id=self.id, question=dict(self.question), assessment=self.last_result)
