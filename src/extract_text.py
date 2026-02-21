import fitz  # PyMuPDF
from pathlib import Path

PDF_PATH = Path("data/plp.pdf")
OUT_PATH = Path("data/plp_extracted.txt")

def main():
    doc = fitz.open(PDF_PATH)
    text = []
    for page in doc:
        text.append(page.get_text())
    OUT_PATH.write_text("\n\n".join(text), encoding="utf-8")
    print(f"Saved extracted text to: {OUT_PATH}")

if __name__ == "__main__":
    main()
