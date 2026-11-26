"""Lossless paragraph and sentence boundaries, in source reading order."""
import re


def split_document(text, max_words, trace):
    if max_words < 1:
        raise ValueError("max_words must be positive")
    if not text.strip():
        raise ValueError("Input document is empty")
    paragraphs, chunks = [], []
    # Offsets are Unicode character offsets into the saved input.txt, end-exclusive.
    for match in re.finditer(r"\S[\s\S]*?(?=\r?\n[ \t]*\r?\n|\s*\Z)", text):
        start, end = match.span()
        while end > start and text[end - 1].isspace():
            end -= 1
        if end <= start:
            continue
        paragraph = dict(id=f"paragraph_{len(paragraphs)+1:03d}", order=len(paragraphs),
                         start=start, end=end, text=text[start:end])
        paragraphs.append(paragraph)
        trace.emit("input.paragraph_parsed", entity_id=paragraph["id"], **paragraph)
        # End sentences at punctuation followed by whitespace; a long sentence is
        # split at word boundaries. No overlaps, reordering, or paraphrasing.
        boundaries = [start] + [start + m.end() for m in re.finditer(r"(?<=[.!?])\s+", text[start:end])] + [end]
        units = []
        for left, right in zip(boundaries, boundaries[1:]):
            words = list(re.finditer(r"\S+", text[left:right]))
            for offset in range(0, len(words), max_words):
                batch = words[offset:offset + max_words]
                units.append((left + batch[0].start(), left + batch[-1].end(), len(batch)))
        trace.emit("input.sentences_parsed", entity_id=paragraph["id"], boundaries=boundaries, units=units)
        groups = []
        for left, right, count in units:
            if groups and groups[-1][2] + count <= max_words:
                groups[-1] = (groups[-1][0], right, groups[-1][2] + count)
            else:
                groups.append((left, right, count))
        for left, right, count in groups:
            chunk = dict(id=f"chunk_{len(chunks)+1:03d}", order=len(chunks), paragraph_id=paragraph["id"],
                         start=left, end=right, text=text[left:right], word_count=count,
                         previous_id=chunks[-1]["id"] if chunks else None)
            chunks.append(chunk)
            trace.emit("input.chunk_created", entity_id=chunk["id"], **chunk)
    if " ".join(text.split()) != " ".join(" ".join(c["text"] for c in chunks).split()):
        raise ValueError("Chunking lost or duplicated source content")
    trace.emit("input.coverage_validated", paragraph_count=len(paragraphs), chunk_count=len(chunks),
               word_count=len(text.split()), coverage=1.0)
    return paragraphs, chunks
