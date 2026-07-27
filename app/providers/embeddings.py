"""Embedding provider 抽象。決策:bge-m3,1024 維——此數字之後寫進 Atlas 向量索引。"""
from typing import Protocol
import hashlib
import math

EMBEDDING_DIM = 1024  # bge-m3;換模型必須同步改這裡與 Atlas index,屬合約變更


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedding:
    """確定性假向量,讓檢索與計分層在沒有模型時可被測試。
    W2 修正:原版用內建 hash(),受 PYTHONHASHSEED 影響、跨行程不定值,
    「同 profile 同 job 分數不漂移」的驗收因此無法跨執行重現;
    改用 hashlib 後,任何機器、任何時間,同輸入必得同向量。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            buf: list[float] = []
            counter = 0
            while len(buf) < EMBEDDING_DIM:
                digest = hashlib.sha256(f"{counter}\x00{t}".encode()).digest()
                buf.extend((b - 127.5) / 128.0 for b in digest)
                counter += 1
            v = buf[:EMBEDDING_DIM]
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class BgeM3Embedding:
    """bge-m3 dense 向量——直接用 transformers 載入,不經 FlagEmbedding。

    W2 實戰決策:FlagEmbedding 與 transformers 隔著 torch_dtype→dtype 改名互踩
    (TypeError),且其依賴樹過大;而 dense 向量的本體只是「XLM-R 編碼器 → 取 CLS
    → L2 正規化」,用已驗證可動的 torch + transformers 自己做,零新依賴。
    同時不裝 sentencepiece(其原生擴充在 Windows + Py3.13 會 access violation),
    tokenizer 走 Rust 快速版(吃快取裡的 tokenizer.json)。

    首次執行需模型已在 HuggingFace 快取(見 W2 note 的下載指引);
    建議搭配 HF_HUB_OFFLINE=1 完全離線載入。verbose 批次時印累計進度。"""

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str | None = None,
                 batch_size: int = 16, max_length: int = 1024, verbose: bool = True):
        import torch
        from transformers import AutoModel, AutoTokenizer  # 延遲載入:CI 不需要
        self._torch = torch
        self._device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        if self._device == "cuda":
            model = model.half()
        self._model = model.to(self._device).eval()
        self._batch = batch_size
        self._max_length = max_length
        self._verbose = verbose
        self._done = 0
        self._t0: float | None = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        import time
        torch = self._torch
        if self._t0 is None:
            self._t0 = time.time()
        out: list[list[float]] = []
        with torch.no_grad():
            for s in range(0, len(texts), self._batch):
                batch = texts[s:s + self._batch]
                enc = self._tokenizer(batch, padding=True, truncation=True,
                                      max_length=self._max_length,
                                      return_tensors="pt").to(self._device)
                cls = self._model(**enc).last_hidden_state[:, 0]        # CLS pooling
                cls = torch.nn.functional.normalize(cls, p=2, dim=1)    # L2 normalize
                out.extend([[float(x) for x in row] for row in cls.cpu()])
                if self._verbose and len(texts) > 1:
                    self._done += len(batch)
                    print(f"    已向量化 {self._done} 條(累計 "
                          f"{time.time() - self._t0:.0f}s)", flush=True)
        assert all(len(v) == EMBEDDING_DIM for v in out), "維度不符 1024=合約變更"
        return out
