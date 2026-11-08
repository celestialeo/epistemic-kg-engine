"""Local iteration harness: reuse validated exact requests, re-run all validators.

Only use caches produced by this local model installation during the current
experiment. Production replay remains available without this helper.
"""
import json
from pathlib import Path
import sys
from unittest.mock import patch

from pipeline.models import Models
from pipeline.replay_background import main


def replay():
    source, cache = map(Path, sys.argv[1:3])
    manifest = json.loads((cache / "manifest.json").read_text(encoding="utf-8"))
    if Path(manifest["source_run"]).resolve() != source.resolve():
        raise ValueError("Cache must belong to the same saved document")
    requests, responses, valid = {}, {}, set()
    for line in (cache / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        data = event["data"]
        if event["event"] == "model.request":
            requests[event["event_id"]] = Models.cache_key("model.request", data)
        elif event["event"] == "model.response":
            responses[event["parent_id"]] = dict(response=data["response"],
                source_event=event["event_id"], source_run=event["run_id"])
        elif event["event"] == "validation.completed":
            valid.add(event["parent_id"])

    class CachedModels(Models):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.cache.update({requests[key]: responses[key] for key in valid
                               if key in requests and key in responses})
            self.trace.emit("cache.parsed", source_run=str(cache), validated_entries=len(self.cache),
                            scope="Exact prompt, schema, model, options and think matches; validators re-run")

    def saved_seeds(extractions, chunks, concepts, trace, **kwargs):
        state = json.loads((cache / "artifacts/seeds.json").read_text(encoding="utf-8"))
        trace.save("artifacts/seeds.json", dict(state, replayed_from=str(cache)))
        return state["selected"]

    with patch("pipeline.replay_background.Models", CachedModels), patch(
        "pipeline.replay_background.collect_seeds", saved_seeds
    ):
        main([str(source)])


if __name__ == "__main__":
    replay()
