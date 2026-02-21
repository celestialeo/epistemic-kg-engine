import json
import re
from pathlib import Path
from collections import Counter

IN_PATH = Path("outputs/pilot_chunks_tagged.json")
OUT_PATH = Path("outputs/pilot_concepts.json")

STOP = set("""
the a an and or of to in for by with on at from this that are is be been will
module modules file files launch presentation window program project leader
each lecturer william ju storyline
""".split())

TITLE_PHRASE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,4})\b")


def norm_concept(s: str) -> str:
    # Option A: Concept id = normalized label string
    return " ".join(s.strip().lower().split())


def main():
    data = json.loads(IN_PATH.read_text(encoding="utf-8"))
    texts = [c["text"] for c in data["chunks"]]

    phrases = []
    for t in texts:
        for m in TITLE_PHRASE.finditer(t):
            phrase = m.group(1).strip()

            if phrase.lower().startswith("the "):
                continue
            if phrase.lower() in STOP:
                continue
            if len(phrase) < 4:
                continue

            phrases.append(phrase)

    counts = Counter(phrases)

    concepts = []
    for label, count in counts.most_common():
        cid = norm_concept(label)
        if cid in STOP or not cid:
            continue
        concepts.append(
            {
                "id": cid,              # <-- Option A
                "label": label,         # keep original casing for display
                "count": int(count),
            }
        )

    OUT_PATH.write_text(json.dumps({"concepts": concepts}, indent=2), encoding="utf-8")
    print(f"Extracted {len(concepts)} concept candidates to {OUT_PATH}")

    for c in concepts[:15]:
        print(c["count"], "-", c["label"], "=>", c["id"])


if __name__ == "__main__":
    main()
