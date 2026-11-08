"""Web Master: единая точка входа и API четырёх сценариев использования."""
import os

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

config = yaml.safe_load(open(os.getenv("CONFIG_PATH", "config.yaml")))
SERVICES = config["services"]

app = FastAPI(title="Web Master")


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": str(exc)})


def call(service: str, method: str, path: str, **kwargs):
    """Запрос к сервису; его ошибки возвращаются клиенту с указанием сервиса."""
    try:
        resp = httpx.request(method, SERVICES[service] + path,
                             timeout=config["timeout_sec"], **kwargs)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"{service} недоступен: {exc}")
    if resp.status_code >= 400:
        body = resp.json()
        raise HTTPException(resp.status_code, f"{service}: {body.get('detail') or body.get('error')}")
    return resp.json()


class CollectRequest(BaseModel):
    batch_size: int = 1000
    batches: int = 1


class TrainRequest(BaseModel):
    model_name: str
    model_type: str = "random_forest"


class PredictRequest(BaseModel):
    model_name: str
    apartment: dict


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/status")
def status():
    """Состояние всех сервисов системы."""
    result = {}
    for name, url in SERVICES.items():
        try:
            result[name] = httpx.get(url + "/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            result[name] = False
    return result


@app.post("/api/scenarios/collect")
def scenario_collect(req: CollectRequest):
    """Сценарий 1: загрузить N батчей из Collector в Storage."""
    loaded, last = 0, {}
    for _ in range(req.batches):
        last = call("collector", "POST", "/collect", params={"size": req.batch_size})
        loaded += last["loaded"]
    total = call("storage", "GET", "/listings/count")["count"]
    return {"loaded": loaded, "remaining": last.get("remaining"), "total_in_storage": total}


@app.post("/api/scenarios/train")
def scenario_train(req: TrainRequest):
    """Сценарий 2: создать модель (если её нет) и обучить."""
    names = [m["name"] for m in call("ml_service", "GET", "/models")]
    if req.model_name not in names:
        call("ml_service", "POST", "/models",
             json={"name": req.model_name, "model_type": req.model_type})
    return call("ml_service", "POST", f"/models/{req.model_name}/train")


@app.post("/api/scenarios/predict")
def scenario_predict(req: PredictRequest):
    """Сценарий 3: оценить стоимость квартиры."""
    return call("ml_service", "POST", f"/models/{req.model_name}/predict", json=req.apartment)


@app.get("/api/scenarios/report")
def scenario_report(model_name: str):
    """Сценарий 4: описание модели — метрики и значимость признаков."""
    return call("ml_service", "GET", f"/models/{model_name}/summary")


@app.get("/api/models")
def models():
    return call("ml_service", "GET", "/models")


@app.get("/api/model-types")
def model_types():
    return list(call("ml_service", "GET", "/model-types"))


@app.delete("/api/data")
def clear_data():
    """Очистить хранилище и начать сбор данных сначала."""
    call("collector", "POST", "/reset")
    return call("storage", "DELETE", "/listings")


if __name__ == "__main__":
    uvicorn.run(app, host=config["host"], port=config["port"])
