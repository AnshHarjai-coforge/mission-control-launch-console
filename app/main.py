"""FastAPI entrypoint. `uvicorn app.main:app --reload` loads the `app` object."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.config import load_settings

HEALTH_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Mission Control</title>
</head>
<body>
  <h1>Mission Control</h1>
  <p>ok</p>
</body>
</html>
"""


def create_app() -> FastAPI:
    app = FastAPI(title="Mission Control")
    app.state.settings = load_settings()

    @app.get("/", response_class=HTMLResponse)
    @app.get("/health", response_class=HTMLResponse)
    def health() -> HTMLResponse:
        return HTMLResponse(HEALTH_PAGE)

    return app


app = create_app()
