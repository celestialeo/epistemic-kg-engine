"""Quiz evidence and semantic mapping, exercising the real model retry boundary."""
import copy
import json
import re
import unittest
from unittest.mock import Mock

from pipeline.models import Models, ModelResponseError, ModelServiceError
from pipeline.quiz_grading import QuizGrader


def graph_fixture():
    return dict(nodes=[
        dict(id="a", label="photovoltaic cell", definition="A device that converts light into electrical energy."),
        dict(id="b", label="electricity", definition="Electrical energy."),
        dict(id="c", label="conductor", definition="A material that permits electric current to flow.")],
        edges=[dict(id="e1", source="a", target="b", label="produces", definition="Converts light to electrical energy."),
               dict(id="e2", source="c", target="b", label="conducts", definition="Permits electric current to flow.")])


def judgment(**changes):
    return dict(dict(statement_id="statement_1", edge_id="e1", meaning="equivalent",
                     asserts_relation=True, source_identified=True, target_identified=True,
                     source_quote="PV cells", target_quote="electrical energy", relation_quote="make",
                     reason="The cited device and energy denote the supplied endpoints."), **changes)


def statements(text, assertion=True):
    return dict(statements=[dict(text=text, is_assertion=assertion)])


def repair(text, **changes):
    """Model response fixture selecting token spans rather than rewriting quotes."""
    value = judgment(**changes)
    tokens = list(re.finditer(r'\w+|[^\w\s]', text))
    for name in ('source', 'target', 'relation'):
        quote = value.pop(name + '_quote')
        if not quote:
            value[name + '_span'] = None
        elif quote not in text:
            value[name + '_span'] = dict(start_token=len(tokens), end_token=len(tokens))
        else:
            start = text.index(quote)
            value[name + '_span'] = dict(
                start_token=next(i for i,t in enumerate(tokens) if t.start() == start),
                end_token=next(i for i,t in enumerate(tokens) if t.end() == start + len(quote)))
    return value


def models_with(*outputs):
    trace = Mock(run_id="test")
    trace.emit.return_value = "event"
    models = Models(trace, "fixture", "fixture", "http://127.0.0.1:11434",
                    context_tokens=16384, max_output_tokens=4096)
    responses = []
    for output in outputs:
        if isinstance(output, Exception):
            responses.append(output)
        else:
            response = Mock()
            response.model_dump.return_value = dict(message=dict(content=json.dumps(output)), done_reason="stop")
            responses.append(response)
    models.client = Mock()
    models.client.chat.side_effect = responses
    return models


