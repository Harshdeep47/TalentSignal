"""Download the embedding model (one-time, needs network) into artifacts/models/.

    python scripts/download_model.py

BAAI/bge-small-en-v1.5 is MIT-licensed (~130 MB). After this step ranking runs
fully offline. Without the model the engine still works with lexical and
structured evidence only (semantic component disabled, weights re-normalised).
"""
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "artifacts" / "models" / "bge-small-en-v1.5"

if __name__ == "__main__":
    path = snapshot_download("BAAI/bge-small-en-v1.5", local_dir=str(DEST),
                             allow_patterns=["*.json", "*.txt", "model.safetensors", "1_Pooling/*", "modules.json"])
    print("Model saved to", path)
