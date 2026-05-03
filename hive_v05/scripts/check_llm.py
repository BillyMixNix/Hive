import requests
from hive_llm import OLLAMA_URL

payload = {"model": "qwen2.5-coder:7b", "prompt": "Hello", "stream": False}
try:
    r = requests.post(OLLAMA_URL, json=payload, timeout=10)
    print('Status:', r.status_code)
    try:
        print('JSON:', r.json())
    except Exception as e:
        print('Response text:', r.text[:1000])
except Exception as e:
    print('ERROR:', repr(e))
