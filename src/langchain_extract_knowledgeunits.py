import argparse
import json
import re
from pathlib import Path
from typing import List, Literal

from pydantic import BaseModel, Field

# Preferred (new) package
from langchain_ollama import ChatOllama


Layer = Literal["core", "support", "scaffolding"]
UnitKind = Literal["core_statement", "definition", "example", "metadata", "navigation", "other"]


class KUExtraction(BaseModel):
    layer: Layer = Field(description="Which layer this text belongs to: core/support/scaffolding")
    unit_kind: UnitKind = Field(description="What kind of knowledge unit this is")
    concepts: List[str] = Field(description="Key concept strings found in the text")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the extraction")


_ALLOWED_UNIT_KINDS = {"core_statement", "definition", "example", "metadata", "navigation", "other"}
_ALLOWED_LAYERS = {"core", "support", "scaffolding"}


def _salvage_first_json_object(s: str) -> str:
    """
    Extract the first {...} JSON object from a string, tolerant to extra text.
    """
    if not s:
        raise ValueError("Empty model response")
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    return s[start : end + 1]


def _normalize_llm_dict(d: dict) -> dict:
    """
    Make output robust to model drift (e.g., invalid unit_kind).
    """
    out = dict(d)

    layer = str(out.get("layer", "support")).strip().lower()
    if layer not in _ALLOWED_LAYERS:
        layer = "support"
    out["layer"] = layer

    unit_kind = str(out.get("unit_kind", "other")).strip().lower()
    if unit_kind not in _ALLOWED_UNIT_KINDS:
        unit_kind = "other"
    out["unit_kind"] = unit_kind

    concepts = out.get("concepts", [])
    if not isinstance(concepts, list):
        concepts = []
    # normalize concepts lightly
    out["concepts"] = [str(c).strip() for c in concepts if str(c).strip()]

    conf = out.get("confidence", 0.5)
    try:
        conf = float(conf)
    except Exception:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    out["confidence"] = conf

    return out


def make_prompt(text: str) -> str:
    return (
        "You are extracting structured knowledge from a text chunk.\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        "layer: one of [core, support, scaffolding]\n"
        "unit_kind: one of [core_statement, definition, example, metadata, navigation, other]\n"
        "concepts: a list of short noun phrases\n"
        "confidence: number from 0 to 1\n\n"
        f"TEXT:\n{text}\n"
    )


def main():
    parser = argparse.ArgumentParser(description="Extract structured knowledge units using LangChain + Ollama.")
    parser.add_argument("--in", dest="in_path", required=True, help="Input chunks JSON (with key 'chunks').")
    parser.add_argument("--out", dest="out_path", required=True, help="Output extractions JSON.")
    parser.add_argument("--model", default="llama3.2:3b", help="Ollama model name, e.g. llama3.2:3b")
    parser.add_argument("--limit", type=int, default=0, help="Optional: limit number of chunks processed (0 = all).")
    args = parser.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)

    data = json.loads(in_path.read_text(encoding="utf-8"))
    chunks = data["chunks"]
    if args.limit and args.limit > 0:
        chunks = chunks[: args.limit]

    llm = ChatOllama(model=args.model, temperature=0)

    results = []
    total = len(chunks)

    for i, ch in enumerate(chunks, start=1):
        chunk_id = ch.get("chunk_id", f"chunk_{i:04d}")
        text = ch.get("text", "")

        prompt = make_prompt(text)

        try:
            resp = llm.invoke(prompt)
            raw = getattr(resp, "content", str(resp))
            raw_json = _salvage_first_json_object(raw)

            # validate through pydantic (after normalization)
            parsed_dict = json.loads(raw_json)
            parsed_dict = _normalize_llm_dict(parsed_dict)
            extracted = KUExtraction.model_validate(parsed_dict)

            results.append(
                {
                    "chunk_id": chunk_id,
                    "text": text,
                    "llm": extracted.model_dump(),
                }
            )
            print(f"[{i}/{total}] ok chunk={chunk_id}")

        except Exception as e:
            results.append({"chunk_id": chunk_id, "text": text, "error": str(e)})
            print(f"[{i}/{total}] ERROR chunk={chunk_id} -> {e}")

    out_path.write_text(json.dumps({"extractions": results}, indent=2), encoding="utf-8")
    print(f"Saved LangChain/Ollama extractions to {out_path}")


if __name__ == "__main__":
    main()
