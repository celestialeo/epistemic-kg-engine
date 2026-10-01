"""Shared strict records and text normalization."""
from pydantic import BaseModel, ConfigDict
import re
import unicodedata


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def normalize(value):
    return " ".join(value.casefold().split())


def normalize_name(value):
    """Orthographic normalization only; semantic and number identity is verified."""
    value = unicodedata.normalize("NFKC", value)
    return normalize(re.sub(r"[_\u2010-\u2015-]+", " ", value))


def name_variants(value):
    """Retrieve singular/plural candidates, never authorize a semantic merge."""
    name = re.sub(r" \([0-9a-f]{8}\)$", "", normalize_name(value))
    tokens = name.split()
    variants = {name}
    for index, word in enumerate(tokens):
        stems = set()
        if word.endswith("s") and not word.endswith(("ss", "us", "is")):
            stems.add(word[:-1])
        if word.endswith("es"):
            stems.add(word[:-2])
        if word.endswith("ies"):
            stems.add(word[:-3] + "y")
        for stem in stems:
            if stem:
                variants.add(" ".join(tokens[:index] + [stem] + tokens[index+1:]))
    return variants


def name_occurs(name, text):
    """Ground a canonical spelling against inflected surface forms in a unit."""
    words = re.findall(r"\w+", normalize_name(name))
    source = re.findall(r"\w+", normalize_name(text))
    variants = name_variants(" ".join(words))
    return bool(words) and any(variants & name_variants(" ".join(source[i:i+len(words)]))
                              for i in range(len(source)-len(words)+1))


def batches(items, size=12):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start:start + size]
