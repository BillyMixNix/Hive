from fastapi import FastAPI

app = FastAPI()
ROUTE_TEXT = "@app.get('/api/string-only')"
# @app.get('/api/comment-only')

@app.get('/api/dynamic')
def dynamic():
    payload = {'guessed': True}
    return payload

@app.get('/api/outer')
async def outer():
    def nested():
        return {'nested_only': True}
    return {'real': True}

def container():
    @app.get('/api/nested-route')
    def nested_route():
        return {'fake': True}
