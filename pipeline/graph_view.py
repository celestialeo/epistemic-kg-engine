"""Build a replayable graph and render its portable interactive view."""
import hashlib
import json
from pathlib import Path


def concept_id(name):
    return "concept_" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def build_graph(text, paragraphs, chunks, extractions, debate, trace, concepts=None, relations=None):
    nodes, edges = {}, []

    def node(identifier, label, kind, origin="document", **details):
        value = dict(id=identifier, label=label, kind=kind, origin=origin, **details)
        if identifier in nodes:
            old = nodes[identifier]
            value = {**old, **details}
            if old["origin"] != origin:
                value["origin"] = "both"
            if value != old:
                nodes[identifier] = value
                trace.emit("graph.node_updated", entity_id=identifier, node=value)
        else:
            nodes[identifier] = value
            trace.emit("graph.node_added", entity_id=identifier, node=value)
        return identifier

    def concept(name, origin="document"):
        entry = concepts.entries.get(name, {}) if concepts else {}
        return node(concept_id(name), name, "event" if entry.get("kind") == "event" else "concept", origin,
                    definition=entry.get("definition"), semantic_kind=entry.get("kind"),
                    form=entry.get("form", "concept"),
                    kind_detail=entry.get("kind_detail"), kind_details=entry.get("kind_details", []),
                    aliases=entry.get("aliases", []), alternative_definitions=entry.get("alternative_definitions", []))

    def edge(source, target, label, origin="document", **details):
        if source not in nodes or target not in nodes:
            raise ValueError("Dangling graph relationship")
        identifier = f"edge_{len(edges)+1:05d}"
        value = dict(id=identifier, source=source, target=target, label=label, origin=origin, **details)
        edges.append(value)
        trace.emit("graph.edge_added", entity_id=identifier, edge=value)

    for extraction in extractions:
        chunk_id = extraction["chunk_id"]
        for name in extraction["concepts"]:
            concept(name)
        for relation in extraction["relations"]:
            if not relation.get("accepted"):
                continue
            edge(concept(relation["source"]), concept(relation["target"]), relation["relation"],
                 chunk_id=chunk_id, evidence=relation["evidence"],
                 evidence_start=relation["evidence_start"], evidence_end=relation["evidence_end"],
                 candidate_id=relation["id"], definition=relation["relation_definition"],
                 supporting_evidence=relation.get("supporting_evidence", []),
                 conditions=relation.get("conditions"), modality=relation.get("modality"),
                 verification_basis=relation["verification_basis"])
    for row in debate["candidates"]:
        if row["accepted"]:
            edge(concept(row["source"], "background"), concept(row["target"], "background"),
                 row["relation"], "background", candidate_id=row["id"], chunk_id=row["chunk_id"],
                 score=row["score"], tier=row.get("tier", "related"), reason=row["decision_reason"],
                 conditions=row.get("conditions"), modality=row.get("modality"),
                 definition=row.get("relation_definition"), verification_basis=row.get("verification_basis", "model_knowledge"))
    graph = {"schema_version": 2, "run_id": trace.run_id, "nodes": list(nodes.values()), "edges": edges,
             "provenance": {"text": text, "paragraphs": paragraphs, "chunks": chunks,
                            "extractions": [{k: extraction[k] for k in
                                ("chunk_id", "concepts", "claims", "confidence", "unit_kind")}
                                for extraction in extractions]},
             "relation_registry": relations.vocabulary() if relations else []}
    trace.emit("graph.validated", node_count=len(nodes), edge_count=len(edges), dangling_edges=0)
    return graph


def render_graph(graph):
    payload = json.dumps(graph, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Path(__file__).with_name("graph_view.html").read_text(encoding="utf-8").replace("__GRAPH_DATA__", payload)
