"""Log native calls and apply explicit local Ollama generation settings."""
import functools
from .local_generation import CURRENT_RESPONSE


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


class Observer:
    def __init__(self, trace, generation_options=None):
        self.trace = trace
        self.generation_options = generation_options or {}
        self.chunk_id = None
        self.calls = 0
        self.embedding_calls = 0
        self.prompt_tokens = 0
        self.output_tokens = 0
        self.issues = []

    def start(self, operation, args, kwargs):
        if operation == "chat":
            self.calls += 1
        else:
            self.embedding_calls += 1
        return self.trace.emit("kag.model.request", entity_id=self.chunk_id,
                               operation=operation, role=(CURRENT_RESPONSE.get() or (None,))[0],
                               args=plain(args), kwargs=plain(kwargs))

    def chat_arguments(self, kwargs):
        kwargs = {**self.generation_options, **kwargs}
        response = CURRENT_RESPONSE.get()
        if response is not None:
            kwargs["format"] = response[1]
        return kwargs

    def finish(self, operation, request, response):
        raw = plain(response)
        self.trace.emit("kag.model.response", entity_id=self.chunk_id,
                        parent_id=request, operation=operation, response=raw)
        if operation == "chat" and isinstance(raw, dict):
            self.prompt_tokens += raw.get("prompt_eval_count") or 0
            self.output_tokens += raw.get("eval_count") or 0
            if raw.get("done_reason") == "length":
                self.issues.append({"chunk_id": self.chunk_id, "operation": operation,
                                    "reason": "Upstream model output reached its length limit"})
                raise ValueError("KAG model output reached its token limit; increase max_output_tokens in config.json")

    def failure(self, operation, request, exc):
        self.issues.append({"chunk_id": self.chunk_id, "operation": operation,
                            "reason": str(exc)})
        self.trace.emit("kag.model.failed", entity_id=self.chunk_id,
                        parent_id=request, operation=operation, error=str(exc))

    def sync_client(self, client):
        owner = self

        class Proxy:
            def __getattr__(self, name):
                method = getattr(client, name)
                if name != "chat":
                    return method

                @functools.wraps(method)
                def call(*args, **kwargs):
                    kwargs = owner.chat_arguments(kwargs)
                    request = owner.start(name, args, kwargs)
                    try:
                        result = method(*args, **kwargs)
                    except Exception as exc:
                        owner.failure(name, request, exc)
                        raise
                    owner.finish(name, request, result)
                    return result
                return call
        return Proxy()

    def async_client(self, client):
        owner = self

        class Proxy:
            def __getattr__(self, name):
                method = getattr(client, name)
                if name not in {"embeddings", "embed", "chat"}:
                    return method

                @functools.wraps(method)
                async def call(*args, **kwargs):
                    if name == "chat":
                        kwargs = owner.chat_arguments(kwargs)
                    request = owner.start(name, args, kwargs)
                    try:
                        result = await method(*args, **kwargs)
                    except Exception as exc:
                        owner.failure(name, request, exc)
                        raise
                    owner.finish(name, request, result)
                    return result
                return call
        return Proxy()
