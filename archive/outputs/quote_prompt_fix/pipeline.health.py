from .settings import setting
"""Stop systematic failures, not normal duplicate/no-match decisions."""
from collections import defaultdict, deque


class HealthFailure(RuntimeError):
    pass


class HealthMonitor:
    def __init__(self, trace, window=None, minimum=None, max_failure_rate=None):
        window = setting("health", "window") if window is None else window
        minimum = setting("health", "minimum") if minimum is None else minimum
        max_failure_rate = setting("health", "max_failure_rate") if max_failure_rate is None else max_failure_rate
        self.trace = trace
        self.window, self.minimum, self.max_failure_rate = window, minimum, max_failure_rate
        self.history = defaultdict(lambda: deque(maxlen=window))

    def record(self, step, passed, reason="", entity_id=None, *, fatal=True):
        history = self.history[step]
        history.append(dict(passed=bool(passed), reason=reason, entity_id=entity_id))
        failures = sum(not r["passed"] for r in history)
        if not passed and len(history) >= self.minimum and failures / len(history) > self.max_failure_rate:
            message = (f"{'Stopped early' if fatal else 'Continuing with issues'}: {step} failed {failures}/{len(history)} recent items "
                       f"(limit {self.max_failure_rate:.0%}). Latest reason: {reason}. "
                       "Inspect the health diagnostic and events.jsonl.")
            self.trace.save("artifacts/health.json" if fatal else "artifacts/health_warning.json", dict(step=step, error=message,
                fatal=fatal, measurement="final_item_outcome",
                window=self.window, minimum=self.minimum, max_failure_rate=self.max_failure_rate,
                recent=list(history)))
            self.trace.emit("health.failed" if fatal else "health.warning", entity_id=entity_id,
                            step=step, error=message, recent=list(history))
            if fatal:
                raise HealthFailure(message)


def observe(trace, step, passed, reason="", entity_id=None, *, fatal=True):
    if hasattr(trace, "health"):
        trace.health.record(step, passed, reason, entity_id, fatal=fatal)


def finish_item(trace, step, entity_id, error=None):
    """Record one final work-item outcome, never its intermediate retries."""
    completed = getattr(trace, "completed_items", None)
    if completed is None:
        trace.completed_items = completed = set()
    key = (step, entity_id)
    if key in completed:
        return
    completed.add(key)
    row = dict(step=step, id=entity_id, status="unresolved" if error else "completed",
               reason=str(error) if error else "Validated item completed")
    trace.emit("item.unresolved" if error else "item.completed", entity_id=entity_id, **row)
    if error:
        if not hasattr(trace, "unresolved_items"):
            trace.unresolved_items = []
        trace.unresolved_items.append(row)
        # Persist before the circuit breaker can stop a systematically failing stage.
        trace.save("artifacts/unresolved_items.json", trace.unresolved_items)
    observe(trace, step, not error, row["reason"], entity_id)
