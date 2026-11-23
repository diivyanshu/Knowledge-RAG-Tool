"""Embedding + reranking with two interchangeable backends:
  torch : Hugging Face models (used for the one-time build; uses Apple GPU via MPS)
  onnx  : int8-quantised ONNX models (small 'slim' runtime, created by make_slim.py)
Both use CLS pooling + L2 normalisation, as bge-m3 dense retrieval does."""
import gc, os, threading, time
import numpy as np
from common import log

def _onnx_ready(cfg, name):
    return os.path.exists(os.path.join(cfg["onnx_dir"], name, "model.onnx"))

class _Base:
    def __init__(self, cfg, kind):
        self.cfg, self.kind = cfg, kind
        self.backend = "onnx" if _onnx_ready(cfg, kind) else "torch"
        self._m = None; self._lock = threading.Lock(); self.last = time.time()

    def unload(self):
        with self._lock:
            if self._m is not None:
                self._m = None; gc.collect(); log(f"[{self.kind}] unloaded after idle")

    def _load(self):
        if self._m is not None:
            return
        name = self.cfg["embed_model"] if self.kind == "embed" else self.cfg["rerank_model"]
        t = time.time()
        if self.backend == "onnx":
            import onnxruntime as ort
            from tokenizers import Tokenizer
            d = os.path.join(self.cfg["onnx_dir"], self.kind)
            so = ort.SessionOptions(); so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess = ort.InferenceSession(os.path.join(d, "model.onnx"), so, providers=["CPUExecutionProvider"])
            tok = Tokenizer.from_file(os.path.join(d, "tokenizer.json"))
            self._m = ("onnx", sess, tok, None)
        else:
            import torch
            from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
            dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
            cls = AutoModel if self.kind == "embed" else AutoModelForSequenceClassification
            m = cls.from_pretrained(name).eval().to(dev)
            if dev != "cpu":
                m = m.half()
            self._m = ("torch", m, AutoTokenizer.from_pretrained(name), dev)
        log(f"[{self.kind}] loaded {self.backend} model in {time.time()-t:.1f}s")

    def _run(self, a, b=None, max_len=512):
        """Returns last_hidden_state CLS (embed) or logits (rerank) as float32 numpy."""
        kind, m, tok, dev = self._m
        if kind == "torch":
            import torch
            enc = tok(a, b, padding=True, truncation=True, max_length=max_len, return_tensors="pt").to(dev)
            with torch.no_grad():
                out = m(**enc)
            x = out.last_hidden_state[:, 0] if self.kind == "embed" else out.logits.view(-1)
            return x.float().cpu().numpy()
        tok.enable_truncation(max_len)
        pad = next((p for p in ("<pad>", "[PAD]") if tok.token_to_id(p) is not None), None)
        tok.enable_padding(pad_id=tok.token_to_id(pad) if pad else 0, pad_token=pad or "[PAD]")
        encs = tok.encode_batch(list(zip(a, b)) if b is not None else a)
        ids = np.array([e.ids for e in encs], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
        names = [i.name for i in m.get_inputs()]
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.zeros_like(ids)
        out = m.run(None, {k: v for k, v in feed.items() if k in names})[0]
        return out[:, 0] if self.kind == "embed" else out.reshape(-1)

class Embedder(_Base):
    def __init__(self, cfg):
        super().__init__(cfg, "embed")

    def encode(self, texts, batch=16, max_len=None):
        max_len = max_len or self.cfg["embed_max_tokens"]
        with self._lock:
            self._load(); self.last = time.time()
            vecs = []
            for i in range(0, len(texts), batch):
                v = self._run(texts[i:i + batch], max_len=max_len)
                vecs.append(v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9))
            return np.vstack(vecs).astype(np.float32)

class Reranker(_Base):
    def __init__(self, cfg):
        super().__init__(cfg, "rerank")

    def score(self, query, passages, batch=8):
        with self._lock:
            self._load(); self.last = time.time()
            s = []
            for i in range(0, len(passages), batch):
                p = passages[i:i + batch]
                s.extend(self._run([query] * len(p), p, max_len=512).tolist())
            return s

def start_idle_reaper(models, minutes):
    def loop():
        while True:
            time.sleep(60)
            for m in models:
                if m._m is not None and time.time() - m.last > minutes * 60:
                    m.unload()
    threading.Thread(target=loop, daemon=True).start()
