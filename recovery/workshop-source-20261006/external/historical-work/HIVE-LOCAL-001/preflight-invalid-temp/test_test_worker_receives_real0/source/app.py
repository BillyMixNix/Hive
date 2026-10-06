from fastapi import FastAPI

app = FastAPI()

@app.get('/health')
def health_endpoint():
    return {'ok': True, 'source': 'real app route'}
