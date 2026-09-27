"""Append-only, ordered application events and hashed run artifacts."""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


class Trace:
    def __init__(self, directory, run_id):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=False)
        self.run_id = run_id
        self.sequence = 0
        self.started = time.monotonic()
        self.counts = Counter()
        self.stage = "setup"
        self.stream = (self.directory / "events.jsonl").open("x", encoding="utf-8")
        self.artifacts = {}

    def emit(self, event, *, entity_id=None, parent_id=None, **data):
        self.sequence += 1
        now = datetime.now(timezone.utc)
        row = dict(schema_version=1, run_id=self.run_id, sequence=self.sequence,
                   event_id=f"event_{self.sequence:06d}",
                   timestamp=now.isoformat(), timestamp_local=now.astimezone().isoformat(),
                   elapsed_seconds=round(time.monotonic() - self.started, 6),
                   stage=self.stage, event=event, entity_id=entity_id,
                   parent_id=parent_id, data=data)
        self.stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        self.stream.flush()
        self.counts[event] += 1
        return row["event_id"]

    def text(self, name, content):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = content.encode("utf-8")
        path.write_bytes(raw)
        info = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        self.artifacts[name] = info
        self.emit("artifact.written", path=name, **info)
        return path

    def save(self, name, value):
        return self.text(name, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")

    @contextmanager
    def span(self, name):
        previous = self.stage
        self.stage = name
        start = time.monotonic()
        event = self.emit("stage.started")
        print(f"[{name}]", flush=True)
        try:
            yield
        except BaseException as exc:
            self.emit("stage.failed", parent_id=event, error=str(exc), error_type=type(exc).__name__)
            raise
        else:
            self.emit("stage.completed", parent_id=event, duration_seconds=time.monotonic() - start)
        finally:
            self.stage = previous

    def close(self):
        self.stream.close()
