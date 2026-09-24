import json
from pathlib import Path
import tempfile
import unittest

from pipeline.graph_view import build_graph, write_graph


class GraphViewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        fixtures = {
            "chunks": {"chunks": [{"chunk_id": "run::1", "text": "A neuron transmits signals."}]},
            "concepts": {"concepts": [{"id": "neuron", "label": "Neuron"}]},
            "extractions": {"extractions": [{"chunk_id": "run::1", "text": "A neuron transmits signals.",
                                             "llm": {"concepts": ["neuron"]}}]},
            "mentions": {"mentions": [{"from_chunk_id": "run::1", "to_concept": "neuron"}]},
            "relations": {"relations": [{"ku_id": "ku::run::1", "relations": {"defines": ["neuron"]}}]},
            "background_approved": {"approved_edges": [
                {"source_concept": "neuron", "target_concept": "cell", "relation_type": "is_a",
                 "justification": "A neuron is a cell.", "eigenvalue_weighted_score": 0.7232},
                {"source_concept": "cell", "target_concept": "organism", "relation_type": "part_of"}]},
        }
        for name, data in fixtures.items():
            (self.out / (name + ".json")).write_text(json.dumps(data), encoding="utf-8")

    def test_provenance_and_background_details(self):
        graph = build_graph(self.out)
        nodes = {n["id"]: n for n in graph["nodes"]}
        self.assertEqual(nodes["concept:neuron"]["origin"], "both")
        self.assertEqual(nodes["concept:neuron"]["label"], "Neuron")
        self.assertEqual(nodes["concept:cell"]["origin"], "background")
        self.assertEqual(nodes["concept:organism"]["origin"], "background")
        self.assertTrue(all(e["source"] in nodes and e["target"] in nodes for e in graph["edges"]))
        background = [e for e in graph["edges"] if e["origin"] == "background"]
        self.assertEqual(background[0]["score"], 0.7232)
        self.assertEqual(background[0]["justification"], "A neuron is a cell.")

    def test_document_only_run(self):
        (self.out / "background_approved.json").unlink()
        graph = build_graph(self.out)
        self.assertTrue(all(n["origin"] == "document" for n in graph["nodes"]))
        self.assertTrue(any(e["label"] == "defines" for e in graph["edges"]))

    def test_embedded_data_cannot_close_script(self):
        malicious = '</script><script>alert("test")</script>'
        path = write_graph(self.out, malicious)
        page = path.read_text(encoding="utf-8")
        self.assertNotIn(malicious, page)
        payload = page.split('<script type="application/json" id="graph-data">')[1].split('</script>')[0]
        self.assertEqual(json.loads(payload)["run_id"], malicious)


if __name__ == "__main__":
    unittest.main()
