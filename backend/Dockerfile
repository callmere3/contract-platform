FROM python:3.12-slim

WORKDIR /app

# libpq-dev и gcc нужны для сборки psycopg (клиент PostgreSQL),
# curl — чтобы docker-compose мог сходить в /health при желании добавить healthcheck и на api
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
