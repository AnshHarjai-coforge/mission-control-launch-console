from fastapi.testclient import TestClient

from app.main import create_app

_ENV_NAMES = (
    "DATABASE_PATH",
    "MODEL_BACKEND",
    "AZURE_FOUNDRY_BASE_URL",
    "AZURE_FOUNDRY_API_KEY",
    "AZURE_FOUNDRY_MODEL",
    "INPUT_USD_PER_MILLION",
    "OUTPUT_USD_PER_MILLION",
    "MODEL_TIMEOUT_SECONDS",
)


def test_health_page(monkeypatch):
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert "ok" in response.text
    assert client.app.state.settings.azure_foundry_api_key == ""
