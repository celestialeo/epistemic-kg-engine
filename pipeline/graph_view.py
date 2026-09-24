"""Render a portable, run-specific graph from saved artifacts, without services."""
import json
from pathlib import Path

from src.build_mentions_from_extractions import keep_concept, norm_concept


def build_graph(out):
    def rows(filename, key, optional=False):
        path = out / filename
        if optional and not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8-sig"))[key]

    nodes, edges = {}, []

    def node(key, label, kind, origin="document", **details):
        if key in nodes:
            if nodes[key]["origin"] != origin:
                nodes[key]["origin"] = "both"
        else:
            nodes[key] = dict(id=key, label=label, kind=kind, origin=origin, **details)
        return key

    def concept(name, origin="document", label=None):
        return node("concept:" + name, label or name, "concept", origin)

    def edge(source, target, label, origin="document", **details):
        if source in nodes and target in nodes:
            edges.append(dict(source=source, target=target, label=label, origin=origin, **details))

    chunks = rows("chunks.json", "chunks")
    for i, row in enumerate(chunks, 1):
        node(row["chunk_id"], f"Chunk {i}: {row['text']}", "chunk", text=row["text"],
             chunk_id=row.get("original_chunk_id", row["chunk_id"]))
    for a, b in zip(chunks, chunks[1:]):
        edge(a["chunk_id"], b["chunk_id"], "next")
    for row in rows("concepts.json", "concepts"):
        concept(row["id"], label=row.get("label"))
    for row in rows("extractions.json", "extractions"):
        if "error" in row:
            continue
        llm = row.get("llm", {})
        key = node("ku::" + row["chunk_id"], row["text"], "statement", text=row["text"],
                   unit_kind=llm.get("unit_kind"), confidence=llm.get("confidence"))
        edge(row["chunk_id"], key, "has statement")
        for name in llm.get("concepts", []):
            name = norm_concept(name)
            if keep_concept(name):
                edge(key, concept(name), "mentions")
    for row in rows("mentions.json", "mentions"):
        edge(row["from_chunk_id"], concept(row["to_concept"]), "mentions",
             confidence=row.get("confidence"))
    for row in rows("relations.json", "relations"):
        if "error" in row:
            continue
        key, rels = row["ku_id"], row.get("relations", {})
        for name in rels.get("defines", []):
            edge(key, concept(name), "defines", confidence=row.get("confidence"))
        for field, target, subject, label in [("part_of", "parent", "child", "part of"),
                                               ("causes", "effect", "cause", "causes")]:
            for rel in rels.get(field, []):
                if rel.get(target) and rel.get(subject):
                    edge(key, concept(rel[target]), label, subject=rel[subject],
                         confidence=row.get("confidence"))
    for row in rows("background_approved.json", "approved_edges", optional=True):
        # Background participation does not imply occurrence in the source text.
        source = concept(row["source_concept"], "background")
        target = concept(row["target_concept"], "background")
        score = next((row[k] for k in ("eigenvalue_weighted_score", "final_score", "proposer_confidence")
                      if row.get(k) is not None), None)
        edge(source, target, row["relation_type"].replace("_", " "), "background",
             justification=row.get("justification"), source_context=row.get("source_context"),
             score=score, critic_reason=row.get("critic_reason"),
             factscore=row.get("factscore"), evidence_accepted=row.get("evidence_accepted"),
             claim_checks=row.get("claim_checks"), checker_error=row.get("error"))
    return {"nodes": list(nodes.values()), "edges": edges}


def write_graph(out, run_id):
    graph = {"run_id": run_id, **build_graph(out)}
    # Embedded JSON must not be able to close its script element.
    payload = json.dumps(graph, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = Path(__file__).with_name("graph_view.html").read_text(encoding="utf-8")
    path = out / "knowledge_graph.html"
    path.write_text(template.replace("__GRAPH_DATA__", payload), encoding="utf-8")
    return path
