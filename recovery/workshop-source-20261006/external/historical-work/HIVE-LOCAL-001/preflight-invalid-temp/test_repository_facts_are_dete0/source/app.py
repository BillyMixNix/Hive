from fastapi import FastAPI

app = FastAPI(title='Example')

@app.get('/api/health')
def health():
    return {'ok': True}
