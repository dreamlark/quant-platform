import os
import sys
import traceback

sys.path.insert(0, "_vendor/Kronos")
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from model import Kronos, KronosTokenizer

print("=== 试加载 Tokenizer ===")
try:
    tok = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    print("tokenizer OK:", type(tok))
except Exception:
    traceback.print_exc()

print("=== 试加载 Model ===")
try:
    m = Kronos.from_pretrained("NeoQuasar/Kronos-small")
    print("model OK:", type(m))
except Exception:
    traceback.print_exc()
