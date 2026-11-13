# mission-control-launch-console

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

## Start

```bash
uvicorn app.main:app --reload
```

## Test

```bash
pytest
```

## Sample prices

`INPUT_USD_PER_MILLION` and `OUTPUT_USD_PER_MILLION` are blank in `.env.example`. Until those are set, cost uses $3 per million input tokens and $15 per million output tokens. Those samples are not a claim about the real Opus price.
