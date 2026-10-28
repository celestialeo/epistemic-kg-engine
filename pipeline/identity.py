"""Domain-independent, name-only concept identity for English source material."""
from functools import lru_cache
import re
import threading
import unicodedata

import inflect

_inflector = inflect.engine()
_lock = threading.Lock()


@lru_cache(maxsize=32768)
def concept_key(value):
    """Ignore case/punctuation/number, never consult definitions or context."""
    value = unicodedata.normalize("NFKC", value).casefold()
    # Remove only the old registry's machine-generated sense suffix on import.
    value = re.sub(r"\s*\([0-9a-f]{8}\)\s*$", "", value)
    value = re.sub(r"(?<=\w)['’](?=\w)", "", value)
    words = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    with _lock:
        words = [str(_inflector.singular_noun(word) or word) if word.isalpha() else word
                 for word in words]
    key = " ".join(words)
    if not key:
        raise ValueError("A concept name must contain letters or numbers")
    return key


def short_definition(value):
    """Keep one short definition; relationship records carry contextual detail."""
    text = " ".join((value or "").split())
    text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return text if len(text) <= 240 else text[:237].rsplit(" ", 1)[0] + "..."
