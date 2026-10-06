"""Small development check, not held-out quality/accuracy evaluation."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
questions = [
    {'question':'What units are supported for reporting electricity?', 'language':'en'},
    {'question':'누락 값은 0으로 처리하나요?', 'language':'ko'},
]
root = Path(__file__).resolve().parents[1]
fingerprint = hashlib.sha256((root/'model_server.py').read_bytes()).hexdigest()
output = Path(args.output)
output.mkdir(parents=True, exist_ok=True)
for index, case in enumerate(questions, start=4):
    payload = dict(case, generate=True)
    request = Request('http://127.0.0.1:8765/api/ask', data=json.dumps(payload, ensure_ascii=False).encode(), headers={'Content-Type':'application/json'})
    with urlopen(request, timeout=100) as response:
        result = json.load(response)
    report = {'scope':'development check; no held-out accuracy estimate', 'question':case,
              'model_server_sha256':fingerprint, 'result':result}
    (output/f'{index:02}-development-{case["language"]}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2),encoding='utf-8')
    print(case['language'], result['mode'], result.get('generation_ms'), flush=True)
