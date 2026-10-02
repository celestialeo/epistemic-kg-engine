import json
from ollama import Client

client = Client(host="http://127.0.0.1:11434", timeout=600)
for name in ("qwen3.5:9b", "nomic-embed-text"):
    print(f"Downloading {name}", flush=True)
    last = None
    for event in client.pull(name, stream=True):
        percent = int(100 * (event.completed or 0) / event.total) if event.total else None
        state = (event.status, percent // 10 if percent is not None else None)
        if state != last:
            print(json.dumps({"model": name, "status": event.status,
                              "percent": percent, "total_bytes": event.total}), flush=True)
            last = state
print(client.list().model_dump_json(), flush=True)
