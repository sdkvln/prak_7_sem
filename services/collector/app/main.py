"""Collector: отдаёт CSV-набор батчами и загружает их в Storage."""
import json
import logging
import os
from pathlib import Path

import httpx
import pandas as pd
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

config = yaml.safe_load(open(os.getenv("CONFIG_PATH", "config.yaml")))

Path(config["log_file"]).parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(config["log_file"])],
)
log = logging.getLogger("collector")

data = pd.read_csv(config["dataset_path"])
data = data[data["price"] > 0]  # объявления без цены бесполезны
state = {"offset": 0}  # позиция следующего батча

app = FastAPI(title="Collector")


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    log.exception("ошибка при обработке %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": str(exc)})


def get_rows(offset: int, size: int) -> list[dict]:
    if offset >= len(data):
        raise HTTPException(404, "данные в источнике закончились")
    part = data.iloc[offset:offset + size]
    return json.loads(part.to_json(orient="records"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/batch")
def batch(offset: int | None = None, size: int | None = None):
    """Вернуть батч данных без сохранения (по умолчанию со следующей позиции)."""
    offset = state["offset"] if offset is None else offset
    rows = get_rows(offset, size or config["default_batch_size"])
    return {"offset": offset, "count": len(rows), "rows": rows}


@app.post("/collect")
def collect(size: int | None = None):
    """Взять следующий батч и сохранить его в Storage."""
    size = size or config["default_batch_size"]
    rows = get_rows(state["offset"], size)
    try:
        resp = httpx.post(f"{config['storage_url']}/listings/bulk", json=rows, timeout=60)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("не удалось сохранить батч в Storage: %s", exc)
        raise HTTPException(502, f"Storage недоступен: {exc}")
    start = state["offset"]
    state["offset"] += len(rows)
    log.info("загружен батч: строки %d-%d (%d шт.)", start, state["offset"] - 1, len(rows))
    return {"loaded": len(rows), "offset": state["offset"], "remaining": len(data) - state["offset"]}


@app.post("/reset")
def reset():
    state["offset"] = 0
    log.info("позиция сброшена")
    return {"offset": 0}


if __name__ == "__main__":
    uvicorn.run(app, host=config["host"], port=config["port"])
