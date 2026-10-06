
from workshop.router import choose, estimate_cost

def test_auto_local():
    r=choose("auto","gpt-5.6-sol",True,"qwen:latest",False)
    assert r.provider=="ollama"

def test_web_uses_luna():
    r=choose("auto","gpt-6-astra",True,"qwen:latest",True)
    assert r.model=="gpt-5.6-luna"

def test_cost():
    assert estimate_cost("gpt-5.6-luna",1_000_000,1_000_000)==1.4
