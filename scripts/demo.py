"""Прогон всех четырёх сценариев через API Web Master.

Система должна быть запущена: docker compose up -d --build
    python3 scripts/demo.py
"""
import json
import urllib.error
import urllib.request

API = "http://localhost:8000"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> {exc.code}: {exc.read().decode()}")


print("Состояние сервисов:", call("GET", "/api/status"))

print("\n1. Сбор данных")
call("DELETE", "/api/data")
print(call("POST", "/api/scenarios/collect", {"batch_size": 10000, "batches": 5}))

print("\n2. Обучение модели")
r = call("POST", "/api/scenarios/train", {"model_name": "rf_main", "model_type": "random_forest"})
print("метрики:", r["metrics"])

print("\n3. Оценка квартиры (Москва, 2 комнаты, 54 м², 7/17 этаж, панель)")
apartment = {"region": 3, "area": 54, "rooms": 2, "kitchen_area": 9, "level": 7, "levels": 17,
             "building_type": 2, "object_type": 1}
print(call("POST", "/api/scenarios/predict", {"model_name": "rf_main", "apartment": apartment}))

print("\n4. Отчёт по модели")
r = call("GET", "/api/scenarios/report?model_name=rf_main")
print("значимость признаков:", r["feature_importance"])
print("HTML-отчёт: http://localhost:8050/report/rf_main")
