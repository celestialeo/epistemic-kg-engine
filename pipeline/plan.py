"""Pure pipeline planning, independent of Neo4j and Ollama."""
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Step:
    name: str
    script: str
    args: tuple
    artifact: str = ""
    rows_key: str = ""


def build_plan(out: Path, model: str, embedding_model: str, count: int,
               source: str, background: bool, evaluate: bool, seed_limit: int):
    def path(name):
        return str(out / name)

    steps = []

    def add(name, script, args, artifact="", rows_key=""):
        steps.append(Step(name, script, tuple(map(str, args)), artifact, rows_key))

    add("extract", "langchain_extract_knowledgeunits.py",
        ["--in", path("chunks.json"), "--out", path("extractions.json"), "--model", model],
        "extractions.json", "extractions")
    add("build_mentions", "build_mentions_from_extractions.py",
        ["--in", path("extractions.json"), "--concepts-out", path("concepts.json"),
         "--mentions-out", path("mentions.json")], "mentions.json", "mentions")
    add("extract_relations", "extract_epistemic_relations.py",
        ["--in", path("extractions.json"), "--out", path("relations.json"), "--model", model],
        "relations.json", "relations")
    for name, script, flag, filename in [
        ("load_chunks", "load_chunks_to_neo4j.py", "--chunks", "chunks.json"),
        ("load_concepts", "load_concepts_to_neo4j.py", "--concepts", "concepts.json"),
        ("load_units", "load_kus_to_neo4j.py", "--extractions", "extractions.json"),
    ]:
        add(name, script, [flag, path(filename), "--source-type", source])
    add("load_mentions", "load_mentions_to_neo4j.py", ["--mentions", path("mentions.json")])
    add("load_relations", "load_epistemic_relations_to_neo4j.py",
        ["--relations", path("relations.json"), "--source-type", source])
    add("enrich_chunks", "enrich_chunks_in_neo4j.py", ["--extractions", path("extractions.json")])

    def evaluation(label, extra):
        add("evaluate_" + label, "evaluate_graph_fidelity.py",
            ["--out", path(label + ".json"), "--model", model,
             "--embedding-model", embedding_model, "--limit", count,
             "--source-type", source, *extra], label + ".json", "results")
        add("report_" + label, "report_fidelity.py",
            ["--in", path(label + ".json"), "--out", path(label + ".html"), "--title", label])

    relations = ["--include-relations", "--relation-policy", "auto"]
    if evaluate:
        evaluation("concepts_only", [])
        evaluation("document", relations)
    if background:
        add("select_seeds", "select_seed_concepts.py",
            ["--out", path("seeds.json"), "--limit", seed_limit, "--source-type", source],
            "seeds.json", "concepts")
        add("expand_background", "expand_background_knowledge.py",
            ["--in", path("seeds.json"), "--extractions", path("extractions.json"),
             "--out", path("background_candidates.json"), "--model", model],
            "background_candidates.json", "candidates")
        add("score_background", "score_background_candidates.py",
            ["--in", path("background_candidates.json"), "--out", path("background_approved.json"),
             "--model", model, "--use-critic"], "background_approved.json", "approved_edges")
        add("load_background", "load_background_to_neo4j.py",
            ["--in", path("background_approved.json"), "--with-facts"])
        if evaluate:
            evaluation("with_background", relations + ["--include-background"])
    if evaluate:
        labels = ["concepts_only", "document"] + (["with_background"] if background else [])
        comparisons = [arg for label in labels for arg in ("--run", label + "=" + path(label + ".json"))]
        add("compare", "compare_fidelity_runs.py", comparisons + ["--by-unit-kind"])
        add("hypothesis_test", "hypothesis_test_fidelity.py",
            ["--baseline", path("document.json" if background else "concepts_only.json"),
             "--candidate", path(labels[-1] + ".json"), "--by-unit-kind"])
    return steps
