"""ML Service: создание, обучение, применение и описание моделей цены квартиры."""
import json
import os
from datetime import datetime
from pathlib import Path

import httpx
import joblib
import numpy as np
import pandas as pd
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

config = yaml.safe_load(open(os.getenv("CONFIG_PATH", "config.yaml")))
MODELS_DIR = Path(config["models_dir"])
MODELS_DIR.mkdir(parents=True, exist_ok=True)
FEATURES = config["features"]

app = FastAPI(title="ML Service")


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": str(exc)})


class CreateModel(BaseModel):
    name: str
    model_type: str


class Apartment(BaseModel):
    region: int
    area: float
    rooms: int = 1
    level: int = 1
    levels: int = 5
    kitchen_area: float = 8
    building_type: int = 0
    object_type: int = 1


# Каждая модель — два файла: <name>.json (описание) и <name>.joblib (обученная модель)
def meta_path(name: str) -> Path:
    return MODELS_DIR / f"{name}.json"


def load_meta(name: str) -> dict:
    if not meta_path(name).exists():
        raise HTTPException(404, f"модель {name} не найдена")
    return json.loads(meta_path(name).read_text())


def save_meta(meta: dict) -> None:
    meta_path(meta["name"]).write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def make_regressor(model_type: str):
    params = config["model_types"][model_type]
    if model_type == "linear":
        # коды региона, типа дома и рынка — категории, а не числа
        categorical = ["region", "building_type", "object_type"]
        encode = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore"), categorical)],
                                   remainder="passthrough")
        return make_pipeline(encode, LinearRegression(**params))
    return RandomForestRegressor(**params, n_jobs=-1, random_state=42)


def load_data() -> pd.DataFrame:
    rows, offset = [], 0
    while True:
        resp = httpx.get(f"{config['storage_url']}/listings",
                         params={"limit": 10000, "offset": offset}, timeout=60)
        resp.raise_for_status()
        part = resp.json()
        rows += part
        if len(part) < 10000:
            break
        offset += 10000
    df = pd.DataFrame(rows)
    if df.empty:
        raise HTTPException(400, "в Storage нет данных, сначала выполните сбор данных")
    for col, (lo, hi) in config["filters"].items():
        df = df[df[col].between(lo, hi)]
    return df.dropna(subset=FEATURES + [config["target"]])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/model-types")
def model_types():
    return config["model_types"]


@app.post("/models", status_code=201)
def create_model(body: CreateModel):
    if body.model_type not in config["model_types"]:
        raise HTTPException(422, f"неизвестный тип модели {body.model_type}, "
                                 f"доступны: {list(config['model_types'])}")
    if meta_path(body.name).exists():
        raise HTTPException(409, f"модель {body.name} уже существует")
    meta = {"name": body.name, "model_type": body.model_type, "status": "created",
            "created_at": datetime.now().isoformat(timespec="seconds")}
    save_meta(meta)
    return meta


@app.get("/models")
def list_models():
    return [json.loads(p.read_text()) for p in sorted(MODELS_DIR.glob("*.json"))]


@app.post("/models/{name}/train")
def train(name: str):
    meta = load_meta(name)
    df = load_data()
    X, y = df[FEATURES], df[config["target"]]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=config["test_size"], random_state=42)

    model = make_regressor(meta["model_type"])
    model.fit(X_train, np.log(y_train))  # цена распределена логнормально
    pred = np.exp(model.predict(X_test))

    # значимость признака: насколько растёт ошибка, если перемешать его значения
    sample = X_test.sample(min(len(X_test), 3000), random_state=42)
    importance = permutation_importance(model, sample, np.log(y_test.loc[sample.index]),
                                        n_repeats=3, random_state=42).importances_mean
    importance = np.clip(importance, 0, None) / max(np.clip(importance, 0, None).sum(), 1e-9)

    meta.update({
        "status": "trained",
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "rows_train": len(X_train),
        "rows_test": len(X_test),
        "metrics": {
            "mae": round(float(mean_absolute_error(y_test, pred))),
            "mape": round(float(mean_absolute_percentage_error(y_test, pred)), 3),
            # R² по логарифму цены: модель учится на нём, и он не так чувствителен к выбросам
            "r2": round(float(r2_score(np.log(y_test), np.log(pred))), 3),
        },
        "feature_importance": dict(sorted(
            ((f, round(float(v), 4)) for f, v in zip(FEATURES, importance)),
            key=lambda kv: -kv[1])),
    })
    joblib.dump(model, MODELS_DIR / f"{name}.joblib")
    save_meta(meta)
    return meta


@app.post("/models/{name}/predict")
def predict(name: str, apartment: Apartment):
    meta = load_meta(name)
    if meta["status"] != "trained":
        raise HTTPException(409, f"модель {name} ещё не обучена")
    model = joblib.load(MODELS_DIR / f"{name}.joblib")
    X = pd.DataFrame([apartment.model_dump()])[FEATURES]
    price = float(np.exp(model.predict(X)[0]))
    return {"model": name, "price": round(price), "price_per_m2": round(price / apartment.area)}


@app.get("/models/{name}/summary")
def summary(name: str):
    return load_meta(name)


@app.delete("/models/{name}")
def delete_model(name: str):
    load_meta(name)
    meta_path(name).unlink()
    (MODELS_DIR / f"{name}.joblib").unlink(missing_ok=True)
    return {"deleted": name}


if __name__ == "__main__":
    uvicorn.run(app, host=config["host"], port=config["port"])
