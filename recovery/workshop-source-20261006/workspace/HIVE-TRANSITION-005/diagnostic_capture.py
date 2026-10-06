"""Diagnostic-only HTTP boundary recording. No production prompt/body mutations."""
import hashlib, json
from pathlib import Path
import httpx

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False, default=str)+'\n').encode())

class TeeStream(httpx.AsyncByteStream):
    def __init__(self, inner, path): self.inner, self.path = inner, path
    async def __aiter__(self):
        with self.path.open('xb') as file:
            async for chunk in self.inner:
                file.write(chunk); file.flush()
                yield chunk
    async def aclose(self): await self.inner.aclose()

def install(provider, root):
    root = Path(root)
    real_client = httpx.AsyncClient
    count = 0
    class Recorder(httpx.AsyncHTTPTransport):
        async def handle_async_request(self, request):
            nonlocal count
            if request.url.path != '/api/chat':
                return await super().handle_async_request(request)
            assert str(request.url) == 'http://127.0.0.1:11434/api/chat'
            payload = request.content
            assert json.loads(payload)['model'] == 'qwen2.5-coder:14b'
            count += 1
            folder = root / f'{count:02d}'
            folder.mkdir(parents=True, exist_ok=False)
            (folder / 'wire-request.json').write_bytes(payload)
            save(folder / 'transport.json', {'endpoint': str(request.url), 'method': request.method,
                 'body_bytes':len(payload), 'body_sha256':hashlib.sha256(payload).hexdigest(),
                 'capture_point':'AsyncHTTPTransport.handle_async_request, before super/send'})
            response = await super().handle_async_request(request)
            save(folder / 'http-response.json', {'status_code':response.status_code})
            response.stream = TeeStream(response.stream, folder / 'response.ndjson')
            return response
    def client(*args, **kwargs):
        return real_client(*args, transport=Recorder(), **kwargs)
    provider.httpx.AsyncClient = client
    return lambda: setattr(provider.httpx, 'AsyncClient', real_client)
