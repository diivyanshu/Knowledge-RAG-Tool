"""Create the slim runtime models: export the embedding model and reranker to ONNX,
quantise to int8 (~4x smaller), verify against the full models, and save to onnx_dir.
Run once after build_index.py, inside the full (torch) environment."""
import os, sys, shutil, tempfile
import numpy as np, torch
from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification
from onnxruntime.quantization import quantize_dynamic, QuantType
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_config, connect, log

class EmbedWrap(torch.nn.Module):
    def __init__(self, m): super().__init__(); self.m = m
    def forward(self, input_ids, attention_mask): return self.m(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
class RerankWrap(torch.nn.Module):
    def __init__(self, m): super().__init__(); self.m = m
    def forward(self, input_ids, attention_mask): return self.m(input_ids=input_ids, attention_mask=attention_mask).logits

def export(name, kind, out_dir):
    log(f"exporting {name} ...")
    tok = AutoTokenizer.from_pretrained(name)
    m = (AutoModel if kind == "embed" else AutoModelForSequenceClassification).from_pretrained(
        name, attn_implementation="eager").eval().float()
    w = EmbedWrap(m) if kind == "embed" else RerankWrap(m)
    tmp = tempfile.mkdtemp(dir=os.path.dirname(out_dir)); f32 = os.path.join(tmp, "model_fp32.onnx")
    enc = tok(["example text"], return_tensors="pt")
    oname = "last_hidden_state" if kind == "embed" else "logits"
    kw = dict(input_names=["input_ids", "attention_mask"], output_names=[oname], opset_version=17,
              do_constant_folding=True, dynamic_axes={"input_ids": {0: "b", 1: "s"}, "attention_mask": {0: "b", 1: "s"}, oname: {0: "b"}})
    try:
        torch.onnx.export(w, (enc["input_ids"], enc["attention_mask"]), f32, dynamo=False, **kw)
    except TypeError:   # older torch without the 'dynamo' switch
        torch.onnx.export(w, (enc["input_ids"], enc["attention_mask"]), f32, **kw)
    os.makedirs(out_dir, exist_ok=True)
    log("quantising to int8 ...")
    quantize_dynamic(f32, os.path.join(out_dir, "model.onnx"), weight_type=QuantType.QInt8)
    tok.backend_tokenizer.save(os.path.join(out_dir, "tokenizer.json"))
    shutil.rmtree(tmp, ignore_errors=True)
    return tok, m

def main():
    cfg = load_config(); db = connect(cfg); od = cfg["onnx_dir"]
    os.makedirs(od, exist_ok=True)
    final = {k: os.path.join(od, k) for k in ("embed", "rerank")}
    stage = {k: v + ".new" for k, v in final.items()}
    tok, m = export(cfg["embed_model"], "embed", stage["embed"])
    sample = [r[0] for r in db.execute("SELECT text FROM chunks ORDER BY random() LIMIT 24")] or ["test sentence", "दूसरा वाक्य"]
    with torch.no_grad():
        e = tok(sample, padding=True, truncation=True, max_length=512, return_tensors="pt")
        ref = m(**e).last_hidden_state[:, 0].numpy()
    import onnxruntime as ort
    from tokenizers import Tokenizer
    s = ort.InferenceSession(os.path.join(stage["embed"], "model.onnx"), providers=["CPUExecutionProvider"])
    tk = Tokenizer.from_file(os.path.join(stage["embed"], "tokenizer.json")); tk.enable_truncation(512)
    tk.enable_padding(pad_id=tok.pad_token_id, pad_token=tok.pad_token)
    en = tk.encode_batch(sample)
    got = s.run(None, {"input_ids": np.array([x.ids for x in en]), "attention_mask": np.array([x.attention_mask for x in en])})[0][:, 0]
    cos = (ref * got).sum(1) / np.linalg.norm(ref, axis=1) / np.linalg.norm(got, axis=1)
    log(f"embedding check: mean cosine full vs slim = {cos.mean():.4f} (min {cos.min():.4f})")
    if cos.mean() < float(os.environ.get("SLIM_MIN_COS", "0.95")):
        shutil.rmtree(stage["embed"], ignore_errors=True)
        log("Slim embedding model differs too much - keeping the full models. Nothing changed."); sys.exit(1)
    if cfg["use_reranker"]:
        export(cfg["rerank_model"], "rerank", stage["rerank"])
    for k in stage:
        if os.path.exists(stage[k]):
            shutil.rmtree(final[k], ignore_errors=True); os.replace(stage[k], final[k])
    total = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(od) for f in fs) / 1e9
    log(f"slim models ready in {od} ({total:.2f} GB)")

if __name__ == "__main__":
    main()
