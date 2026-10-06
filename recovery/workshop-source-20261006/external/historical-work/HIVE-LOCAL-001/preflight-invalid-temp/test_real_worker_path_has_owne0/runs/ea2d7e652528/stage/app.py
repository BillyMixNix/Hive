from fastapi import FastAPI

app = FastAPI()

@app.get('/health')
def health():
    return {'ok': True}


@app.get('/api/project-summary')
def project_summary():
    return {'name': 'demo', 'path': '.', 'files': 1}

