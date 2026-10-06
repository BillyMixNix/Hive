from fastapi import FastAPI

app = FastAPI(version='0.10.1')

@app.get('/api/health')
def health():
    return {'ok': True, 'version': app.version, 'jobs': {}}
