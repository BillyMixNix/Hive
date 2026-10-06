from fastapi import FastAPI
from workshop import providers
app = FastAPI()

@app.get('/api/status')
async def status():
    ok, models = await providers.ollama_status()
    return {
        'ollama': ok,
        'ollama_models': models,
    }
