"""Lossless native exports plus an explicit relational projection for evaluation."""
import hashlib
import json
import re


INDEX_TYPES = {"Chunk", "Doc", "Summary", "Outline", "AtomicQuery", "KnowledgeUnit", "SemanticConcept", "Table"}
INDEX_RELATIONS = {"similar", "semantictype", "officialname", "synonyms"}


def key(label, identifier):
    # Native identity is (type, id), not display name. No semantic deduplication.
    value = json.dumps([label, identifier], ensure_ascii=False, separators=(",", ":"))
    return "kag_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def graph_projection(snapshots, chunks, text, run_id, trace):
    nodes, edges, issues = {}, [], []
    for snapshot in snapshots:
        chunk_id = snapshot["chunk_id"]
        native = snapshot["graph"]
        for node in native["resultNodes"]:
            identifier = key(node["label"], node["id"])
            node_type = node["label"].rsplit(".", 1)[-1]
            kind = "chunk" if node_type == "Chunk" else "statement" if node_type in INDEX_TYPES else "event" if node_type == "Event" else "concept"
            if identifier not in nodes:
                nodes[identifier] = {"id": identifier, "label": node["name"], "kind": kind,
                                     "semantic_kind": node_type, "origin": "document",
                                     "kag_id": node["id"], "kag_type": node["label"],
                                     "native_occurrences": []}
            nodes[identifier]["native_occurrences"].append({"chunk_id": chunk_id, "node": node})

    # Resolve endpoints only after collecting nodes from every native subgraph.
    for snapshot in snapshots:
        chunk_id = snapshot["chunk_id"]
        native = snapshot["graph"]

        def endpoint(edge, side):
            identity = (edge[side + "Type"], edge[side])
            exact = key(*identity)
            if exact in nodes and not nodes[exact].get("unresolved_endpoint"):
                return exact
            # Do not silently repair an upstream type mismatch or invent a concept.
            # Preserve the edge with an explicitly unresolved endpoint in the viewer.
            if exact not in nodes:
                nodes[exact] = {"id": exact, "label": str(edge[side]), "kind": "statement",
                                "origin": "document", "kag_type": identity[0],
                                "kag_id": identity[1], "unresolved_endpoint": True}
            issues.append({"chunk_id": chunk_id, "edge_id": edge["id"],
                           "reason": "Native edge endpoint has no matching typed node", "endpoint": identity})
            return exact

        for native_edge in native["resultEdges"]:
            source, target = endpoint(native_edge, "from"), endpoint(native_edge, "to")
            props = native_edge.get("properties") or {}
            domain = all(nodes[n]["kind"] in {"concept", "event"} for n in (source, target))
            is_fact = domain and native_edge["label"].casefold() not in INDEX_RELATIONS
            edge = {"id": f"edge_{len(edges) + 1:05d}", "source": source, "target": target,
                    "label": native_edge["label"], "origin": "document" if is_fact else "kag_index",
                    "chunk_id": chunk_id, "conditions": props.get("condition", props.get("conditions")),
                    "modality": props.get("modality"), "definition": None,
                    "verification_basis": "upstream_kag_extraction", "native_edge": native_edge}
            edges.append(edge)
    graph = {"schema_version": 2, "run_id": run_id, "nodes": list(nodes.values()), "edges": edges,
             "provenance": {"text": text, "chunks": chunks},
             "projection": {"identity": "native type plus native id; no semantic merging",
                            "evaluation": "Document relations between concept/event nodes only",
                            "excluded_node_types": sorted(INDEX_TYPES),
                            "excluded_relation_labels": sorted(INDEX_RELATIONS),
                            "native_artifact": "artifacts/kag_graph.json"}}
    trace.save("artifacts/projection_issues.json", issues)
    trace.emit("graph.projected", nodes=len(nodes), edges=len(edges), issues=len(issues))
    return graph, issues


def native_union(snapshots):
    # An occurrence-preserving file export. No database upserts are performed.
    return {"resultNodes": [node for s in snapshots for node in s["graph"]["resultNodes"]],
            "resultEdges": [edge for s in snapshots for edge in s["graph"]["resultEdges"]],
            "note": "Per-chunk occurrences retained in local files. No database upserts or semantic merging."}


def paragraphs(text):
    result = []
    for match in re.finditer(r"\S[\s\S]*?(?=\r?\n[ \t]*\r?\n|\s*\Z)", text):
        source = match.group().rstrip()
        result.append({"id": f"paragraph_{len(result) + 1:03d}", "order": len(result),
                       "text": source, "start": match.start(), "end": match.start() + len(source)})
    return result