class QuizGradingTests(unittest.TestCase):
    def setUp(self):
        self.text = "PV cells make electrical energy."
        self.graph = graph_fixture()

    def test_semantic_endpoint_and_relation_paraphrases_map_existing_ids(self):
        original = copy.deepcopy(self.graph)
        models = models_with(statements(self.text), dict(judgments=[judgment()]))
        result = QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual([(m["id"], m["status"]) for m in result["matches"]], [("e1", "match")])
        self.assertEqual(result["matches"][0]["source_quote"], "PV cells")
        self.assertEqual(result["matches"][0]["target_quote"], "electrical energy")
        prompt = models.client.chat.call_args_list[1].kwargs["messages"][0]["content"]
        self.assertIn(self.graph["nodes"][0]["definition"], prompt)
        self.assertEqual(self.graph, original)

    def test_unrelated_invalid_quotes_cannot_abort_a_valid_match(self):
        unrelated = judgment(edge_id="e2", meaning="unrelated", asserts_relation=False,
                             source_quote="conductor", target_quote="not in the answer")
        models = models_with(statements(self.text), dict(judgments=[judgment(), unrelated]))
        result = QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual([m["id"] for m in result["matches"]], ["e1"])
        self.assertEqual(models.client.chat.call_count, 2)

    def test_only_invalid_relevant_judgment_is_retried(self):
        text = "PV cells make electrical energy; conducting material carries electrical energy."
        valid = judgment()
        invalid = judgment(edge_id="e2", source_quote="conductor", relation_quote="conducts")
        repaired = repair(text, edge_id="e2", source_quote="conducting material", relation_quote="carries")
        models = models_with(statements(text), dict(judgments=[valid, invalid]), dict(judgments=[repaired]))
        result = QuizGrader(self.graph, models).match(text, "Explain energy production and flow.")
        self.assertEqual([m["id"] for m in result["matches"]], ["e1", "e2"])
        prompt = models.client.chat.call_args_list[2].kwargs["messages"][0]["content"]
        payload = json.loads(prompt.split("\nDATA:\n")[1])
        self.assertEqual([f["id"] for f in payload["facts"]], ["e2"])
        self.assertEqual({c['field']: c['quote'] for c in payload['invalid_citations']},
                         {'source_quote': 'conductor', 'relation_quote': 'conducts'})
        self.assertEqual(payload['statement']['text'], text)
        self.assertNotIn('invalid_judgment', payload)
        self.assertEqual(models.client.chat.call_count, 3)

    def test_question_quotes_are_repaired_from_exact_answer_with_reassessed_meaning(self):
        question = 'How do photovoltaic cells produce electricity?'
        invalid = judgment(source_quote='photovoltaic cells', target_quote='electricity', relation_quote='produce')
        # Even the first repair is invalid. Its new bad field must be identified
        # by the retry validator, rather than accepting or reusing its verdict.
        bad_repair = repair(self.text, relation_quote='produce')
        reassessed = repair(self.text, meaning='similar')
        models = models_with(statements(self.text), dict(judgments=[invalid]),
                             dict(judgments=[bad_repair]), dict(judgments=[reassessed]))
        result = QuizGrader(self.graph, models).match(self.text, question)
        self.assertEqual([(m['id'], m['status']) for m in result['matches']], [('e1', 'related')])
        for field in ('source_quote', 'target_quote', 'relation_quote'):
            self.assertIn(result['matches'][0][field], self.text)
        repair_prompt = models.client.chat.call_args_list[2].kwargs['messages'][0]['content']
        payload = json.loads(repair_prompt.split('\nDATA:\n')[1])
        self.assertEqual(payload['question'], question)
        self.assertEqual(payload['statement']['text'], self.text)
        self.assertEqual([f['id'] for f in payload['facts']], ['e1'])
        self.assertEqual({c['field']: c['quote'] for c in payload['invalid_citations']},
                         {field: invalid[field] for field in ('source_quote', 'target_quote', 'relation_quote')})
        self.assertTrue(all('does not occur verbatim' in c['problem'] for c in payload['invalid_citations']))
        self.assertIn('reassess the judgment from scratch', repair_prompt)
        self.assertNotIn('invalid_judgment', payload)
        retry_prompt = models.client.chat.call_args_list[3].kwargs['messages'][0]['content']
        feedback = retry_prompt.split('Previous response failed validation: ')[1]
        self.assertIn('relation_span', feedback)
        self.assertIn('learner token indices', feedback)
        self.assertNotIn('target_span', feedback)
        self.assertEqual(models.client.chat.call_count, 4)

    def test_repair_cannot_quote_graph_reference_instead_of_learner(self):
        invalid = dict(judgments=[judgment(source_quote='photovoltaic cell')])
        # Exact reference label, but not an exact learner quote. All attempts fail.
        invalid_repair = dict(judgments=[repair(self.text, source_quote='photovoltaic cell')])
        models = models_with(statements(self.text), invalid, invalid_repair, invalid_repair, invalid_repair)
        with self.assertRaisesRegex(ModelResponseError, 'source_span'):
            QuizGrader(self.graph, models).match(self.text, 'Explain the conversion.')
        self.assertEqual(models.client.chat.call_count, 5)

    def test_repair_cannot_change_statement_or_fact_identity(self):
        for changes in [dict(statement_id='statement_2'), dict(edge_id='e2')]:
            with self.subTest(changes=changes):
                invalid = dict(judgments=[judgment(target_quote='electricity')])
                replacement = dict(judgments=[repair(self.text, **changes)])
                models = models_with(statements(self.text), invalid, replacement, replacement, replacement)
                with self.assertRaises(ModelResponseError):
                    QuizGrader(self.graph, models).match(self.text, 'Explain the conversion.')

    def test_selected_repair_spans_preserve_original_whitespace(self):
        text = 'PV cells\tmake  electrical energy.'
        invalid = dict(judgments=[judgment(relation_quote='produce electricity')])
        selected = repair(text)
        selected['relation_span'] = dict(start_token=2, end_token=4)
        models = models_with(statements(text), invalid, dict(judgments=[selected]))
        result = QuizGrader(self.graph, models).match(text, 'How do cells produce electricity?')
        self.assertEqual(result['matches'][0]['relation_quote'], 'make  electrical energy')

    def test_empty_or_reversed_repair_spans_cannot_receive_credit(self):
        for span in [None, dict(start_token=4, end_token=3)]:
            with self.subTest(span=span):
                invalid = dict(judgments=[judgment(target_quote='electricity')])
                selected = repair(self.text)
                selected['target_span'] = span
                replacement = dict(judgments=[selected])
                models = models_with(statements(self.text), invalid, replacement, replacement, replacement)
                with self.assertRaisesRegex(ModelResponseError, 'verbatim'):
                    QuizGrader(self.graph, models).match(self.text, 'Explain the conversion.')

    def test_exhausted_citation_repairs_raise_instead_of_assigning_zero(self):
        invalid = dict(judgments=[judgment(source_quote="photovoltaic cell")])
        invalid_repair = dict(judgments=[repair(self.text, source_quote='photovoltaic cell')])
        models = models_with(statements(self.text), invalid, invalid_repair, invalid_repair, invalid_repair)
        with self.assertRaisesRegex(ModelResponseError, "verbatim"):
            QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual(models.client.chat.call_count, 5)

    def test_empty_repair_is_not_treated_as_a_negative_grade(self):
        invalid = dict(judgments=[judgment(target_quote="electricity")])
        empty = dict(judgments=[])
        models = models_with(statements(self.text), invalid, empty, empty, empty)
        with self.assertRaisesRegex(ModelResponseError, "exactly one judgment"):
            QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")

    def test_repair_may_resolve_judgment_as_unrelated(self):
        invalid = dict(judgments=[judgment(source_quote="invented")])
        models = models_with(statements(self.text), invalid,
                             dict(judgments=[repair(self.text, meaning="unrelated", source_quote="", target_quote="")]))
        result = QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual(result["matches"], [])

    def test_ambiguous_or_unasserted_endpoints_do_not_earn_credit(self):
        for changes in [dict(source_identified=False), dict(target_identified=False), dict(asserts_relation=False)]:
            with self.subTest(changes=changes):
                models = models_with(statements(self.text), dict(judgments=[judgment(**changes)]))
                result = QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
                self.assertEqual(result["matches"], [])
                self.assertEqual(len(result["uncredited"]), 1)

    def test_a_single_mention_cannot_supply_both_endpoints(self):
        invalid = dict(judgments=[judgment(target_quote="PV cells")])
        invalid_repair = dict(judgments=[repair(self.text, target_quote='PV cells')])
        models = models_with(statements(self.text), invalid, invalid_repair, invalid_repair, invalid_repair)
        with self.assertRaisesRegex(ModelResponseError, "non-overlapping"):
            QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual(models.client.chat.call_count, 5)

    def test_overlapping_verbatim_quotes_are_repaired_before_rejecting_match(self):
        invalid = dict(judgments=[judgment(source_quote=self.text)])
        models = models_with(statements(self.text), invalid, dict(judgments=[repair(self.text)]))
        result = QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual([m["id"] for m in result["matches"]], ["e1"])
        self.assertEqual(result["matches"][0]["source_quote"], "PV cells")
        self.assertEqual(result["matches"][0]["target_quote"], "electrical energy")
        self.assertEqual(models.client.chat.call_count, 3)

    def test_relation_evidence_cannot_just_repeat_entity(self):
        invalid = dict(judgments=[judgment(relation_quote="PV cells")])
        models = models_with(statements(self.text), invalid, dict(judgments=[repair(self.text)]))
        result = QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual(result["matches"][0]["relation_quote"], "make")
        self.assertEqual(models.client.chat.call_count, 3)

    def test_citations_cannot_be_borrowed_from_another_sentence(self):
        text = self.text + " It makes electricity."
        parsed = dict(statements=[dict(text=self.text, is_assertion=True),
                                 dict(text="It makes electricity.", is_assertion=True)])
        invalid = dict(judgments=[judgment(target_quote="electricity")])
        invalid_repair = dict(judgments=[repair(self.text, target_quote='electricity')])
        models = models_with(parsed, invalid, invalid_repair, invalid_repair, invalid_repair)
        with self.assertRaisesRegex(ModelResponseError, "verbatim"):
            QuizGrader(self.graph, models).match(text, "Explain the conversion.")

    def test_nonassertions_do_not_map_edges(self):
        models = models_with(statements("PV cells?", assertion=False))
        result = QuizGrader(self.graph, models).match("PV cells?", "Explain the conversion.")
        self.assertEqual(result["matches"], [])
        self.assertEqual(models.client.chat.call_count, 1)

    def test_partial_and_contradictory_meanings_are_preserved(self):
        for meaning, status in [("similar", "related"), ("contradiction", "conflict")]:
            with self.subTest(meaning=meaning):
                models = models_with(statements(self.text), dict(judgments=[judgment(meaning=meaning)]))
                result = QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
                self.assertEqual(result["matches"][0]["status"], status)

    def test_unknown_ids_are_rejected_even_for_unrelated_judgments(self):
        self.graph["edges"] = self.graph["edges"][:1]
        for changes in [dict(edge_id="invented"), dict(statement_id="statement_99")]:
            with self.subTest(changes=changes):
                invalid = dict(judgments=[judgment(meaning="unrelated", **changes)])
                models = models_with(statements(self.text), invalid, invalid, invalid)
                with self.assertRaisesRegex(ModelResponseError, "supplied fact ID"):
                    QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")

    def test_service_failure_does_not_trigger_batch_splitting(self):
        models = models_with(statements(self.text), RuntimeError("Service unavailable"))
        with self.assertRaises(ModelServiceError):
            QuizGrader(self.graph, models).match(self.text, "Explain the conversion.")
        self.assertEqual(models.client.chat.call_count, 2)


if __name__ == "__main__":
    unittest.main()
