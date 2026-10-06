
import asyncio
from workshop import providers

def test_set_ollama_base():
    old=providers.ollama_base()
    try:
        providers.set_ollama_base("http://localhost:11434/")
        assert providers.ollama_base()=="http://localhost:11434"
    finally:
        providers.set_ollama_base(old)

def test_set_ollama_base_requires_http():
    try:
        providers.set_ollama_base("127.0.0.1:11434")
        assert False
    except ValueError:
        pass
