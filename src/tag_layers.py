import json
import re
from pathlib import Path
from typing import Dict, Any

IN_PATH = Path("outputs/pilot_chunks.json")
OUT_PATH = Path("outputs/pilot_chunks_tagged.json")

SUPPORT_PATTERNS = [
    r"\bdefinition\b", r"\bbackground\b", r"\bprerequisite\b", r"\breference\b",
    r"\bglossary\b", r"\bread more\b", r"\bfurther reading\b"
]

SCAFFOLD_PATTERNS = [
    r"\bexample\b", r"\bexercise\b", r"\bpractice\b", r"\bquiz\b", r"\bhint\b",
    r"\bstep\b", r"\btry\b", r"\bactivity\b", r"\bworksheet\b"
]

def match_any(text: str, patterns) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)

def tag_chunk(chunk: Dict[str, Any]) -> str:
    text = chunk["text"]

    # If it looks like support/scaffolding by keywords, tag that first
    if match_any(text, SCAFFOLD_PATTERNS):
        return "scaffolding"
    if match_any(text, SUPPORT_PATTERNS):
        return "support"

    # Heuristic defaults based on structure
    if chunk["type"] in {"h1", "h2", "h3"}:
        return "core"
    if chunk["type"] == "li":
        return "core"

    # Default fallback
    return "core"

def main():
    data = json.loads(IN_PATH.read_text(encoding="utf-8"))
    for c in data["chunks"]:
        c["layer"] = tag_chunk(c)

    OUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Saved tagged chunks to {OUT_PATH}")

if __name__ == "__main__":
    main()