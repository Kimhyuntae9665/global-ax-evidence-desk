"""Optional loopback LLM drafting; exact source checks are not entailment checks."""
import json
import re
from urllib.request import Request, urlopen
from urllib.error import URLError

URL = 'http://127.0.0.1:8891/generate'


def validate_output(raw, citations):
    cleaned = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
    result = json.loads(cleaned)
    if not isinstance(result, dict) or not all(isinstance(result.get(k), str) for k in ('doc_id','quote','answer')):
        raise ValueError('AI 출력 형식이 맞지 않아 초안을 보류했습니다.')
    source = next((c for c in citations if c['doc_id'] == result['doc_id'] and c['quote'] == result['quote']), None)
    if source is None:
        raise ValueError('AI 인용이 검색 원문과 일치하지 않아 초안을 보류했습니다.')
    if not result['answer'].strip() or len(result['answer']) > 2000:
        raise ValueError('AI 초안 길이를 확인할 수 없어 보류했습니다.')
    return result, source


def augment(result, question, language):
    out = dict(result)
    payload = json.dumps({'question':question, 'citations':result['citations'], 'language':language},ensure_ascii=False).encode('utf-8')
    try:
        with urlopen(Request(URL, data=payload, headers={'Content-Type':'application/json'}), timeout=90) as response:
            generated = json.loads(response.read(20000))
        draft, source = validate_output(generated['raw'], result['citations'])
        out.update(mode='qwen-grounded-draft', generated=True, answer=draft['answer'], citations=[source], model=generated['model'], model_revision=generated['revision'], generation_ms=generated['generation_ms'], quote_verified=True, semantic_verified=False)
        out['notice'] = 'AI 초안입니다. 원문 인용 일치만 검사했으며 의미·업무 적합성은 담당자가 확인해야 합니다.'
        out['raw_generation'] = generated['raw']
    except (URLError, TimeoutError, OSError) as error:
        out.update(mode='generation-unavailable', generated=False, generation_error='로컬 모델 서버가 응답하지 않아 검색 원문만 표시합니다.')
    except (KeyError, TypeError, ValueError) as error:
        out.update(mode='generation-rejected', generated=False, abstained=True, answer='AI 초안을 보류했습니다. 인용 원문을 직접 확인해 주세요.', generation_error=str(error), raw_generation=generated.get('raw','') if 'generated' in locals() else '', notice='실제 모델 출력을 형식·인용 검사에서 보류했습니다. 원문을 직접 확인해 주세요.')
        if 'generated' in locals():
            out.update(model=generated.get('model'), model_revision=generated.get('revision'), generation_ms=generated.get('generation_ms'))
    return out
