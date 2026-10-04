"""Text embedders. Both return (n, dim) float32 arrays with L2-normalised rows."""

import hashlib
import re
import threading
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _normalise(m: np.ndarray) -> np.ndarray:
    m = m.astype(np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


class FastEmbedEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dim: int = 384) -> None:
        self.model_name = model_name
        self.dim = dim
        self._model = None
        self._lock = threading.Lock()  # embed() may run in worker threads

    def embed(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding  # lazy: loading downloads the model

                    self._model = TextEmbedding(model_name=self.model_name)
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _normalise(np.array(list(self._model.embed(texts))))


class HashingEmbedder:
    """Deterministic bag-of-words hashing embedder, used by tests."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> np.ndarray:
        m = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"\w+", t.lower()):
                h = int.from_bytes(hashlib.md5(w.encode()).digest()[:8], "big")
                m[i, h % self.dim] += 1.0
        return _normalise(m)
