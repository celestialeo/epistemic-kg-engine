"""Topic-independent retrieval. Ranking proposes candidates; it never merges them."""
from collections import Counter
from difflib import SequenceMatcher
import math
import re


def tokens(text):
    return re.findall(r'[^\W_]+', str(text).casefold())


def shortlist(query, entries, limit, *, name_field='name', preferred=None):
    entries = list(entries)
    if not entries:
        return []
    query_tokens = set(tokens(query))
    documents = [set(tokens(str(e.get(name_field, '')) + ' ' + str(e.get('definition', '')))) for e in entries]
    frequency = Counter(t for document in documents for t in document)
    def score(pair):
        index, entry = pair
        name = str(entry.get(name_field, ''))
        overlap = sum(math.log(1 + len(entries) / frequency[t]) for t in query_tokens & documents[index])
        lexical = SequenceMatcher(None, str(query).casefold(), name.casefold()).ratio()
        return (name == preferred, overlap, lexical, -index)
    ranked = [entry for _, entry in sorted(enumerate(entries), key=score, reverse=True)]
    # A retrieval ceiling limits identity work, not source facts. Unmatched
    # concepts and predicates retain separate identities with their own checks.
    return ranked[:limit] if limit else ranked
