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
