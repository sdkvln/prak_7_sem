"""Visualization: веб-страница для запуска сценариев (прослойка над Web Master)."""
import os

import httpx
import yaml
from flask import Flask, Response, render_template, request

config = yaml.safe_load(open(os.getenv("CONFIG_PATH", "config.yaml")))
WEB_MASTER = config["web_master_url"]

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/<path:path>", methods=["GET", "POST", "DELETE"])
def proxy(path):
    """Все запросы страницы уходят в Web Master."""
    try:
        resp = httpx.request(request.method, f"{WEB_MASTER}/api/{path}",
                             params=request.args, content=request.get_data(),
                             headers={"Content-Type": "application/json"},
                             timeout=config["timeout_sec"])
    except httpx.HTTPError as exc:
        return {"detail": f"Web Master недоступен: {exc}"}, 503
    return Response(resp.content, resp.status_code, content_type="application/json")


@app.route("/report/<model_name>")
def report(model_name):
    """Сценарий 4: отчёт по модели в виде скачиваемого HTML-файла."""
    try:
        resp = httpx.get(f"{WEB_MASTER}/api/scenarios/report",
                         params={"model_name": model_name}, timeout=30)
    except httpx.HTTPError as exc:
        return f"Web Master недоступен: {exc}", 503
    if resp.status_code != 200:
        return f"Ошибка: {resp.json().get('detail')}", resp.status_code
    html = render_template("report.html", m=resp.json())
    return Response(html, headers={
        "Content-Disposition": f"attachment; filename=report_{model_name}.html"})


if __name__ == "__main__":
    app.run(host=config["host"], port=config["port"])
