import argparse
import json
from pathlib import Path
from typing import List, Literal, Dict, Any

from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama


RelationType = Literal["is_a", "has_part", "requires_understanding_of"]


def norm_concept(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


class BackgroundEdge(BaseModel):
    relation_type: RelationType
    target_concept: str = Field(description="Target background concept")
    justification: str = Field(description="Short explanation of why this background concept is relevant")
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class BackgroundExpansion(BaseModel):
    source_concept: str
    background_concepts: List[str] = Field(default_factory=list)
    edges: List[BackgroundEdge] = Field(default_factory=list)
    summary: str = ""


def salvage_first_json(s: str) -> str:
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    return s[start:end + 1]


def make_prompt(concept: str) -> str:
    return (
        "You are expanding a scientific knowledge graph with background knowledge.\n"
        "Given a source concept, identify prerequisite background concepts and relations needed to understand it.\n\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        "source_concept: string\n"
        "background_concepts: list of short noun phrases\n"
        "edges: list of objects with keys:\n"
        "  relation_type: one of [is_a, has_part, requires_understanding_of]\n"
        "  target_concept: short noun phrase\n"
        "  justification: short explanation\n"
        "  confidence: number from 0 to 1\n"
        "summary: short summary string\n\n"
        "Rules:\n"
        "- Prefer educational prerequisite concepts.\n"
        "- Keep concepts short and specific.\n"
        "- Do not include the source concept itself as a target.\n"
        "- Return at most 5 background concepts.\n"
        "- If unsure, return fewer edges.\n\n"
        f"SOURCE CONCEPT:\n{concept}\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Generate background-knowledge candidates for concepts.")
    parser.add_argument("--in", dest="in_path", required=True, help="Input seed concepts JSON.")
    parser.add_argument("--out", dest="out_path", required=True, help="Output background candidates JSON.")
    parser.add_argument("--model", default="llama3.2:3b", help="Ollama model name.")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N concepts (0=all).")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    concepts = data.get("concepts", [])
    if args.limit and args.limit > 0:
        concepts = concepts[:args.limit]

    llm = ChatOllama(model=args.model, temperature=0)

    out: List[Dict[str, Any]] = []
    total = len(concepts)

    for i, row in enumerate(concepts, start=1):
        concept = norm_concept(row.get("id", ""))
        if not concept:
            continue

        try:
            resp = llm.invoke(make_prompt(concept))
            raw = getattr(resp, "content", str(resp))
            raw_json = salvage_first_json(raw)
            parsed = json.loads(raw_json)
            validated = BackgroundExpansion.model_validate(parsed)

            source_concept = norm_concept(validated.source_concept) or concept
            bg_concepts = sorted(
                {norm_concept(c) for c in validated.background_concepts if norm_concept(c) and norm_concept(c) != source_concept}
            )

            edges = []
            seen = set()
            for e in validated.edges:
                target = norm_concept(e.target_concept)
                if not target or target == source_concept:
                    continue
                key = (e.relation_type, target)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    {
                        "relation_type": e.relation_type,
                        "target_concept": target,
                        "justification": str(e.justification).strip(),
                        "confidence": float(e.confidence),
                    }
                )

            out.append(
                {
                    "source_concept": source_concept,
                    "background_concepts": bg_concepts,
                    "edges": edges,
                    "summary": str(validated.summary).strip(),
                }
            )
            print(f"[{i}/{total}] ok concept={source_concept}")

        except Exception as e:
            out.append(
                {
                    "source_concept": concept,
                    "error": str(e),
                }
            )
            print(f"[{i}/{total}] ERROR concept={concept} -> {e}")

    out_path.write_text(json.dumps({"candidates": out}, indent=2), encoding="utf-8")
    print(f"Saved background candidates to {out_path}")


if __name__ == "__main__":
    main()