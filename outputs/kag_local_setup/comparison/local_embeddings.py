"""Keep KAG's Ollama embedding client on one event loop across all batches."""
import asyncio
from kag.interface import VectorizeModelABC
from kag.common.vectorize_model.ollama_model import OllamaVectorizeModel


@VectorizeModelABC.register("local_ollama")
class LocalOllamaVectorizer(OllamaVectorizeModel):
    # Native vectorize() creates/closes a loop for every call, but reuses its
    # pooled AsyncClient. Its second batch then fails with 'Event loop is closed'.
    # All embedding generation and batching remain inherited from KAG.
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._local_runner = asyncio.Runner()
        self._local_closed = False

    def vectorize(self, texts):
        return self._local_runner.run(self.avectorize(texts))

    def close(self):
        if not self._local_closed:
            try:
                self._local_runner.run(self.aclient._client.aclose())
            finally:
                self._local_runner.close()
                self._local_closed = True
