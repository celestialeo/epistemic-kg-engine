"""Domain-independent, name-only concept identity for English source material."""
from .settings import setting
from functools import lru_cache
import re
import unicodedata


@lru_cache(maxsize=setting('operations', 'definition_cache_entries'))
def concept_key(value):
    """Normalize spelling presentation, never guess number or semantic identity.

    Inferring singular forms from isolated words can corrupt valid terms. Number
    and synonym equivalence require the registry's contextual identity checks.
    """
    value = unicodedata.normalize("NFKC", value).casefold()
    # Remove only the old registry's machine-generated sense suffix on import.
    value = re.sub(r"\s*\([0-9a-f]{8}\)\s*$", "", value)
    value = re.sub(r"(?<=\w)['’](?=\w)", "", value)
    words = re.findall(r"[^\W_]+", value, flags=re.UNICODE)
    key = " ".join(words)
    if not key:
        raise ValueError("A concept name must contain letters or numbers")
    return key


def short_definition(value):
    """Keep one short definition; relationship records carry contextual detail."""
    text = " ".join((value or "").split())
    text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    limit = setting('text', 'display_definition_chars')
    suffix = '...'
    return text if len(text) <= limit else text[:max(0, limit-len(suffix))].rsplit(" ", 1)[0] + suffix
