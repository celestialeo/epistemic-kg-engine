if "<html" not in html.lower() and "<!doctype" not in html.lower():
    raise ValueError("pilot.html does not look like HTML. Check how it was saved (use wget/curl or View Page Source).")

from bs4 import BeautifulSoup
from pathlib import Path
import json
import re
from typing import List, Dict, Any

HTML_PATH = Path("data/html/pilot.html")
OUT_PATH = Path("outputs/pilot_chunks.json")

def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s

def main() -> None:
    if not HTML_PATH.exists():
        raise FileNotFoundError(f"Missing {HTML_PATH}. Save your pilot HTML to data/html/pilot.html")

    html = HTML_PATH.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")

    # Try to focus on the main content if present; fall back to body
    main = soup.find("main") or soup.find("article") or soup.body or soup

    chunks: List[Dict[str, Any]] = []
    idx = 0

    # Extract headings/paragraphs/list items in reading order
    for el in main.find_all(["h1","h2","h3","h4","h5","h6","p","li"], recursive=True):
        text = clean_text(el.get_text(" ", strip=True))
        if not text:
            continue

        chunks.append({
            "chunk_id": f"chunk_{idx:04d}",
            "type": el.name,                 # h2, p, li, ...
            "text": text,
            "provenance": {
                "source_file": str(HTML_PATH),
                "css_path_hint": el.name,     # simple hint; upgrade later if needed
            }
        })
        idx += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "pilot_file": str(HTML_PATH),
        "num_chunks": len(chunks),
        "chunks": chunks
    }, indent=2), encoding="utf-8")

    print(f"Saved {len(chunks)} chunks to {OUT_PATH}")

if __name__ == "__main__":
    main()