
from __future__ import annotations
import os, base64, httpx, shutil, subprocess, asyncio, json, contextlib
from pathlib import Path

OPENAI_BASE = "https://api.openai.com/v1"
OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL","http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT_TIMEOUT = 900.0
OLLAMA_TOTAL_GENERATION_TIMEOUT = 900.0
OLLAMA_CANCEL_POLL_SECONDS = 0.1
_last_ollama_error = ""

class OllamaRequestError(RuntimeError):
    """Local provider failure retaining transport and endpoint diagnostics."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable

_ephemeral_key = None

def set_ephemeral_key(key: str):
    global _ephemeral_key
    _ephemeral_key = key.strip() or None

def openai_key():
    return _ephemeral_key or os.environ.get("OPENAI_API_KEY","").strip()

def set_ollama_base(url: str):
    global OLLAMA_BASE
    value=(url or "").strip().rstrip("/")
    if not value.startswith(("http://","https://")):
        raise ValueError("Ollama endpoint must start with http:// or https://")
    OLLAMA_BASE=value

def ollama_base():
    return OLLAMA_BASE

def ollama_last_error():
    return _last_ollama_error

async def ollama_status():
    global _last_ollama_error
    errors=[]

    # Primary path: Ollama HTTP API.
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as c:
            r = await c.get(f"{OLLAMA_BASE}/api/tags")
            if r.is_success:
                js = r.json()
                models=[m.get("name") for m in js.get("models",[]) if m.get("name")]
                _last_ollama_error=""
                return True, models
            errors.append(f"HTTP {r.status_code} from {OLLAMA_BASE}/api/tags")
    except Exception as e:
        errors.append(f"HTTP discovery failed: {type(e).__name__}: {e}")

    # Native fallback: useful on Windows if HTTP binding/startup is odd but
    # the Ollama CLI is installed and can talk to the local daemon.
    exe=shutil.which("ollama")
    if exe:
        try:
            cp=subprocess.run([exe,"list"],capture_output=True,text=True,timeout=8)
            if cp.returncode==0:
                lines=[ln.strip() for ln in cp.stdout.splitlines() if ln.strip()]
                models=[]
                for ln in lines[1:]:
                    # NAME ID SIZE MODIFIED -- model tags cannot contain whitespace.
                    name=ln.split()[0] if ln.split() else ""
                    if name:
                        models.append(name)
                if models:
                    _last_ollama_error=""
                    return True, models
                errors.append("ollama list returned no installed models")
            else:
                errors.append(f"ollama list failed rc={cp.returncode}: {cp.stderr.strip()[:300]}")
        except Exception as e:
            errors.append(f"ollama CLI fallback failed: {type(e).__name__}: {e}")
    else:
        errors.append("ollama executable not found on PATH")

    _last_ollama_error="; ".join(errors)
    return False, []

async def ollama_has_model(model: str):
    ok, models = await ollama_status()
    return ok and model in models

def _extract_openai_text(js):
    if isinstance(js.get("output_text"), str):
        return js["output_text"]
    parts=[]
    for item in js.get("output",[]) or []:
        if item.get("type") == "message":
            for c in item.get("content",[]) or []:
                if c.get("type") in ("output_text","text") and c.get("text"):
                    parts.append(c["text"])
    return "\n".join(parts).strip()

def build_openai_response_body(model, messages, instructions, effort="medium", web=False,
                               image_data_url=None, max_output_tokens=None):
    inp = []
    for m in messages:
        inp.append({"role":m["role"],"content":[{"type":"input_text","text":m["content"]}]})
    if image_data_url and inp and inp[-1]["role"] == "user":
        inp[-1]["content"].append({"type":"input_image","image_url":image_data_url})

    body = {
        "model": model,
        "instructions": instructions,
        "input": inp,
        "reasoning": {"effort": effort},
    }
    if web:
        body["tools"] = [{"type":"web_search"}]
    if max_output_tokens is not None:
        value = int(max_output_tokens)
        if value < 1:
            raise ValueError("max_output_tokens must be at least 1")
        body["max_output_tokens"] = value
    return body

async def openai_chat(model, messages, instructions, effort="medium", web=False, image_data_url=None, max_output_tokens=None):
    key = openai_key()
    if not key:
        raise RuntimeError("No OpenAI API key is configured.")
    body = build_openai_response_body(
        model=model,
        messages=messages,
        instructions=instructions,
        effort=effort,
        web=web,
        image_data_url=image_data_url,
        max_output_tokens=max_output_tokens,
    )
    async with httpx.AsyncClient(timeout=180.0) as c:
        r = await c.post(f"{OPENAI_BASE}/responses",
                         headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},
                         json=body)
        if not r.is_success:
            raise RuntimeError(f"OpenAI {r.status_code}: {r.text[:1200]}")
        js = r.json()
    usage = js.get("usage") or {}
    return {
        "text": _extract_openai_text(js),
        "input_tokens": usage.get("input_tokens",0),
        "output_tokens": usage.get("output_tokens",0),
        "raw_id": js.get("id"),
    }

def _retryable_ollama_failure(exc):
    if isinstance(exc, OllamaRequestError):
        return exc.retryable
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError))

async def _ollama_chat_once(body, *, cancel_event=None,
                            total_timeout=OLLAMA_TOTAL_GENERATION_TIMEOUT):
    """Read one Ollama stream with independent stall, total, and cancel limits."""
    if total_timeout is None or float(total_timeout) <= 0:
        raise ValueError("total_timeout must be greater than zero")

    async def exchange():
        parts=[]
        final={}
        async with httpx.AsyncClient(timeout=OLLAMA_CHAT_TIMEOUT, trust_env=False) as c:
            async with c.stream("POST", f"{OLLAMA_BASE}/api/chat", json=body) as r:
                if not r.is_success:
                    try:
                        detail=(await r.aread()).decode(errors="replace")[:1000]
                    except Exception:
                        detail=""
                    raise OllamaRequestError(
                        f"HTTP {r.status_code}: {detail}",
                        retryable=r.status_code >= 500 or r.status_code in (408, 429),
                    )
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk=json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise OllamaRequestError(
                            f"Invalid Ollama stream JSON: {exc}", retryable=True
                        ) from exc
                    if chunk.get("error"):
                        raise OllamaRequestError(
                            f"Ollama stream error: {chunk['error']}", retryable=False
                        )
                    content=(chunk.get("message") or {}).get("content","")
                    if content:
                        parts.append(content)
                    if chunk.get("done"):
                        final=chunk
        return {
            "text": "".join(parts),
            "input_tokens": final.get("prompt_eval_count",0),
            "output_tokens": final.get("eval_count",0),
            "raw_id": None,
        }

    task=asyncio.create_task(exchange())
    deadline=asyncio.get_running_loop().time()+float(total_timeout)
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise OllamaRequestError("Ollama generation cancelled", retryable=False)
            remaining=deadline-asyncio.get_running_loop().time()
            if remaining <= 0:
                raise OllamaRequestError(
                    f"Ollama generation exceeded the {float(total_timeout):g}-second total limit",
                    retryable=False,
                )
            done,_=await asyncio.wait(
                {task}, timeout=min(OLLAMA_CANCEL_POLL_SECONDS, remaining)
            )
            if done:
                return task.result()
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

async def ollama_chat(model, messages, instructions, image_data_url=None, *,
                      response_format=None, temperature=None,
                      max_output_tokens=None, context_window=None, cancel_event=None,
                      total_timeout=OLLAMA_TOTAL_GENERATION_TIMEOUT):
    """Chat locally, optionally using a JSON schema or 'json' response format."""
    global _last_ollama_error
    msgs = [{"role":"system","content":instructions}] + [{"role":m["role"],"content":m["content"]} for m in messages]
    if image_data_url and msgs:
        try:
            b64 = image_data_url.split(",",1)[1]
            msgs[-1]["images"] = [b64]
        except Exception:
            pass
    body = {"model":model,"messages":msgs,"stream":True}
    if response_format is not None:
        body["format"] = response_format
    options={}
    if temperature is not None:
        options["temperature"] = temperature
    if max_output_tokens is not None:
        value=int(max_output_tokens)
        if value < 1:
            raise ValueError("max_output_tokens must be at least 1")
        options["num_predict"] = value
    if context_window is not None:
        if type(context_window) is not int or context_window < 1:
            raise ValueError("context_window must be a positive integer")
        if max_output_tokens is not None and options["num_predict"] >= context_window:
            raise ValueError("context_window must exceed max_output_tokens")
        options["num_ctx"] = context_window
        # Structured agent prompts must reach the runtime intact or fail.
        # Ollama's default can silently retain only a prompt prefix and tail.
        body["truncate"] = False
    if options:
        body["options"] = options
    last=None
    for attempt in (1, 2):
        try:
            result=await _ollama_chat_once(
                body, cancel_event=cancel_event, total_timeout=total_timeout
            )
            _last_ollama_error=""
            break
        except Exception as exc:
            last=exc
            _last_ollama_error=f"chat attempt {attempt}/2: {type(exc).__name__}: {exc}"
            if attempt == 1 and _retryable_ollama_failure(exc):
                await asyncio.sleep(0)
            else:
                break
    else:
        raise OllamaRequestError(f"Ollama chat failed at {OLLAMA_BASE}: {_last_ollama_error}") from last
    if last is not None and "result" not in locals():
        raise OllamaRequestError(f"Ollama chat failed at {OLLAMA_BASE}: {_last_ollama_error}") from last
    return result

async def generate_image(prompt, quality="low", size="1024x1024", model="gpt-image-2.5-flare"):
    key=openai_key()
    if not key:
        raise RuntimeError("No OpenAI API key is configured.")
    body={"model":model,"prompt":prompt,"quality":quality,"size":size}
    async with httpx.AsyncClient(timeout=240.0) as c:
        r=await c.post(f"{OPENAI_BASE}/images/generations",
                       headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body)
        if not r.is_success:
            raise RuntimeError(f"Image API {r.status_code}: {r.text[:1200]}")
        js=r.json()
    d=(js.get("data") or [{}])[0]
    return d

async def create_video(prompt, seconds=4, size="1280x720", model="sora-2"):
    key=openai_key()
    if not key:
        raise RuntimeError("No OpenAI API key is configured.")
    body={"model":model,"prompt":prompt,"seconds":str(seconds),"size":size}
    async with httpx.AsyncClient(timeout=60.0) as c:
        r=await c.post(f"{OPENAI_BASE}/videos",
                       headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body)
        if not r.is_success:
            raise RuntimeError(f"Video API {r.status_code}: {r.text[:1200]}")
        return r.json()

async def get_video(video_id):
    key=openai_key()
    if not key:
        raise RuntimeError("No OpenAI API key is configured.")
    async with httpx.AsyncClient(timeout=30.0) as c:
        r=await c.get(f"{OPENAI_BASE}/videos/{video_id}",headers={"Authorization":f"Bearer {key}"})
        if not r.is_success:
            raise RuntimeError(f"Video API {r.status_code}: {r.text[:1000]}")
        return r.json()
