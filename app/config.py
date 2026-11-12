"""Read configuration from the environment.

Unset variables stay blank. Nothing here opens a network connection or builds a client.
"""

import os
from dataclasses import dataclass

_ENV_FIELDS = (
    ("database_path", "DATABASE_PATH"),
    ("model_backend", "MODEL_BACKEND"),
    ("azure_foundry_base_url", "AZURE_FOUNDRY_BASE_URL"),
    ("azure_foundry_api_key", "AZURE_FOUNDRY_API_KEY"),
    ("azure_foundry_model", "AZURE_FOUNDRY_MODEL"),
    ("input_usd_per_million", "INPUT_USD_PER_MILLION"),
    ("output_usd_per_million", "OUTPUT_USD_PER_MILLION"),
    ("model_timeout_seconds", "MODEL_TIMEOUT_SECONDS"),
)


@dataclass(frozen=True)
class Settings:
    database_path: str
    model_backend: str
    azure_foundry_base_url: str
    azure_foundry_api_key: str
    azure_foundry_model: str
    input_usd_per_million: str
    output_usd_per_million: str
    model_timeout_seconds: str


def load_settings() -> Settings:
    values = {field: os.environ.get(name, "") for field, name in _ENV_FIELDS}
    return Settings(**values)
