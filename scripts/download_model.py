"""Explicit optional model download from official HF Qwen repository."""
import argparse
from huggingface_hub import snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument('--destination', required=True)
args = parser.parse_args()
print(snapshot_download('Qwen/Qwen2.5-1.5B-Instruct', revision='989aa7980e4cf806f80c7fef2b1adb7bc71aa306',
                        local_dir=args.destination, token=False,
                        allow_patterns=['*.json', '*.safetensors', '*.txt', '*.model']))
