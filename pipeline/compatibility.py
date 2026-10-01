"""Explicit replay migration; never used to loosen live generation validation."""
from typing import get_args
from .registry import ConceptKind


def legacy_endpoint(value):
    migrated = dict(value)
    if migrated.get("kind") not in get_args(ConceptKind):
        detail = migrated.get("kind")
        migrated["kind"] = "other"  # Unknown broad class, not an inferred classification.
        migrated["kind_detail"] = detail
    return migrated
