import argparse
import json
from pathlib import Path
from typing import List, Literal, Dict, Any

from pydantic import BaseModel, Field
from langchain_ollama import ChatOllama

RelationType = Literal["defines", "part_of", "causes"]


def norm_concept(s: str) -> str:
    return " ".join(str(s).strip().lower().split())


class PartOfPair(BaseModel):
    child: str = Field(description="The part (child) concept")
    parent: str = Field(description="The whole (parent) concept")


class CausesPair(BaseModel):
    cause: str = Field(description="Cause concept")
    effect: str = Field(description="Effect concept")


class RelationExtraction(BaseModel):
    defines: List[str] = Field(default_factory=list, description="Concepts defined by this KU.")
    part_of: List[PartOfPair] = Field(default_factory=list, description="Part-of relations mentioned in this KU.")
    causes: List[CausesPair] = Field(default_factory=list, description="Causal relations mentioned in this KU.")
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


def make_prompt(text: str) -> str:
    return (
        "Extract epistemic relations from the text.\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        "defines: list of concept strings that are being defined\n"
        "part_of: list of {child, parent} concept pairs (X is part of Y)\n"
        "causes: list of {cause, effect} concept pairs (X causes Y)\n"
        "confidence: number from 0 to 1\n\n"
        "Rules:\n"
        "- Use short noun phrases for concepts.\n"
        "- If no relation exists, return empty lists.\n\n"
        f"TEXT:\n{text}\n"
    )


def salvage_first_json(s: str) -> str:
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in response")
    return s[start : end + 1]


def main():
    p = argparse.ArgumentParser(description="Extract DEFINES/PART_OF/CAUSES from extractions JSON.")
    p.add_argument("--in", dest="in_path", required=True, help="Input extractions JSON (key: 'extractions').")
    p.add_argument("--out", dest="out_path", required=True, help="Output relations JSON.")
    p.add_argument("--model", default="llama3.2:3b", help="Ollama model name.")
    p.add_argument("--limit", type=int, default=0, help="Process only first N rows (0=all).")
    args = p.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    rows = data["extractions"]
    if args.limit and args.limit > 0:
        rows = rows[: args.limit]

    llm = ChatOllama(model=args.model, temperature=0)

    out: List[Dict[str, Any]] = []
    total = len(rows)

    for i, r in enumerate(rows, start=1):
        chunk_id = r.get("chunk_id")
        text = r.get("text", "")

        if "error" in r:
            out.append({"chunk_id": chunk_id, "error": r["error"]})
            continue

        try:
            resp = llm.invoke(make_prompt(text))
            raw = getattr(resp, "content", str(resp))
            raw_json = salvage_first_json(raw)

            parsed = json.loads(raw_json)
            validated = RelationExtraction.model_validate(parsed)

            # normalize concepts
            defines = [norm_concept(x) for x in validated.defines if norm_concept(x)]
            part_of = [{"child": norm_concept(p.child), "parent": norm_concept(p.parent)} for p in validated.part_of
                       if norm_concept(p.child) and norm_concept(p.parent)]
            causes = [{"cause": norm_concept(c.cause), "effect": norm_concept(c.effect)} for c in validated.causes
                      if norm_concept(c.cause) and norm_concept(c.effect)]

            out.append({
                "chunk_id": chunk_id,
                "ku_id": f"ku::{chunk_id}",
                "relations": {
                    "defines": sorted(set(defines)),
                    "part_of": part_of,
                    "causes": causes,
                },
                "confidence": float(validated.confidence),
            })
            print(f"[{i}/{total}] ok chunk={chunk_id}")

        except Exception as e:
            out.append({"chunk_id": chunk_id, "ku_id": f"ku::{chunk_id}", "error": str(e)})
            print(f"[{i}/{total}] ERROR chunk={chunk_id} -> {e}")

    out_path.write_text(json.dumps({"relations": out}, indent=2), encoding="utf-8")
    print(f"Saved relations to {out_path}")


if __name__ == "__main__":
    main()