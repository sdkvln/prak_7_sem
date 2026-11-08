FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 CONFIG_PATH=/app/config.yaml

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY config.yaml .

# хост и порт берутся из config.yaml
CMD ["python", "-m", "app.main"]
