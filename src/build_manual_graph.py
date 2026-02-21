import networkx as nx
from pathlib import Path
import json

OUT_PATH = Path("outputs/manual_graph.json")

def main():
    G = nx.MultiDiGraph()

    # Nodes
    G.add_node("c_limit", type="Concept", label="Limit", source={"doc":"plp.pdf", "note":"manual"})
    G.add_node("c_derivative", type="Concept", label="Derivative", source={"doc":"plp.pdf", "note":"manual"})
    G.add_node("d_derivative", type="Definition", label="Definition of derivative", source={"doc":"plp.pdf", "note":"manual"})
    G.add_node("clm_diff_cont", type="Claim", label="Differentiable implies continuous", source={"doc":"plp.pdf", "note":"manual"})
    G.add_node("p1", type="ProofStep", label="Use definition of derivative (limit form)", source={"doc":"plp.pdf", "note":"manual"})

    # Edges (typed)
    G.add_edge("c_derivative", "c_limit", type="depends_on", evidence="Derivative defined using a limit", confidence=0.9)
    G.add_edge("c_derivative", "d_derivative", type="defined_by", evidence="Definition statement", confidence=0.95)
    G.add_edge("clm_diff_cont", "p1", type="supported_by", evidence="Proof step uses definition", confidence=0.7)
    G.add_edge("clm_diff_cont", "c_derivative", type="about", evidence="Claim uses differentiability", confidence=0.8)

    # Export
    data = {
        "nodes": [{ "id": n, **G.nodes[n] } for n in G.nodes],
        "edges": [
            { "source": u, "target": v, **attrs }
            for u, v, attrs in G.edges(data=True)
        ],
    }
    OUT_PATH.parent.mkdir(exist_ok=True, parents=True)
    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved graph to: {OUT_PATH}")

if __name__ == "__main__":
    main()
