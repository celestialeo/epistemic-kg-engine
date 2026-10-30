"""Build a replayable graph and render its portable interactive view."""
import hashlib
import json
from pathlib import Path
from .identity import concept_key, short_definition
from .records import normalize


def concept_id(name):
    return "concept_" + hashlib.sha256(concept_key(name).encode("utf-8")).hexdigest()[:16]


def canonicalize_graph(graph):
    """Final name/edge safeguard, also used to display legacy saved graphs."""
    nodes, redirects, edges = {}, {}, {}
    for old in sorted(graph["nodes"], key=lambda n: n.get("origin") == "background"):
        name = concept_key(old.get("label") or old["name"])
        identifier = concept_id(name)
        redirects[old["id"]] = identifier
        origin = "background" if old.get("origin") == "background" else "document"
        nodes.setdefault(identifier, dict(id=identifier, label=name, kind="concept",
            definition=short_definition(old.get("definition")), origin=origin))
        if not nodes[identifier]["definition"]:
            nodes[identifier]["definition"] = short_definition(old.get("definition"))
        if origin == "document":
            nodes[identifier]["origin"] = "document"
    contracts = {row["key"]: row for row in graph.get("relation_registry", [])}
    for old in sorted(graph["edges"], key=lambda e: e.get("origin") == "background"):
        edge = dict(old, source=redirects[old["source"]], target=redirects[old["target"]],
                    origin="background" if old.get("origin") == "background" else "document")
        if edge["origin"] == "document":
            for endpoint in (edge["source"], edge["target"]):
                nodes[endpoint]["origin"] = "document"
        source, target, label = edge["source"], edge["target"], edge["label"]
        forms = [(source, label, target)]
        spec = contracts.get(label, {})
        if spec.get("symmetric"):
            forms.append((target, label, source))
        if spec.get("inverse"):
            forms.append((target, spec["inverse"], source))
        key = (*min(forms), normalize(edge.get("conditions") or ""), normalize(edge.get("modality") or ""))
        if key not in edges:
            edges[key] = edge
            edge["supporting_evidence"] = list(edge.get("supporting_evidence", []))
        survivor = edges[key]
        # Keep every document quote/chunk after collapsing duplicate edges.
        if edge["origin"] == "document":
            supports = list(edge.get("supporting_evidence", []))
            if edge.get("evidence"):
                supports.append({k: edge[k] for k in
                    ("chunk_id", "evidence", "evidence_start", "evidence_end") if k in edge})
            for support in supports:
                if support not in survivor["supporting_evidence"]:
                    survivor["supporting_evidence"].append(support)
    return {**graph, "schema_version": 3, "identity_policy": "normalized_name_only",
            "nodes": list(nodes.values()), "edges": list(edges.values())}


def build_graph(text, paragraphs, chunks, extractions, debate, trace, concepts=None, relations=None):
    nodes, edges = {}, []

    def node(identifier, label, kind, origin="document", **details):
        value = dict(id=identifier, label=label, kind=kind, origin=origin, **details)
        if identifier in nodes:
            old = nodes[identifier]
            value = {**old, **details}
            if old["origin"] != origin:
                value["origin"] = "document" if "document" in (old["origin"], origin) else "background"
            if value != old:
                nodes[identifier] = value
                trace.emit("graph.node_updated", entity_id=identifier, node=value)
        else:
            nodes[identifier] = value
            trace.emit("graph.node_added", entity_id=identifier, node=value)
        return identifier

    def concept(name, origin="document"):
        name = concept_key(name)
        entry = concepts.entries.get(name, {}) if concepts else {}
        return node(concept_id(name), name, "concept", origin,
                    definition=short_definition(entry.get("definition")))

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
                 intended_fact=row.get("intended_fact"), link_reading=row.get("link_reading"),
                 repair_of=row.get("repair_of"), seed_id=row.get("seed_id"), gap_ids=row.get("gap_ids", []),
                 definition=row.get("relation_definition"), verification_basis=row.get("verification_basis", "model_knowledge"))
    graph = {"schema_version": 3, "run_id": trace.run_id, "nodes": list(nodes.values()), "edges": edges,
             "provenance": {"text": text, "paragraphs": paragraphs, "chunks": chunks,
                            "extractions": [{k: extraction[k] for k in
                                ("chunk_id", "concepts", "claims", "confidence", "unit_kind")}
                                for extraction in extractions]},
             "relation_registry": relations.vocabulary() if relations else []}
    graph = canonicalize_graph(graph)
    trace.emit("graph.canonicalized", identity_policy=graph["identity_policy"],
               nodes_removed=len(nodes)-len(graph["nodes"]), edges_removed=len(edges)-len(graph["edges"]))
    trace.emit("graph.validated", node_count=len(graph["nodes"]), edge_count=len(graph["edges"]), dangling_edges=0)
    return graph


def render_graph(graph):
    payload = json.dumps(graph, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Path(__file__).with_name("graph_view.html").read_text(encoding="utf-8").replace("__GRAPH_DATA__", payload)
