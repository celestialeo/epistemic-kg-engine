"""Explicit event contracts shared by extraction, debate, and graph admission."""

EVENT_POLICY = (
    "Represent only happenings supported by the assertion. A process and its defining transformation "
    "are not two causally connected events. Distinguish general processes, particular occurrences, and "
    "their participants without inventing extra nodes. Use causal predicates only for genuinely distinct "
    "causes and effects. There is no mandatory acts_on companion. Preserve modality and conditions. "
)


def kind_error(relation, source_kind, target_kind):
    if relation == "causes" and target_kind not in {"event", "process"}:
        return "causes must target an event or process, not its affected object"
    if relation == "caused_by" and source_kind not in {"event", "process"}:
        return "caused_by must start at an event or process"
    if relation == "acts_on" and (source_kind not in {"event", "process"} or target_kind in {"event", "process"}):
        return "acts_on requires an event/process source and a non-event object target"
    return None

